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
WORKFLOW_LOCK = ContractRef("siestaflow.workflow-lock", CORE_CONTRACT_VERSION)
RUN_LOCK = ContractRef("siestaflow.run-lock", CORE_CONTRACT_VERSION)
PLUGIN_DESCRIPTOR = ContractRef(
    "siestaflow.plugin-descriptor", CORE_CONTRACT_VERSION
)
SCIENTIFIC_INTENT = ContractRef(
    "siestaflow.scientific-intent", CORE_CONTRACT_VERSION
)
WORKFLOW_DEFINITION = ContractRef(
    "siestaflow.workflow-definition", CORE_CONTRACT_VERSION
)
SCIENTIFIC_ARTIFACT = ContractRef(
    "siestaflow.scientific-artifact", CORE_CONTRACT_VERSION
)
NUMERICAL_PROFILE = ContractRef(
    "siestaflow.numerical-profile", CORE_CONTRACT_VERSION
)
SCIENTIFIC_APPROVAL = ContractRef(
    "siestaflow.scientific-approval", CORE_CONTRACT_VERSION
)

CORE_CONTRACTS = (
    VALIDATION_REPORT,
    ARTIFACT_REFERENCE,
    EXECUTION_REQUEST,
    EXECUTION_EVIDENCE,
    WORKFLOW_EVENT,
    WORKFLOW_LOCK,
    RUN_LOCK,
    PLUGIN_DESCRIPTOR,
    SCIENTIFIC_INTENT,
    WORKFLOW_DEFINITION,
    SCIENTIFIC_ARTIFACT,
    NUMERICAL_PROFILE,
    SCIENTIFIC_APPROVAL,
)


def contract_catalog() -> tuple[ContractRef, ...]:
    return CORE_CONTRACTS
