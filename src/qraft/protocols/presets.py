"""Single-calculation preset protocols over the canonical runtime.

Execution, ownership and reuse remain in execute_fdf_plan. Postprocessors read
the validated attempt; they never launch SIESTA or edit a settled attempt.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..engines.siesta.effective_fdf import resolve_effective_fdf
from ..engines.siesta.ground_state import system_label
from ..engines.siesta.relaxation import geometry_from_fdf, _float, _unit_factor
from ..engines.siesta.relaxation import parse_struct_out, _fdf_logical
from ..engines.siesta.variable_cell import assess_variable_cell
from ..engines.siesta.presets import parse_run, evaluate_molecule, image_interaction
from ..engines.siesta.molecular_vibrations import parse_fc, evaluate_vibrations
from .single_fdf import execute_fdf_plan, build_scientific_identity, _canonical_sha


def _attempt_directory(result, runs_root):
    plan = result['plan']
    key = _canonical_sha({'scientific': plan['scientific_identity']['fingerprint'],
                          'execution': plan['execution_spec']['fingerprint']})[:16]
    attempt = result['attempt']
    return Path(runs_root).resolve() / 'runtime' / key / 'work' / attempt['node_id'] / attempt['attempt_id']


def _run(fdf, *, runs_root, **execution):
    result = execute_fdf_plan(fdf, runs_root=runs_root, **execution)
    directory = _attempt_directory(result, runs_root)
    stdout = directory / result['attempt']['stdout']
    # Bound to the exact stdout returned by canonical execution/reuse.
    data = stdout.read_bytes()
    run = parse_run(data.decode('utf-8', errors='replace'))
    return result, directory, run, hashlib.sha256(data).hexdigest()


class MoleculeProtocol:
    def run(self, fdf: Path, *, intent, radii=None, runs_root=Path('.qraft-molecule'), **execution):
        effective = resolve_effective_fdf(fdf)
        charge = effective.scalar('NetCharge')
        if charge is None or _float(charge.value, 'NetCharge') != intent['net_charge']:
            raise ValueError('molecule intent requires matching explicit NetCharge')
        kgrid = effective.block('kgrid.MonkhorstPack')
        if kgrid is not None:
            rows = [[float(v) for v in row.split()] for row in kgrid.body_lines if row.strip()]
            if rows != [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]:
                raise ValueError('KGRID_NOT_GAMMA')
        if effective.scalar('Slab.DipoleCorrection') is not None:
            raise ValueError('S-01 does not enable slab dipole correction')
        preview = {'status': 'NOT_CHECKED'}
        if radii is not None:
            geometry = geometry_from_fdf(fdf)
            labels = {}
            for row in effective.block('ChemicalSpeciesLabel').body_lines:
                fields = row.split()
                if fields:
                    labels[int(fields[0])] = fields[2]
            preview = image_interaction({'cell': geometry['cell'], 'atoms': [
                {'species': labels[a['species_index']], 'cart': a['coordinates']} for a in geometry['atoms']]}, radii)
        result, directory, run, digest = _run(fdf, runs_root=runs_root, **execution)
        if result['attempt']['result']['technical_validation']['status'] != 'PASS':
            return {'execution': result, 'scientific_decision': 'NOT_EVALUATED',
                    'source_stdout_sha256': digest}
        if run['net_charge'] is None or run['net_charge'] != intent['net_charge']:
            raise ValueError('observed molecular charge disagrees with declared intent')
        return {'execution': result, 'assessment': evaluate_molecule(run, intent),
                'image_interaction': preview, 'source_stdout_sha256': digest,
                'protocol_id': 'qraft.preset.s-01@1'}


class MolecularVibrationProtocol:
    def run(self, fdf: Path, *, reference_fdf: Path, cart, masses, policy,
            runs_root=Path('.qraft-molecular-fc'), **execution):
        manifest = execution.get('pseudo_manifest')
        first = build_scientific_identity(reference_fdf, pseudo_manifest=manifest)
        second = build_scientific_identity(fdf, pseudo_manifest=manifest)
        if first.geometry_sha256 != second.geometry_sha256 or first.species_mapping_sha256 != second.species_mapping_sha256:
            raise ValueError('ATOM_MAP_MISMATCH')
        model = ('basis', 'xc', 'k_grid', 'mesh_cutoff', 'charge_spin', 'dft_u_projectors')
        if first.pseudopotentials != second.pseudopotentials or any(first.components[k] != second.components[k] for k in model):
            raise ValueError('GEOMETRY_NOT_RELAXED')
        effective = resolve_effective_fdf(fdf)
        kind = effective.scalar('MD.TypeOfRun')
        displacement = effective.scalar('FC.Displacement')
        low, high = effective.scalar('FC.First'), effective.scalar('FC.Last')
        if kind is None or kind.value.upper() != 'FC' or displacement is None or low is None or high is None:
            raise ValueError('molecular FC requires explicit FC settings')
        if _float(displacement.value, 'FC.Displacement') * _unit_factor(displacement.unit) != policy['fc_displacement_A']:
            raise ValueError('FC displacement disagrees with declared policy')
        if int(low.value) != 1 or int(high.value) != len(cart):
            raise ValueError('ATOM_MAP_MISMATCH')
        geometry = geometry_from_fdf(fdf)
        if [a['coordinates'] for a in geometry['atoms']] != cart or len(masses) != len(cart):
            raise ValueError('ATOM_MAP_MISMATCH')
        result, directory, run, digest = _run(fdf, runs_root=runs_root, **execution)
        if result['attempt']['result']['technical_validation']['status'] != 'PASS':
            return {'execution': result, 'scientific_decision': 'NOT_EVALUATED',
                    'source_stdout_sha256': digest}
        path = directory / (system_label(fdf) + '.FC')
        data = path.read_bytes()
        fc = parse_fc(data.decode('utf-8'))
        return {'execution': result, 'assessment': evaluate_vibrations(run, fc, cart, masses, policy),
                'source_stdout_sha256': digest, 'source_fc_sha256': hashlib.sha256(data).hexdigest(),
                'reference_fdf_sha256': first.effective_fdf_sha256,
                'protocol_id': 'qraft.preset.s-07@1', 'policy': policy}


class VariableCellProtocol:
    """One variable-cell relaxation and V-1…V-4, with native provisional scope."""
    def run(self, fdf: Path, *, runs_root=Path('.qraft-variable-cell'), **execution):
        effective = resolve_effective_fdf(fdf)
        variable, pressure, stress = (effective.scalar(n) for n in ('MD.VariableCell','MD.TargetPressure','MD.MaxStressTol'))
        force, steps, kind = (effective.scalar(n) for n in ('MD.MaxForceTol','MD.Steps','MD.TypeOfRun'))
        if variable is None or not _fdf_logical(variable.value) or pressure is None or pressure.unit is None or pressure.unit.lower()!='gpa' or _float(pressure.value,'pressure')!=0:
            raise ValueError('Variable-cell preset requires explicit P=0')
        if stress is None or stress.unit is None or stress.unit.lower()!='gpa' or _float(stress.value,'stress')<=0 or force is None or force.unit is None:
            raise ValueError('Explicit positive stress and force tolerances required')
        tolerance = _float(force.value,'force')*_unit_factor(force.unit,force=True)
        if tolerance<=0 or steps is None or int(steps.value)<=0 or kind is None or kind.value.upper() not in ('CG','BROYDEN','FIRE'):
            raise ValueError('Explicit relaxation settings required')
        block, scalar = effective.block('Mesh.Sizes'), effective.scalar('Mesh.Sizes')
        if block is not None:
            mesh_text=' '.join(block.body_lines)
        elif scalar is not None and scalar.value.startswith('[') and scalar.value.endswith(']'):
            mesh_text=scalar.value[1:-1]
        else:
            raise ValueError('Observed initial Mesh.Sizes must be fixed explicitly')
        mesh=[int(n) for n in mesh_text.split()]
        if len(mesh)!=3 or min(mesh)<=0:
            raise ValueError('Invalid Mesh.Sizes')
        # Provider availability is established before launching a real job.
        from ..engines.siesta.variable_cell import space_group
        initial=geometry_from_fdf(fdf); space_group(initial)
        result,directory,run,digest=_run(fdf,runs_root=runs_root,**execution)
        if result['attempt']['result']['technical_validation']['status']!='PASS':
            return {'execution':result,'scientific_decision':'NOT_EVALUATED','source_stdout_sha256':digest}
        if not run['meshes'] or run['mesh_cutoff_Ry'] is None:
            raise ValueError('Variable-cell run lacks mesh evidence')
        if any(observed!=mesh for observed in run['meshes']) and len(run['meshes'])==1:
            raise ValueError('Observed mesh disagrees with declared Mesh.Sizes')
        final_path=directory/(system_label(fdf)+'.STRUCT_OUT')
        final=parse_struct_out(final_path)
        assessment,symmetry=assess_variable_cell(run, {'variable_cell':True,'max_force_tol_eV_A':tolerance,
            'has_constraints':effective.block('Geometry.Constraints') is not None},initial,final)
        return dict(execution=result, assessment=assessment, symmetry=symmetry, geometry=final,
                    authority='PROVISIONAL', protocol_id='qraft.preset.s-03@1',
                    source_stdout_sha256=digest, source_struct_out_sha256=hashlib.sha256(final_path.read_bytes()).hexdigest())
