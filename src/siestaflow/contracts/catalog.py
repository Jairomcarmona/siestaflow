"""Built-in public contract identities."""

from __future__ import annotations

from .versioning import ContractRef, ContractVersion


CORE_CONTRACT_VERSION = ContractVersion(1, 0)

VALIDATION_REPORT = ContractRef(
    "siestaflow.validation-report", CORE_CONTRACT_VERSION
)
ARTIFACT_REFERENCE = ContractRef(
    "siestaflow.artifact-reference", CORE_CONTRACT_VERSION
)
EXECUTION_REQUEST = ContractRef(
    "siestaflow.execution-request", CORE_CONTRACT_VERSION
)
EXECUTION_EVIDENCE = ContractRef(
    "siestaflow.execution-evidence", CORE_CONTRACT_VERSION
)
WORKFLOW_EVENT = ContractRef("siestaflow.workflow-event", CORE_CONTRACT_VERSION)
PLUGIN_DESCRIPTOR = ContractRef(
    "siestaflow.plugin-descriptor", CORE_CONTRACT_VERSION
)

CORE_CONTRACTS = (
    VALIDATION_REPORT,
    ARTIFACT_REFERENCE,
    EXECUTION_REQUEST,
    EXECUTION_EVIDENCE,
    WORKFLOW_EVENT,
    PLUGIN_DESCRIPTOR,
)


def contract_catalog() -> tuple[ContractRef, ...]:
    return CORE_CONTRACTS

