"""Versioned identifiers and compatibility rules for public contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering


_CONTRACT_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$")


class ContractCompatibilityError(ValueError):
    """Raised when a producer cannot satisfy a required contract version."""


def require_namespaced_identifier(value: str, *, field: str = "identifier") -> str:
    normalized = str(value).strip()
    if not _CONTRACT_NAME.fullmatch(normalized):
        raise ValueError(
            f"{field} must be a lowercase namespaced identifier: {value!r}"
        )
    return normalized


@total_ordering
@dataclass(frozen=True)
class ContractVersion:
    """Major/minor wire-contract version.

    Patch releases belong to implementations, not to serialized contracts.
    Within one major version, a provider with a newer minor version may satisfy
    a consumer requiring an older minor version.
    """

    major: int
    minor: int

    def __post_init__(self) -> None:
        if self.major < 1 or self.minor < 0:
            raise ValueError("contract versions must be MAJOR>=1 and MINOR>=0")

    @classmethod
    def parse(cls, value: str | "ContractVersion") -> "ContractVersion":
        if isinstance(value, cls):
            return value
        match = re.fullmatch(r"([1-9][0-9]*)\.([0-9]+)", str(value).strip())
        if not match:
            raise ValueError(f"invalid contract version: {value!r}")
        return cls(int(match.group(1)), int(match.group(2)))

    def supports(self, required: str | "ContractVersion") -> bool:
        requirement = self.parse(required)
        return self.major == requirement.major and self.minor >= requirement.minor

    def require_supports(self, required: str | "ContractVersion") -> None:
        requirement = self.parse(required)
        if not self.supports(requirement):
            raise ContractCompatibilityError(
                f"provided contract {self} does not satisfy required {requirement}"
            )

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ContractVersion):
            return NotImplemented
        return (self.major, self.minor) < (other.major, other.minor)


@dataclass(frozen=True)
class ContractRef:
    name: str
    version: ContractVersion

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "name", require_namespaced_identifier(self.name, field="contract name")
        )
        object.__setattr__(self, "version", ContractVersion.parse(self.version))

    @classmethod
    def parse(cls, value: str) -> "ContractRef":
        name, separator, version = str(value).rpartition("@")
        if not separator:
            raise ValueError(f"contract reference must use name@major.minor: {value!r}")
        return cls(name, ContractVersion.parse(version))

    def satisfies(self, required: "ContractRef") -> bool:
        return self.name == required.name and self.version.supports(required.version)

    def require_satisfies(self, required: "ContractRef") -> None:
        if self.name != required.name:
            raise ContractCompatibilityError(
                f"provided contract {self.name!r} does not match {required.name!r}"
            )
        self.version.require_supports(required.version)

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "version": str(self.version)}

    def __str__(self) -> str:
        return f"{self.name}@{self.version}"

