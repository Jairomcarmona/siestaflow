"""Fine electronic analysis delegated to the native post-SCF runtime."""
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import re

from ..contracts import CapabilityRegistry
from ..core import ScientificIdentity
from ..engines.siesta.electronic_analysis import POLICY, BOHR_ANG, band_gap, directional_mass, parse_bands, band_run_check, parse_eigfat, fat_partition, fat_groups
from ..engines.siesta.effective_fdf import materialize_effective_fdf
from ..engines.siesta.electronic_properties import PROPERTY_CAPABILITIES
from ..engines.siesta.input_closure import resolve_scientific_input_closure
from ..execution.capability_plugins import register_siesta_electronic_properties
from ..execution.capability_runtime import CompiledWorkflowRuntime
from ..execution.runtime_composition import compose_runtime
from ..workflows import WorkflowCompiler
from .single_fdf import build_scientific_identity, resolve_execution_spec
from .electronic_properties import ElectronicStateSource, _immutable_copy, _immutable_json
from ._worker_environment import _WorkerEnvironment
from .provisional_scf import ProvisionalScfSource


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
    def __init__(self, *, worker_lock_path):
        self._worker_environment = _WorkerEnvironment.load(worker_lock_path)

    def run_sample(self, source: ElectronicStateSource, *, block_name, rows, n_occupied,
                   runs_root, profile=None, wfs_for_bands=False):
        if type(source) is not ElectronicStateSource:
            raise TypeError('The integration protocol requires an immutable M6 electronic state')
        return self._run_sample(source, block_name=block_name, rows=rows, n_occupied=n_occupied,
            runs_root=runs_root, profile=profile, wfs_for_bands=wfs_for_bands)

    def _run_sample(self, source, *, block_name, rows, n_occupied, runs_root, profile=None, wfs_for_bands=False):
        source = source.verify()
        self._worker_environment.verify()
        if block_name not in ('BandLines', 'BandPoints'):
            raise ValueError('Choose an explicit native band sample')
        root = Path(runs_root).resolve()
        branch = root / 'source/bands'
        request = dict(block_name=block_name, rows=rows, n_occupied=n_occupied, wfs_for_bands=wfs_for_bands)
        _immutable_copy(self._worker_environment.lock_path, root / 'worker-environment.json')
        _immutable_json(root / 'lock.json', {'parent': source.provenance(), 'request': request, 'policy_id': 'qraft.electronic.policy@1', 'policy': POLICY, 'worker_environment_sha256': self._worker_environment.sha256})
        with tempfile.TemporaryDirectory(prefix='qraft-bands-render-') as temporary:
            rendered = materialize_effective_fdf(source.final_fdf, Path(temporary), primary_destination='input.fdf',
                scalar_updates={'DM.UseSaveDM': ('T', None), 'BandLinesScale': ('ReciprocalLatticeVectors', None),
                                'WFS.Write.For.Bands': ('T' if wfs_for_bands else 'F', None),
                                **({'SaveHS': ('T', None)} if wfs_for_bands else {})},
                block_updates={block_name: '\n'.join(' '.join(str(v) for v in row) for row in rows)})
            for path in Path(temporary).rglob('*'):
                if path.is_file():
                    _immutable_copy(path, branch / path.relative_to(temporary))
        for pseudo in source.pseudopotentials.values():
            _immutable_copy(pseudo, branch / pseudo.name)
        _immutable_copy(source.density_matrix, branch / source.density_matrix.name)
        provisional = isinstance(source, ProvisionalScfSource)
        if provisional:
            _immutable_json(branch / 'provisional-scf.json', source.provenance())
        else:
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
            outputs.append({'name': 'overlap', 'path': source.label+'.HSX', 'artifact_type': 'siesta.hsx', 'media_type': 'application/octet-stream', 'required': True})
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
            components={**identity.components, ('qraft.provisional_scf' if provisional else 'm7.parent_electronic_state'): source.identity_component(), 'm7.sample': _digest(request)})
        execution, _ = resolve_execution_spec(profile=profile)
        if execution.executable != self._worker_environment.siesta.path:
            raise ValueError('Execution executable differs from worker lock')
        registry = CapabilityRegistry(); register_siesta_electronic_properties(registry); registry.freeze()
        composition = compose_runtime(execution, max_parallel_steps=1, placement_probe_root=root)
        runtime = CompiledWorkflowRuntime(workflow=compilation.compiled, registry=registry, root=root / 'runtime',
            source_root=root / 'source', scientific_identities={'bands': identity}, execution_specs=execution,
            launcher=self._worker_environment.launcher(composition.launcher), allocation=composition.allocation).run()
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
                  ('parent_scf' if provisional else 'parent_electronic_state'): source.provenance(), 'sample': request,
                  'bands_sha256': _hash(raw), 'stdout_sha256': _hash(stdout)}
        result['worker_environment_sha256'] = self._worker_environment.sha256
        if wfs_for_bands:
            result['fat_input_sha256'] = {source.label+suffix: _hash(attempt_root / (source.label+suffix))
                                          for suffix in ('.bands.WFSX', '.HSX')}
        if provisional:
            result['authority'] = 'NUMERICAL_CANDIDATE'
            result['origin'] = 'PROVISIONAL_DIRECT_SCF'
        _immutable_json(root / 'result.json', result)
        return {'result': result, 'bands': bands, 'attempt_root': attempt_root}

    def run_fat(self, sample, *, mpr, projections, min_band, max_band, runs_root):
        if 'parent_scf' in sample['result'] or 'parent_electronic_state' not in sample['result']:
            raise TypeError('The integration protocol requires an immutable M6 electronic state')
        return self._run_fat(sample,mpr=mpr,projections=projections,min_band=min_band,max_band=max_band,runs_root=runs_root)

    def _run_fat(self, sample, *, mpr, projections, min_band, max_band, runs_root):
        """Project the exact sampled wavefunctions with the locked utility.

        A dedicated directory preserves the immutable canonical SIESTA attempt.
        Version provenance for fat is its pinned distribution/build, not a
        nonexistent independent --version interface.
        """
        self._worker_environment.verify()
        if sample['result']['worker_environment_sha256'] != self._worker_environment.sha256:
            raise ValueError('Sample worker lock differs')
        if type(min_band) is not int or type(max_band) is not int or not 1 <= min_band <= max_band <= sample['bands']['nbands']:
            raise ValueError('Explicit valid fat band range required')
        names = tuple(projections)
        if not names or len(set(names)) != len(names) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', n) for n in names):
            raise ValueError('Explicit safe projection names required')
        description = Path(mpr).read_bytes()
        label = description.decode('utf-8').splitlines()[0].strip()
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', label):
            raise ValueError('Unsafe fat SystemLabel')
        attempt = Path(sample['attempt_root'])
        bands_path = attempt / (label+'.bands')
        if _hash(bands_path) != sample['result']['bands_sha256']:
            raise ValueError('Sample bands changed')
        bands = parse_bands(bands_path.read_text(encoding='utf-8'))
        if max_band > bands['nbands']:
            raise ValueError('Fat range exceeds verified bands')
        root = Path(runs_root).resolve()
        root.mkdir(parents=True, exist_ok=False)
        hashes = {}
        for suffix in ('.bands', '.bands.WFSX', '.HSX'):
            path = attempt / (label+suffix)
            if not path.is_file():
                raise ValueError('Required fat input missing: '+path.name)
            expected = sample['result']['bands_sha256'] if suffix=='.bands' else sample['result']['fat_input_sha256'].get(path.name)
            if _hash(path) != expected:
                raise ValueError('Sample fat input changed: '+path.name)
            _immutable_copy(path, root / path.name)
            hashes[path.name] = _hash(path)
        (root / 'projection.mpr').write_bytes(description)
        hashes['projection.mpr'] = _hash(root / 'projection.mpr')
        _immutable_copy(self._worker_environment.lock_path, root / 'worker-environment.json')
        command = [self._worker_environment.fat.path, '-b', str(min_band), '-B', str(max_band), 'projection']
        self._worker_environment.verify()
        with (root / 'stdout.txt').open('xb') as out, (root / 'stderr.txt').open('xb') as err:
            process = subprocess.run(command, cwd=root, stdout=out, stderr=err, check=False)
        if process.returncode != 0:
            raise ValueError('fat execution failed')
        sets = {name: parse_eigfat((root / ('projection.'+name+'.EIGFAT')).read_text(encoding='utf-8')) for name in names}
        partition = fat_partition(bands, sets, POLICY)
        parent_key = 'parent_scf' if 'parent_scf' in sample['result'] else 'parent_electronic_state'
        result = dict(partition=partition, groups=fat_groups(bands, sets, POLICY) if partition['status']=='PASS' else [],
                      input_sha256=hashes, output_sha256={p.name: _hash(p) for p in root.glob('*.EIGFAT')},
                      stdout_sha256=_hash(root / 'stdout.txt'), stderr_sha256=_hash(root / 'stderr.txt'),
                      worker_environment_sha256=self._worker_environment.sha256, command=command)
        result[parent_key] = sample['result'][parent_key]
        result['policy_id'] = 'qraft.electronic.policy@1'
        if parent_key == 'parent_scf':
            result['authority'] = 'NUMERICAL_CANDIDATE'
            result['origin'] = 'PROVISIONAL_DIRECT_SCF'
        _immutable_json(root / 'result.json', result)
        return result

    def run_masses(self, source, *, path_rows, longitudinal, transverse_directions, band, carrier, n_occupied, spin=0,
                   step_invA, points_per_side,
                   runs_root, profile=None):
        if type(source) is not ElectronicStateSource:
            raise TypeError('The integration protocol requires an immutable M6 electronic state')
        return self._run_masses(source, path_rows=path_rows, longitudinal=longitudinal,
            transverse_directions=transverse_directions, band=band, carrier=carrier, n_occupied=n_occupied,
            spin=spin, step_invA=step_invA, points_per_side=points_per_side, runs_root=runs_root, profile=profile)

    def _run_masses(self, source, *, path_rows, longitudinal, transverse_directions, band, carrier, n_occupied, spin=0,
                   step_invA, points_per_side, runs_root, profile=None):
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
        mass = self._mass_result(source, mass)
        _immutable_json(root / 'longitudinal/mass.json', mass)
        if mass.get('numerical_status', mass['status']) != 'ESTABLISHED':
            result = {'longitudinal': mass, 'transverse': [], 'policy_id': 'qraft.electronic.policy@1',
                      'worker_environment_sha256': self._worker_environment.sha256,
                      ('parent_scf' if isinstance(source, ProvisionalScfSource) else 'parent_electronic_state'): source.provenance()}
            if isinstance(source, ProvisionalScfSource):
                result['authority'] = 'NUMERICAL_CANDIDATE'
                result['origin'] = 'PROVISIONAL_DIRECT_SCF'
            _immutable_json(root / 'result.json', result)
            return result
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
            value = self._mass_result(source, value)
            _immutable_json(root / f'transverse-{i:03}/mass.json', value)
            transverse.append(value)
        result = {'longitudinal': mass, 'transverse': transverse, 'center_cartesian_invA': fitted,
                  'step_invA': step_invA, 'points_per_side': points_per_side, 'policy_id': 'qraft.electronic.policy@1'}
        result['parent_scf' if isinstance(source, ProvisionalScfSource) else 'parent_electronic_state'] = source.provenance()
        result['worker_environment_sha256'] = self._worker_environment.sha256
        if isinstance(source, ProvisionalScfSource):
            result['authority'] = 'NUMERICAL_CANDIDATE'
            result['origin'] = 'PROVISIONAL_DIRECT_SCF'
        _immutable_json(root / 'result.json', result)
        return result

    @staticmethod
    def _mass_result(source, value):
        if isinstance(source, ProvisionalScfSource):
            value = {**value, 'authority':'NUMERICAL_CANDIDATE', 'origin':'PROVISIONAL_DIRECT_SCF'}
            if value['status']=='ESTABLISHED':
                value = {**value, 'status':'NUMERICAL_CANDIDATE', 'numerical_status':'ESTABLISHED'}
        return value


class _ProvisionalElectronicAnalysisProtocol(ElectronicAnalysisProtocol):
    """Private qualification route; unavailable from the integration API."""
    def run_sample(self, source, **options):
        if type(source) is not ProvisionalScfSource:
            raise TypeError('Qualification requires an explicit provisional SCF source')
        return self._run_sample(source, **options)

    def run_masses(self, source, **options):
        if type(source) is not ProvisionalScfSource:
            raise TypeError('Qualification requires an explicit provisional SCF source')
        return self._run_masses(source, **options)

    def run_fat(self,sample,**options):
        if 'parent_scf' not in sample['result'] or 'parent_electronic_state' in sample['result']:
            raise TypeError('Qualification requires an explicit provisional SCF sample')
        return self._run_fat(sample,**options)
