"""WF-EOS fixed-fractional vertical over the generic canonical DAG runtime."""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

from ..contracts import CapabilityRegistry
from ..engines.siesta.effective_fdf import resolve_effective_fdf, materialize_effective_fdf
from ..engines.siesta.ground_state import geometry_updates, system_label
from ..engines.siesta.relaxation import geometry_from_fdf, parse_struct_out, geometry_envelope, _fdf_logical, _float, _unit_factor
from ..engines.siesta.input_closure import resolve_scientific_input_closure
from ..engines.siesta.presets import parse_run, evaluate_relaxation
from ..engines.siesta.eos import deform, volume, final_energy, evaluate
from ..execution.capability_plugins import register_siesta_engine, SIESTA_ENGINE_CAPABILITY
from ..execution.capability_runtime import CompiledWorkflowRuntime
from ..execution.runtime_composition import compose_runtime
from ..workflows import WorkflowCompiler
from .single_fdf import build_scientific_identity, resolve_execution_spec
from .electronic_properties import _immutable_json, _immutable_copy


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _meshes(text):
    return [[int(v) for v in match.groups()] for match in re.finditer(r'^InitMesh: MESH =\s*(\d+) x\s*(\d+) x\s*(\d+)', text, re.MULTILINE)]


def _nonmagnetic(view):
    spin = view.scalar('Spin')
    polarized = view.scalar('SpinPolarized')
    if (spin is not None and spin.value.lower() != 'non-polarized') or (polarized is not None and _fdf_logical(polarized.value)):
        raise ValueError('SPIN_POLARIZED_UNSUPPORTED_V1')


def _runtime(root, sources, execution):
    tasks, identities = [], {}
    for node, fdf, outputs in sources:
        closure = resolve_scientific_input_closure(fdf)
        inputs = [{'name': item.name, 'source': item.source.relative_to(root / 'source').as_posix(),
                   'destination': item.destination, 'media_type': item.media_type, 'sha256': _hash(item.source)} for item in closure.entries]
        tasks.append({'task_id': node, 'kind': 'calculation', 'capability': SIESTA_ENGINE_CAPABILITY,
                      'inputs': inputs, 'outputs': outputs, 'resources': {}, 'settings': {'primary_input': 'fdf'}})
        identities[node] = build_scientific_identity(fdf)
    definition = root / 'source/workflow.json'
    _immutable_json(definition, {'schema_version': '1.0', 'workflow_id': 'eos', 'project_id': 'eos', 'tasks': tasks})
    compilation = WorkflowCompiler().compile(definition)
    if not compilation.valid or compilation.compiled is None:
        raise ValueError('EOS workflow compilation failed: ' + '; '.join(f.message for f in compilation.findings))
    registry = CapabilityRegistry(); register_siesta_engine(registry); registry.freeze()
    composition = compose_runtime(execution, max_parallel_steps=1, placement_probe_root=root)
    return CompiledWorkflowRuntime(workflow=compilation.compiled, registry=registry,
        root=root / 'runtime', source_root=root / 'source', scientific_identities=identities,
        execution_specs=execution, launcher=composition.launcher, allocation=composition.allocation).run()


def _source(template, destination, *, scalars=None, blocks=None):
    # Render in scratch first; source bytes in a settled stage remain immutable.
    with tempfile.TemporaryDirectory(prefix='qraft-eos-render-') as scratch:
        rendered = materialize_effective_fdf(template, Path(scratch), scalar_updates=scalars or {}, block_updates=blocks or {}, primary_destination='input.fdf')
        original_closure = resolve_scientific_input_closure(template)
        for item in original_closure.entries:
            if item.source.suffix.lower() in {'.psml', '.psf', '.vps'}:
                _immutable_copy(item.source, Path(scratch) / item.destination)
        closure = resolve_scientific_input_closure(rendered.root_fdf)
        for item in closure.entries:
            _immutable_copy(item.source, destination / item.destination)
        return destination / 'input.fdf'


