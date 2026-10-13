"""Fine electronic analysis delegated to the native post-SCF runtime."""
import hashlib
import json
from pathlib import Path
import tempfile

from ..contracts import CapabilityRegistry
from ..core import ScientificIdentity
from ..engines.siesta.electronic_analysis import POLICY, BOHR_ANG, band_gap, directional_mass, parse_bands, band_run_check
from ..engines.siesta.effective_fdf import materialize_effective_fdf
from ..engines.siesta.electronic_properties import PROPERTY_CAPABILITIES
from ..engines.siesta.input_closure import resolve_scientific_input_closure
from ..execution.capability_plugins import register_siesta_electronic_properties
from ..execution.capability_runtime import CompiledWorkflowRuntime
from ..execution.runtime_composition import compose_runtime
from ..workflows import WorkflowCompiler
from .single_fdf import build_scientific_identity, resolve_execution_spec
from .electronic_properties import ElectronicStateSource, _immutable_copy, _immutable_json


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _reciprocal_rows(source):
    from math import pi
    from ..engines.siesta.relaxation import geometry_from_fdf
    from ..engines.siesta.eos import _solve
    cell = geometry_from_fdf(source.final_fdf)['cell']
    # cell @ reciprocal.T = 2*pi I; both lattices use row vectors.
    return [_solve(cell, [2*pi if i == j else 0 for j in range(3)]) for i in range(3)]


def _path_sample_coordinates(rows):
    if len(rows) < 2 or rows[0][0] != 1:
        raise ValueError('An explicit BandLines path is required before masses')
    coordinates = [list(rows[0][1:4])]
    for previous, current in zip(rows, rows[1:]):
        count = current[0]
        if type(count) is not int or count < 1:
            raise ValueError('Invalid BandLines sample count')
        coordinates.extend([[a+(b-a)*j/count for a, b in zip(previous[1:4], current[1:4])]
                            for j in range(1, count+1)])
    return coordinates


