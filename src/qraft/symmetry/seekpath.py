"""Engine-neutral SeeK-path provider for QRAFT band-path proposals."""

from __future__ import annotations

from importlib import metadata
from typing import Any, Mapping

from ..band_paths import (
    BandPathRequest,
    BandPathSegment,
    CrystalStructure,
    InvalidProviderResult,
    ProviderExecutionError,
    ProviderPath,
    SymmetryAnalysis,
    SymmetryProviderUnavailable,
)


def _json_safe(value: Any) -> object:
    """Copy third-party values into deterministic built-in JSON data."""

    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class SeekPathProvider:
    """Use SeeK-path's original-cell APIs without exposing its objects."""

    provider_name = "seekpath"

    def __init__(self) -> None:
        try:
            import seekpath  # type: ignore[import-not-found]
            import spglib  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise SymmetryProviderUnavailable(
                "SeeK-path/spglib is unavailable; install qraft[symmetry] for suggest or automatic paths"
            ) from exc
        self._seekpath = seekpath
        self._spglib = spglib

    @property
    def provider_version(self) -> str:
        return str(getattr(self._seekpath, "__version__", None) or metadata.version("seekpath"))

    @property
    def spglib_version(self) -> str | None:
        return str(getattr(self._spglib, "__version__", None) or metadata.version("spglib"))

    @staticmethod
    def _structure(value: CrystalStructure) -> tuple[list[list[float]], list[list[float]], list[int]]:
        return ([list(row) for row in value.cell], [list(row) for row in value.fractional_positions], list(value.atomic_numbers))

    def generate(self, structure: CrystalStructure, request: BandPathRequest) -> ProviderPath:
        resolved_time_reversal = request.resolved_time_reversal
        if resolved_time_reversal is None:
            raise ProviderExecutionError("TIME_REVERSAL_UNRESOLVED")
        kwargs: dict[str, object] = {
            "with_time_reversal": resolved_time_reversal,
            "recipe": request.convention,
            "symprec": request.symprec,
        }
        if request.angle_tolerance is not None:
            kwargs["angle_tolerance"] = request.angle_tolerance
        native_structure = self._structure(structure)
        try:
            # These APIs retain the M6 input-cell reciprocal basis.  They do
            # not substitute a primitive or standardized electronic system.
            path = self._seekpath.get_path_orig_cell(native_structure, **kwargs)
            explicit = self._seekpath.get_explicit_k_path_orig_cell(
                native_structure, reference_distance=request.reference_distance, **kwargs
            )
        except Exception as exc:
            raise ProviderExecutionError(f"SeeK-path symmetry detection failed: {exc}") from exc
        try:
            points = explicit["explicit_kpoints_rel"]
            labels = explicit["explicit_kpoints_labels"]
            ranges = tuple((int(start), int(stop)) for start, stop in explicit["explicit_segments"])
            if len(points) != len(labels):
                raise ValueError("explicit k-point coordinates and labels have different lengths")
            segments: list[BandPathSegment] = []
            for start, stop in ranges:
                if start < 0 or stop <= start or stop > len(points):
                    raise ValueError("explicit segment is not a valid [start, stop) interval")
                end = stop - 1
                segments.append(BandPathSegment(
                    str(labels[start]), tuple(points[start]), str(labels[end]), tuple(points[end]), stop - start,
                ))
            if any(segment.start_label == "None" or segment.end_label == "None" for segment in segments):
                raise ValueError("explicit high-symmetry segment endpoint is unlabeled")
            analysis = SymmetryAnalysis(
                spacegroup_number=int(path["spacegroup_number"]),
                international_symbol=str(path["spacegroup_international"]),
                bravais_lattice=str(path["bravais_lattice"]),
                is_supercell=bool(path["is_supercell"]),
                primitive_mapping={"input_cell_preserved": True},
                transformation_required=False,
                point_coords=_json_safe(path["point_coords"]),  # type: ignore[arg-type]
                path=tuple(tuple(item) for item in path["path"]),
                explicit_segments=ranges,
                augmented_path=bool(path["augmented_path"]),
                has_inversion_symmetry=bool(path["has_inversion_symmetry"]),
            )
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise InvalidProviderResult(f"SeeK-path returned an invalid original-cell path: {exc}") from exc
        return ProviderPath(analysis, tuple(segments))