class EosProtocol:
    """Reference P=0 evidence followed by independent fixed-fractional points.

    Native geometry authority remains PROVISIONAL. The reference is not an
    S-03 qualification: V-4 is not evaluated by this EOS protocol.
    """
    def run(self, reference_fdf, *, policy, runs_root=Path('.qraft-eos'), **execution_options):
        reference_fdf, root = Path(reference_fdf).resolve(), Path(runs_root).resolve()
        view = resolve_effective_fdf(reference_fdf)
        _nonmagnetic(view)
        if policy['relaxation_mode'] != 'fixed-fractional':
            raise ValueError('internal EOS requires a declared symmetry policy and provider')
        variable, pressure, stress = view.scalar('MD.VariableCell'), view.scalar('MD.TargetPressure'), view.scalar('MD.MaxStressTol')
        steps, kind = view.scalar('MD.Steps'), view.scalar('MD.TypeOfRun')
        if variable is None or not _fdf_logical(variable.value) or pressure is None or pressure.unit is None or pressure.unit.casefold() != 'gpa' or _float(pressure.value, 'MD.TargetPressure') != 0 or stress is None or stress.unit is None or stress.unit.casefold() != 'gpa' or _float(stress.value, 'MD.MaxStressTol') <= 0:
            raise ValueError('EOS reference requires explicit P=0 variable-cell relaxation and stress tolerance')
        if kind is None or kind.value.upper() not in {'CG', 'BROYDEN', 'FIRE'} or steps is None or int(steps.value) <= 0:
            raise ValueError('EOS reference requires an explicit relaxation run')
        force = view.scalar('MD.MaxForceTol')
        mesh_sizes = view.scalar('Mesh.Sizes')
        mesh_block = view.block('Mesh.Sizes')
        if force is None or force.unit is None or (mesh_sizes is None and mesh_block is None):
            raise ValueError('EOS reference requires explicit MD.MaxForceTol and Mesh.Sizes')
        force_tolerance = _float(force.value, 'MD.MaxForceTol') * _unit_factor(force.unit, force=True)
        if mesh_block is not None:
            mesh_text = ' '.join(mesh_block.body_lines)
        else:
            mesh_text = mesh_sizes.value.strip()
            if not (mesh_text.startswith('[') and mesh_text.endswith(']')):
                raise ValueError('Mesh.Sizes requires a bracketed list or block')
            mesh_text = mesh_text[1:-1]
        declared_mesh = [int(v) for v in mesh_text.split()]
        if force_tolerance <= 0 or len(declared_mesh) != 3 or min(declared_mesh) <= 0:
            raise ValueError('invalid reference force tolerance or Mesh.Sizes')
        kgrid = view.block('kgrid.MonkhorstPack')
        if kgrid is None or view.scalar('kgrid.Cutoff') is not None:
            raise ValueError('KGRID_NOT_FIXED')
        grid = [[float(v) for v in row.split()] for row in kgrid.body_lines if row.strip()]
        identity = build_scientific_identity(reference_fdf)
        _immutable_json(root / 'lock.json', {'policy': policy, 'reference_scientific_identity': identity.to_dict()})
        execution, _ = resolve_execution_spec(**execution_options)
        reference_root = root / 'reference'
        fdf = _source(reference_fdf, reference_root / 'source/reference')
        label = system_label(fdf)
        output = [{'name': 'struct-out', 'path': label + '.STRUCT_OUT', 'artifact_type': 'siesta.struct-out', 'media_type': 'text/plain', 'required': True}]
        runtime = _runtime(reference_root, [('reference', fdf, output)], execution)
        attempt = runtime.attempts.get('reference')
        if attempt is None or attempt.result.technical_validation.status != 'PASS':
            return {'status': 'FAILED', 'scientific_decision': 'NOT_EVALUATED'}
        attempt_root = reference_root / 'runtime/work/reference' / attempt.attempt_id
        stdout = attempt_root / attempt.stdout
        text = stdout.read_text(encoding='utf-8', errors='replace')
        if 'outcoor: Relaxed' not in text or 'error' in final_energy(text, policy['energy_quantity']):
            return {'status': 'FAILED', 'scientific_decision': 'NOT_EVALUATED'}
        meshes = _meshes(text)
        run = parse_run(text)
        assessment = evaluate_relaxation(run, {'variable_cell': True, 'max_force_tol_eV_A': force_tolerance,
            'has_constraints': view.block('Geometry.Constraints') is not None})
        if assessment['status'] != 'ACCEPTED':
            return assessment
        if not run['forces'] or run['mesh_cutoff_Ry'] is None:
            return {'status': 'FAILED', 'scientific_decision': 'NOT_EVALUATED'}
        maximum = run['forces'][-1]['max_constrained'] if view.block('Geometry.Constraints') is not None else run['forces'][-1]['max']
        if maximum is None or maximum > force_tolerance:
            return {'status': 'FAILED', 'scientific_decision': 'NOT_EVALUATED'}
        if not meshes:
            raise ValueError('EOS reference lacks observed InitMesh evidence')
        if any(m != declared_mesh for m in meshes):
            return {'status': 'REJECTED', 'reasons': ['MESH_INCONSISTENT']}
        mesh = meshes[-1]
        geometry = parse_struct_out(attempt_root / (label + '.STRUCT_OUT'))
        initial = geometry_from_fdf(reference_fdf)
        if [(a['index'], a['species_index']) for a in geometry['atoms']] != [(a['index'], a['species_index']) for a in initial['atoms']]:
            raise ValueError('ATOM_MAP_MISMATCH')
        initial_envelope = geometry_envelope(artifact_id='initial-geometry', geometry=initial, provenance={'source_fdf_sha256': view.closure_sha256})
        _immutable_json(root / 'initial-geometry.json', initial_envelope)
        envelope = geometry_envelope(artifact_id='eos-reference', geometry=geometry,
            provenance={'source_fdf_sha256': view.closure_sha256, 'input_geometry_sha256': initial_envelope['content_sha256'],
                        'struct_out_sha256': _hash(attempt_root / (label + '.STRUCT_OUT'))})
        _immutable_json(root / 'reference-geometry.json', envelope)
        _immutable_json(root / 'reference-evidence.json', {'geometry_sha256': _hash(root / 'reference-geometry.json'),
            'stdout_sha256': _hash(stdout), 'attempt_manifest_sha256': _hash(attempt_root / 'attempt.json'),
            'scientific_identity': identity.to_dict(), 'mesh': mesh})
        points_root = root / 'points'
        sources = []
        for index, factor in enumerate(policy['volume_factors']):
            node = f'volume-{index:03d}'
            canonical = {'cell': geometry['cell'], 'atoms': [{**atom, 'cart': atom['coordinates']} for atom in geometry['atoms']]}
            scaled = deform(canonical, factor)
            candidate = {'cell': scaled['cell'], 'atoms': [{**atom, 'coordinates': atom['cart']} for atom in scaled['atoms']]}
            updates = geometry_updates(candidate)
            scalars = {**updates['scalars'], 'MD.VariableCell': ('F', None), 'MD.TypeOfRun': ('CG', None),
                       'MD.Steps': (0, None), 'MD.NumCGSteps': (0, None)}
            blocks = dict(updates['blocks'])
            if mesh_block is None:
                scalars['Mesh.Sizes'] = ('['+' '.join(map(str, mesh))+']', None)
            else:
                blocks['Mesh.Sizes'] = ' '.join(map(str, mesh))
            fdf = _source(reference_fdf, points_root / 'source' / node, scalars=scalars, blocks=blocks)
            sources.append((node, fdf, []))
        runtime = _runtime(points_root, sources, execution)
        points = []
        for index, (node, fdf, _) in enumerate(sources):
            attempt = runtime.attempts.get(node)
            if attempt is None or attempt.result.technical_validation.status != 'PASS':
                return {'status': 'FAILED', 'scientific_decision': 'NOT_EVALUATED'}
            path = points_root / 'runtime/work' / node / attempt.attempt_id / attempt.stdout
            text = path.read_text(encoding='utf-8', errors='replace')
            energy = final_energy(text, policy['energy_quantity'])
            if 'error' in energy:
                return {'status': 'REJECTED', 'reasons': [energy['error']]}
            observed = _meshes(text)
            if not observed:
                raise ValueError('EOS point lacks observed InitMesh evidence')
            if any(m != mesh for m in observed):
                return {'status': 'REJECTED', 'reasons': ['MESH_INCONSISTENT']}
            points.append({'volume_factor': policy['volume_factors'][index], 'volume_A3': volume(geometry['cell'])*policy['volume_factors'][index],
                'energy_eV': energy['value'], 'mesh': observed[-1], 'kgrid': {'kind': 'MonkhorstPack', 'block': grid},
                'relaxation_mode': policy['relaxation_mode'], 'stdout_sha256': _hash(path)})
        table = {'quantity': policy['energy_quantity'], 'n_atoms': len(geometry['atoms']), 'points': points}
        result = {**evaluate(table, policy), **table, 'policy_id': policy['policy_id'], 'authority': 'PROVISIONAL'}
        _immutable_json(root / 'result.json', result)
        return result