class ElectronicAnalysisProtocol:
    """No scheduler or recovery state: each branch is a canonical native task.

    Directions, centers, spacing and occupation are explicit operator input;
    no silicon-specific assumptions or Fermi-derived occupations are used.
    """
    def run_sample(self, source: ElectronicStateSource, *, block_name, rows, n_occupied,
                   runs_root, profile=None, wfs_for_bands=False):
        source = source.verify()
        if block_name not in ('BandLines', 'BandPoints'):
            raise ValueError('Choose an explicit native band sample')
        root = Path(runs_root).resolve()
        branch = root / 'source/bands'
        request = dict(block_name=block_name, rows=rows, n_occupied=n_occupied, wfs_for_bands=wfs_for_bands)
        _immutable_json(root / 'lock.json', {'parent': source.provenance(), 'request': request, 'policy_id': 'qraft.electronic.policy@1', 'policy': POLICY})
        with tempfile.TemporaryDirectory(prefix='qraft-bands-render-') as temporary:
            rendered = materialize_effective_fdf(source.final_fdf, Path(temporary), primary_destination='input.fdf',
                scalar_updates={'DM.UseSaveDM': ('T', None), 'BandLinesScale': ('ReciprocalLatticeVectors', None),
                                'WFS.Write.For.Bands': ('T' if wfs_for_bands else 'F', None)},
                block_updates={block_name: '\n'.join(' '.join(str(v) for v in row) for row in rows)})
            for path in Path(temporary).rglob('*'):
                if path.is_file():
                    _immutable_copy(path, branch / path.relative_to(temporary))
        for pseudo in source.pseudopotentials.values():
            _immutable_copy(pseudo, branch / pseudo.name)
        _immutable_copy(source.density_matrix, branch / source.density_matrix.name)
        _immutable_copy(source.state_path, branch / 'electronic-state.json')
        fdf = branch / 'input.fdf'
        closure = resolve_scientific_input_closure(fdf)
        inputs = [{'name': e.name, 'source': 'bands/'+e.destination, 'destination': e.destination,
                   'media_type': e.media_type, 'sha256': _hash(e.source)} for e in closure.entries]
        inputs.append({'name': 'parent-dm', 'source': 'bands/'+source.density_matrix.name,
                       'destination': source.density_matrix.name, 'media_type': 'application/octet-stream', 'sha256': source.density_matrix_sha256})
        outputs = [{'name': 'bands', 'path': source.label+'.bands', 'artifact_type': 'qraft.bands.raw', 'media_type': 'text/plain', 'required': True}]
        if wfs_for_bands:
            outputs.append({'name': 'wavefunctions', 'path': source.label+'.bands.WFSX', 'artifact_type': 'siesta.wfsx', 'media_type': 'application/octet-stream', 'required': True})
        workflow = root / 'source/workflow.json'
        _immutable_json(workflow, {'schema_version': '1.0', 'workflow_id': 'electronic-sample', 'project_id': 'electronic-sample',
            'tasks': [{'task_id': 'bands', 'kind': 'calculation', 'capability': PROPERTY_CAPABILITIES['bands'], 'inputs': inputs,
                       'outputs': outputs, 'resources': {}, 'settings': {'primary_input': 'fdf'}}]})
        compilation = WorkflowCompiler().compile(workflow)
        if not compilation.valid or compilation.compiled is None:
            raise ValueError('Electronic sample compilation failed: '+str(compilation.findings))
        identity = build_scientific_identity(fdf)
        identity = ScientificIdentity(engine=identity.engine, effective_fdf_sha256=identity.effective_fdf_sha256,
            geometry_sha256=identity.geometry_sha256, species_mapping_sha256=identity.species_mapping_sha256,
            pseudopotentials=identity.pseudopotentials, included_scientific_files=identity.included_scientific_files,
            components={**identity.components, 'm7.parent_electronic_state': source.identity_component(), 'm7.sample': _digest(request)})
        execution, _ = resolve_execution_spec(profile=profile)
        registry = CapabilityRegistry(); register_siesta_electronic_properties(registry); registry.freeze()
        composition = compose_runtime(execution, max_parallel_steps=1, placement_probe_root=root)
        runtime = CompiledWorkflowRuntime(workflow=compilation.compiled, registry=registry, root=root / 'runtime',
            source_root=root / 'source', scientific_identities={'bands': identity}, execution_specs=execution,
            launcher=composition.launcher, allocation=composition.allocation).run()
        attempt = runtime.attempts.get('bands')
        if attempt is None or attempt.result.technical_validation.status != 'PASS':
            return {'status': 'NOT_EVALUATED', 'runtime_status': runtime.status}
        attempt_root = root / 'runtime/work/bands' / attempt.attempt_id
        raw, stdout = attempt_root / (source.label+'.bands'), attempt_root / attempt.stdout
        check = band_run_check(stdout.read_text(encoding='utf-8', errors='replace'), raw.is_file())
        if check['status'] != 'PASS':
            return check
        bands = parse_bands(raw.read_text(encoding='utf-8'))
        result = {'gap': band_gap(bands, n_occupied), 'policy_id': 'qraft.electronic.policy@1',
                  'parent_electronic_state': source.provenance(), 'sample': request,
                  'bands_sha256': _hash(raw), 'stdout_sha256': _hash(stdout)}
        _immutable_json(root / 'result.json', result)
        return {'result': result, 'bands': bands, 'attempt_root': attempt_root}

    def run_masses(self, source, *, path_rows, longitudinal, transverse_directions, band, carrier, n_occupied, spin=0,
                   step_invA, points_per_side,
                   runs_root, profile=None):
        from math import sqrt, isfinite
        from ..engines.siesta.eos import _solve
        source = source.verify()
        if carrier not in ('electron', 'hole') or type(band) is not int or band < 1 or type(spin) is not int or spin < 0:
            raise ValueError('Explicit valid mass band, carrier and spin required')
        reciprocal_rows_invA = _reciprocal_rows(source)
        # Cartesian reciprocal vectors are rows; solve K = fractional @ B.
        def fractional(cart):
            return _solve([[reciprocal_rows_invA[r][c] for r in range(3)] for c in range(3)], cart)
        if type(points_per_side) is not int or points_per_side < 3 or not isfinite(step_invA) or step_invA <= 0:
            raise ValueError('Explicit positive mass-line spacing/count required')
        def rows(center, direction):
            norm = sqrt(sum(d*d for d in direction))
            if norm == 0:
                raise ValueError('Mass direction must be nonzero')
            unit = [d/norm for d in direction]
            return [fractional([c+i*step_invA*d for c, d in zip(center, unit)]) for i in range(-points_per_side, points_per_side+1)], unit
        root = Path(runs_root)
        path = self.run_sample(source, block_name='BandLines', rows=path_rows, n_occupied=n_occupied,
                               runs_root=root / 'path', profile=profile)
        if 'bands' not in path:
            return path
        coordinates = _path_sample_coordinates(path_rows)
        if len(coordinates) != path['bands']['nk']:
            raise ValueError('BandLines sample does not match the declared path')
        energies = [e[spin][band-1] for e in path['bands']['E']]
        extremum = (min if carrier == 'electron' else max)(range(len(energies)), key=lambda i: energies[i])
        center_cartesian_invA = [sum(coordinates[extremum][i]*reciprocal_rows_invA[i][j] for i in range(3)) for j in range(3)]
        _immutable_json(root / 'path/extremum.json', {'k_index': extremum, 'center_cartesian_invA': center_cartesian_invA,
                        'path_result_sha256': _hash(root / 'path/result.json'), 'parent': source.provenance()})
        initial, unit = rows(center_cartesian_invA, longitudinal)
        first = self.run_sample(source, block_name='BandPoints', rows=initial, n_occupied=n_occupied,
                                runs_root=root / 'longitudinal', profile=profile)
        if 'bands' not in first:
            return first
        spec = {'from': 0, 'to': 2*points_per_side, 'band': band, 'carrier': carrier, 'spin': spin}
        mass = directional_mass(first['bands'], spec, POLICY)
        _immutable_json(root / 'longitudinal/mass.json', mass)
        if mass['status'] != 'ESTABLISHED':
            return {'longitudinal': mass, 'transverse': []}
        observed = [x/BOHR_ANG for x in first['bands']['k'][mass['extremum_k_index']]]
        fitted = [c+mass['extremum_offset_invA']*d for c, d in zip(observed, unit)]
        transverse = []
        for i, direction in enumerate(transverse_directions):
            sample_rows, _ = rows(fitted, direction)
            sample = self.run_sample(source, block_name='BandPoints', rows=sample_rows, n_occupied=n_occupied,
                runs_root=root / f'transverse-{i:03}', profile=profile)
            if 'bands' not in sample:
                transverse.append(sample)
                continue
            value = directional_mass(sample['bands'], spec, POLICY)
            _immutable_json(root / f'transverse-{i:03}/mass.json', value)
            transverse.append(value)
        result = {'longitudinal': mass, 'transverse': transverse, 'center_cartesian_invA': fitted,
                  'step_invA': step_invA, 'points_per_side': points_per_side, 'policy_id': 'qraft.electronic.policy@1'}
        _immutable_json(root / 'result.json', result)
        return result
