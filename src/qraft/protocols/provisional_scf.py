"""Explicit operator SCF input for pipeline qualification, independent of M6."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from ..engines.siesta.electronic_properties import validate_property_neutral_parent
from ..engines.siesta.ground_state import system_label
from ..engines.siesta.input_closure import resolve_scientific_input_closure, effective_species, resolve_pseudopotentials
from ..engines.siesta.effective_fdf import resolve_effective_fdf
from ..engines.siesta.eos import final_energy
from .single_fdf import build_scientific_identity, _canonical_sha


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class ProvisionalScfSource:
    final_fdf: Path
    density_matrix: Path
    stdout: Path
    pseudo_manifest: Path | None
    label: str
    final_fdf_sha256: str
    density_matrix_sha256: str
    stdout_sha256: str
    parent_scientific_identity_sha256: str
    closure_sha256: str
    pseudopotentials: Mapping[str, Path]
    pseudo_sha256: tuple[tuple[str, str], ...]

    def __post_init__(self):
        object.__setattr__(self, 'pseudopotentials', MappingProxyType(dict(self.pseudopotentials)))

    @classmethod
    def load(cls, *, final_fdf, density_matrix, stdout, pseudo_manifest=None):
        fdf, dm, out = (Path(p).resolve() for p in (final_fdf, density_matrix, stdout))
        validate_property_neutral_parent(fdf)
        observed = final_energy(out.read_text(encoding='utf-8', errors='replace'), 'free_energy')
        if 'error' in observed:
            raise ValueError(observed['error'])
        label = system_label(fdf)
        if dm.name != label+'.DM':
            raise ValueError('Provisional SCF density-matrix filename differs from SystemLabel')
        effective = resolve_effective_fdf(fdf)
        pseudos = resolve_pseudopotentials(effective.source_root, effective_species(effective), pseudo_manifest)
        identity = build_scientific_identity(fdf, pseudo_manifest=pseudo_manifest)
        closure = resolve_scientific_input_closure(fdf)
        return cls(fdf, dm, out, Path(pseudo_manifest).resolve() if pseudo_manifest else None,
                   label, _sha(fdf), _sha(dm), _sha(out), identity.fingerprint, effective.closure_sha256,
                   pseudos, tuple(sorted((name, _sha(path)) for name, path in pseudos.items())))

    def provenance(self):
        return dict(artifact_type='qraft.provisional-scf', authority='NUMERICAL_CANDIDATE',
                    origin='SCF directo provisional', final_fdf_sha256=self.final_fdf_sha256,
                    density_matrix_sha256=self.density_matrix_sha256, stdout_sha256=self.stdout_sha256,
                    scientific_identity_sha256=self.parent_scientific_identity_sha256,
                    closure_sha256=self.closure_sha256, pseudopotentials=dict(self.pseudo_sha256))

    def identity_component(self):
        return _canonical_sha(self.provenance())

    def verify(self):
        current = type(self).load(final_fdf=self.final_fdf, density_matrix=self.density_matrix,
                                  stdout=self.stdout, pseudo_manifest=self.pseudo_manifest)
        if current.provenance() != self.provenance() or current.pseudopotentials != self.pseudopotentials:
            raise ValueError('Provisional SCF evidence changed')
        return current
