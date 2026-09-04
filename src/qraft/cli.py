"""Project-agnostic, local-only SIESTA preparation and simulation CLI."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from .engines.siesta.fdf_parser import FDFParser
from .engines.siesta.input_validator import SiestaInputValidator
from .engines.siesta.models import FDFBlock, FDFInclude, FDFScalar, FDFUnknown
from .engines.siesta.pseudopotentials import PseudopotentialManifest, PseudopotentialVerifier
from .engines.siesta.validation_catalog import SiestaValidationCatalog
from .engines.siesta.validation_profile import SiestaValidationProfile
from .errors import QraftError
from .examples import ExampleRegistry, ExampleService
from .models import AuthorizationEnvelope, CampaignManifest, TaskSpec, primitive
from .project_packages import ProjectPackageLoader, load_structured
from .project_scaffold import (
    ProjectInitRequest,
    ProjectScaffolder,
    render_project_init,
)
from .remote import RemotePackager, RemoteResultImporter
from .remote_environment import EnvironmentProbePackager, RemoteEnvironmentImporter, RemoteEnvironmentStatus
from .siesta_campaigns import CampaignDefinition, SiestaCampaignFactory, simulate_definition
from .siesta_validation import SiestaContextualValidator
from .execution.allocation_controller import ExecutionStatus
from .execution.canonical_controller import CanonicalController
from .execution.campaign_progress import read_campaign_progress, render_campaign_progress
from .m4_remote_package import M4RemoteSmokePackager
from .controller_package import ControllerPackageBuilder
from .band_results import BandResultExporter
from .optical_results import OpticalResultExporter
from .dos_pdos_results import DOSPDOSResultExporter
from .run_inspection import RunInspector
from .run_preparation import RunPreparer, RunPreparationRequest
from .execution_profile import SlurmExecutionProfile
from .slurm_resources import (
    LiveSlurmPlacementService,
    build_snapshot,
    discover_snapshot,
    load_snapshot,
    memory_megabytes,
    resolve_candidates,
    sha256_file,
    utc_now,
    walltime_seconds,
    write_live_selection_provenance,
    write_snapshot,
)
from .validation.scheduler_resolution import ResourceRequest as SlurmResourceRequest
from .workflows import (
    WorkflowCompiler,
    render_workflow_graph,
    render_workflow_plan,
    workflow_graph,
    workflow_plan,
    write_workflow_lock,
)
from .validation_render import render_validation_report
from .workflow_preflight import WorkflowPreflightValidator
from .workflow_authoring import WorkflowAuthoringService
from .scientific_approvals import create_approved_profile, create_decision
from .application import (
    ApplicationConfiguration, QraftApplication, render_config, render_plan,
    render_preflight,
)
from .environment_inspection import render_environment
from .execution.adapters import launcher_registry


class CommandClassification(str, Enum):
    """Current-surface classification, retained until the V2 hierarchy lands."""

    PUBLIC = "PUBLIC"
    ADVANCED_PUBLIC = "ADVANCED_PUBLIC"
    LEGACY = "LEGACY"
    INTERNAL = "INTERNAL"


class CommandVisibility(str, Enum):
    """Whether a command is included in ordinary parser discovery."""

    PRIMARY = "PRIMARY"
    ADVANCED = "ADVANCED"
    HIDDEN = "HIDDEN"


class CommandSideEffect(str, Enum):
    """Coarse behavior metadata for future help and automation policy."""

    READ_ONLY = "READ_ONLY"
    WRITE_LOCAL = "WRITE_LOCAL"
    EXECUTE = "EXECUTE"
    PACKAGE_ONLY = "PACKAGE_ONLY"
    MIXED = "MIXED"


class CommandInputPolicy(str, Enum):
    """Current commands never require an interactive prompt."""

    NEVER_PROMPT = "NEVER_PROMPT"


@dataclass(frozen=True)
class CommandAlias:
    """A future-compatible alternate spelling owned by one command spec."""

    path: tuple[str, ...]


@dataclass(frozen=True)
class CommandOption:
    """Named reusable option metadata; parser binding remains phase-two work."""

    id: str
    flags: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class CommandSurface:
    """Immutable command-tree record and sole current presentation authority."""

    id: str
    path: tuple[str, ...]
    parent_id: str | None
    classification: CommandClassification
    visibility: CommandVisibility
    order: int
    summary: str
    description: str
    usage: str | None
    examples: tuple[str, ...]
    aliases: tuple[CommandAlias, ...]
    handler_id: str
    json_supported: bool
    side_effect: CommandSideEffect
    input_policy: CommandInputPolicy
    option_ids: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """Compatibility accessor for the existing top-level surface API."""

        return self.path[-1]


_SHARED_COMMAND_OPTIONS = (
    CommandOption("output.json", ("--json",), "emit the command result as JSON"),
    CommandOption("execution.profile", ("--profile",), "select an execution profile"),
    CommandOption("execution.resolution", ("--project-config", "--recipe"), "supply execution resolution inputs"),
    CommandOption("execution.runs-root", ("--runs-root",), "select persistent run state"),
)


def _command(
    id: str, name: str, classification: CommandClassification,
    visibility: CommandVisibility, order: int, summary: str, *,
    usage: str | None, handler_id: str, json_supported: bool,
    side_effect: CommandSideEffect, option_ids: tuple[str, ...] = (),
) -> CommandSurface:
    """Keep the current flat surface concise while preparing a command tree."""

    return CommandSurface(
        id=id,
        path=(name,),
        parent_id=None,
        classification=classification,
        visibility=visibility,
        order=order,
        summary=summary,
        description=summary,
        usage=usage,
        examples=(),
        aliases=(),
        handler_id=handler_id,
        json_supported=json_supported,
        side_effect=side_effect,
        input_policy=CommandInputPolicy.NEVER_PROMPT,
        option_ids=option_ids,
    )


# This registry is the current command-specification authority. Parser
# definitions consume its help, visibility, classification, and handler
# metadata; the REPL consumes the same public discovery API. The V2 grouped
# hierarchy is deliberately not introduced in this phase.
_COMMAND_SURFACE = (
    _command("qraft.init", "init", CommandClassification.PUBLIC, CommandVisibility.PRIMARY, 10, "create a minimal editable CampaignSpec template", usage="qraft init [PATH] [--force] [--json]", handler_id="init", json_supported=True, side_effect=CommandSideEffect.WRITE_LOCAL, option_ids=("output.json",)),
    _command("qraft.env", "env", CommandClassification.PUBLIC, CommandVisibility.PRIMARY, 20, "inspect installed execution capabilities", usage="qraft env [execution options] [--json]", handler_id="env", json_supported=True, side_effect=CommandSideEffect.READ_ONLY, option_ids=("execution.profile", "execution.resolution", "output.json")),
    _command("qraft.config", "config", CommandClassification.PUBLIC, CommandVisibility.PRIMARY, 30, "show effective execution configuration", usage="qraft config [execution options] [--json]", handler_id="config", json_supported=True, side_effect=CommandSideEffect.READ_ONLY, option_ids=("execution.profile", "execution.resolution", "output.json")),
    _command("qraft.profile", "profile", CommandClassification.PUBLIC, CommandVisibility.PRIMARY, 40, "list, show or validate execution profiles", usage="qraft profile {list,show,validate} ...", handler_id="profile", json_supported=False, side_effect=CommandSideEffect.READ_ONLY),
    _command("qraft.validate", "validate", CommandClassification.PUBLIC, CommandVisibility.PRIMARY, 50, "validate one FDF and its execution preflight", usage="qraft validate FDF [execution options] [--json]", handler_id="validate", json_supported=True, side_effect=CommandSideEffect.READ_ONLY, option_ids=("execution.profile", "execution.resolution", "output.json")),
    _command("qraft.plan", "plan", CommandClassification.PUBLIC, CommandVisibility.PRIMARY, 60, "resolve an executable three-node plan from one FDF", usage="qraft plan FDF [execution options] [--json]", handler_id="plan", json_supported=True, side_effect=CommandSideEffect.READ_ONLY, option_ids=("execution.profile", "execution.resolution", "output.json")),
    _command("qraft.render", "render", CommandClassification.PUBLIC, CommandVisibility.PRIMARY, 70, "materialize CampaignSpec FDF variants without execution", usage="qraft render FDF [--output PATH] [--json]", handler_id="render", json_supported=True, side_effect=CommandSideEffect.WRITE_LOCAL, option_ids=("output.json",)),
    _command("qraft.run", "run", CommandClassification.PUBLIC, CommandVisibility.PRIMARY, 80, "execute one FDF or manage hash-bound run packages", usage="qraft run FDF [execution options] [--json]", handler_id="run", json_supported=True, side_effect=CommandSideEffect.EXECUTE, option_ids=("execution.profile", "execution.resolution", "execution.runs-root", "output.json")),
    _command("qraft.status", "status", CommandClassification.PUBLIC, CommandVisibility.PRIMARY, 90, "inspect single-FDF campaign state", usage="qraft status [--runs-root PATH] [--json]", handler_id="status", json_supported=True, side_effect=CommandSideEffect.READ_ONLY, option_ids=("execution.runs-root", "output.json")),
    _command("qraft.resume", "resume", CommandClassification.PUBLIC, CommandVisibility.PRIMARY, 100, "resume the saved single-FDF session", usage="qraft resume [FDF] [execution options] [--json]", handler_id="resume", json_supported=True, side_effect=CommandSideEffect.EXECUTE, option_ids=("execution.profile", "execution.runs-root", "output.json")),
    _command("qraft.project", "project", CommandClassification.ADVANCED_PUBLIC, CommandVisibility.ADVANCED, 110, "advanced: prepare and inspect reproducible project packages", usage="qraft project {init,inspect,validate,load} ...", handler_id="project", json_supported=False, side_effect=CommandSideEffect.MIXED),
    _command("qraft.fdf", "fdf", CommandClassification.ADVANCED_PUBLIC, CommandVisibility.ADVANCED, 120, "advanced: inspect parsed SIESTA FDF inputs", usage="qraft fdf inspect PATH [--json]", handler_id="fdf", json_supported=False, side_effect=CommandSideEffect.READ_ONLY),
    _command("qraft.input", "input", CommandClassification.ADVANCED_PUBLIC, CommandVisibility.ADVANCED, 130, "advanced: validate SIESTA inputs and view validation rules", usage="qraft input {validate,rules} ...", handler_id="input", json_supported=False, side_effect=CommandSideEffect.READ_ONLY),
    _command("qraft.environment", "environment", CommandClassification.LEGACY, CommandVisibility.HIDDEN, 140, "legacy spelling for the public env inspection", usage="qraft environment check ...", handler_id="environment", json_supported=False, side_effect=CommandSideEffect.READ_ONLY),
    _command("qraft.pseudo", "pseudo", CommandClassification.ADVANCED_PUBLIC, CommandVisibility.ADVANCED, 150, "advanced: verify pseudopotential manifests", usage="qraft pseudo verify MANIFEST [--json]", handler_id="pseudo", json_supported=False, side_effect=CommandSideEffect.READ_ONLY),
    _command("qraft.campaign", "campaign", CommandClassification.ADVANCED_PUBLIC, CommandVisibility.ADVANCED, 160, "advanced: manage allocation-controller campaigns", usage="qraft campaign ACTION ...", handler_id="campaign", json_supported=False, side_effect=CommandSideEffect.MIXED),
    _command("qraft.workflow", "workflow", CommandClassification.ADVANCED_PUBLIC, CommandVisibility.ADVANCED, 170, "advanced: author, validate and compile workflow definitions", usage="qraft workflow ACTION ...", handler_id="workflow", json_supported=False, side_effect=CommandSideEffect.MIXED),
    _command("qraft.scientific", "scientific", CommandClassification.ADVANCED_PUBLIC, CommandVisibility.ADVANCED, 180, "advanced: record reviewed scientific decisions and profiles", usage="qraft scientific {decide,profile} ...", handler_id="scientific", json_supported=False, side_effect=CommandSideEffect.WRITE_LOCAL),
    _command("qraft.results", "results", CommandClassification.ADVANCED_PUBLIC, CommandVisibility.ADVANCED, 190, "advanced: export verified SIESTA result tables", usage="qraft results {dos-pdos,bands,optics} ...", handler_id="results", json_supported=False, side_effect=CommandSideEffect.WRITE_LOCAL),
    _command("qraft.examples", "examples", CommandClassification.ADVANCED_PUBLIC, CommandVisibility.ADVANCED, 200, "advanced: inspect and package curated examples", usage="qraft examples ACTION ...", handler_id="examples", json_supported=False, side_effect=CommandSideEffect.MIXED),
    _command("qraft.remote", "remote", CommandClassification.ADVANCED_PUBLIC, CommandVisibility.ADVANCED, 210, "advanced: create or inspect non-submitting remote artifacts", usage="qraft remote ACTION ...", handler_id="remote", json_supported=False, side_effect=CommandSideEffect.PACKAGE_ONLY),
    _command("qraft.internal.fdf-run", "_fdf-run", CommandClassification.INTERNAL, CommandVisibility.HIDDEN, 220, "internal compatibility adapter for single-FDF runs", usage=None, handler_id="_fdf-run", json_supported=True, side_effect=CommandSideEffect.EXECUTE, option_ids=("execution.profile", "execution.resolution", "execution.runs-root", "output.json")),
)


def validate_command_surface(commands: tuple[CommandSurface, ...]) -> None:
    """Fail deterministically for command-specification programming defects."""

    ids: set[str] = set()
    canonical_paths: dict[tuple[str, ...], str] = {}
    commands_by_id: dict[str, CommandSurface] = {}
    for command in commands:
        if not command.id:
            raise ValueError("command specification has an empty id")
        if command.id in ids:
            raise ValueError(f"duplicate command id: {command.id}")
        ids.add(command.id)
        commands_by_id[command.id] = command
        if not command.path or any(not token for token in command.path):
            raise ValueError(f"command {command.id} has an invalid canonical path")
        owner = canonical_paths.setdefault(command.path, command.id)
        if owner != command.id:
            rendered = " ".join(command.path)
            raise ValueError(f"duplicate canonical command path: {rendered}")
        if (
            command.classification is CommandClassification.INTERNAL
            and command.visibility is not CommandVisibility.HIDDEN
        ):
            raise ValueError(f"internal command must be hidden: {command.id}")
    for command in commands:
        if command.parent_id is None:
            continue
        parent = commands_by_id.get(command.parent_id)
        if parent is None:
            raise ValueError(
                f"command {command.id} references unknown parent: {command.parent_id}"
            )
        if command.path[:-1] != parent.path:
            raise ValueError(
                f"command {command.id} path does not extend parent {command.parent_id}"
            )
    alias_owners: dict[tuple[str, ...], str] = {}
    for command in commands:
        for alias in command.aliases:
            if not alias.path or any(not token for token in alias.path):
                raise ValueError(f"command {command.id} has an invalid alias path")
            if alias.path in canonical_paths:
                rendered = " ".join(alias.path)
                raise ValueError(f"alias collides with canonical command path: {rendered}")
            owner = alias_owners.setdefault(alias.path, command.id)
            if owner != command.id:
                rendered = " ".join(alias.path)
                raise ValueError(f"ambiguous alias ownership for {rendered}: {owner}, {command.id}")


validate_command_surface(_COMMAND_SURFACE)
_COMMAND_SPECS_BY_PATH = {command.path: command for command in _COMMAND_SURFACE}
_COMMAND_OPTION_SPECS_BY_ID = {option.id: option for option in _SHARED_COMMAND_OPTIONS}


def shared_command_options() -> tuple[CommandOption, ...]:
    """Return immutable reusable option metadata for future parser bindings."""

    return _SHARED_COMMAND_OPTIONS


def validate_command_option_references(
    commands: tuple[CommandSurface, ...],
    options: tuple[CommandOption, ...],
) -> None:
    """Reject duplicate option records and dangling command option references."""

    option_ids = {option.id for option in options}
    if len(option_ids) != len(options):
        raise ValueError("duplicate shared command option id")
    for command in commands:
        unknown = set(command.option_ids) - option_ids
        if unknown:
            rendered = ", ".join(sorted(unknown))
            raise ValueError(
                f"command {command.id} references unknown shared option: {rendered}"
            )


validate_command_option_references(_COMMAND_SURFACE, _SHARED_COMMAND_OPTIONS)


def command_surface() -> tuple[CommandSurface, ...]:
    """Return the complete immutable current command specification."""

    return _COMMAND_SURFACE


def command_spec(path: tuple[str, ...]) -> CommandSurface:
    """Look up one canonical command record without a parallel name list."""

    return _COMMAND_SPECS_BY_PATH[path]


def parser_visible_command_surface() -> tuple[CommandSurface, ...]:
    """Return the current top-level commands argparse exposes in ordinary help."""

    return tuple(
        command for command in _COMMAND_SURFACE
        if len(command.path) == 1 and command.visibility is not CommandVisibility.HIDDEN
    )


def public_command_surface() -> tuple[CommandSurface, ...]:
    """Return every command presented to installed-product users."""

    return tuple(
        command for command in _COMMAND_SURFACE
        if command.classification in {
            CommandClassification.PUBLIC,
            CommandClassification.ADVANCED_PUBLIC,
        }
    )


def public_command_metavar() -> str:
    """Build argparse's usage metavar from the presentation authority."""

    return "{" + ",".join(command.name for command in public_command_surface()) + "}"


def public_command_help() -> tuple[tuple[str, str], ...]:
    """Return stable, concise command discovery rows for the REPL and tests."""

    return tuple((command.name, command.summary) for command in public_command_surface())


def _add_single_fdf_arguments(command: argparse.ArgumentParser, *, execute: bool) -> None:
    command.add_argument("fdf", type=Path)
    command.add_argument("--pseudo-manifest", type=Path)
    command.add_argument("--profile")
    command.add_argument("--project-config", type=Path)
    command.add_argument("--recipe", type=Path)
    command.add_argument("--partition")
    command.add_argument("--nodes", type=int)
    command.add_argument("--np", dest="mpi_ranks", type=int)
    command.add_argument("--cpus-per-rank", type=int)
    command.add_argument("--memory-mb", type=int)
    command.add_argument("--launcher", choices=launcher_registry.names())
    command.add_argument("--siesta", dest="executable")
    command.add_argument("--siesta-argument", action="append", default=None)
    command.add_argument("--walltime-seconds", type=int)
    command.add_argument("--launcher-command", nargs="+")
    command.add_argument("--launcher-argument", action="append", default=None)
    command.add_argument(
        "--env", action="append", default=[], metavar="NAME=VALUE",
        help="execution environment entry; repeat for multiple values",
    )
    if execute:
        command.add_argument("--runs-root", type=Path, default=Path(".qraft-runs"))
        command.add_argument("--force-new-attempt", action="store_true")
    command.add_argument("--json", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qraft", description="SIESTA preparation, allocation-local execution, and evidence handling")
    parser.add_argument("--version", action="version", version=f"QRAFT {__version__}")
    parser.add_argument("--workspace", type=Path, default=Path(".qraft-work"))
    parser.add_argument("--examples-root", type=Path, default=Path("examples"), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(
        dest="domain",
        required=True,
        metavar=public_command_metavar(),
    )

    def add_resolution_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--profile")
        command.add_argument("--project-config", type=Path)
        command.add_argument("--recipe", type=Path)
        command.add_argument("--partition")
        command.add_argument("--nodes", type=int)
        command.add_argument("--np", dest="mpi_ranks", type=int)
        command.add_argument("--cpus-per-rank", type=int)
        command.add_argument("--launcher", choices=launcher_registry.names())
        command.add_argument("--siesta", dest="executable")
        command.add_argument("--walltime-seconds", type=int)
        command.add_argument("--json", action="store_true")

    env = sub.add_parser("env", help=command_spec(("env",)).summary)
    add_resolution_options(env)
    config = sub.add_parser("config", help=command_spec(("config",)).summary)
    add_resolution_options(config)
    init = sub.add_parser("init", help=command_spec(("init",)).summary)
    init.add_argument("path", nargs="?", type=Path, default=Path("campaign.yaml"))
    init.add_argument("--force", action="store_true", help="replace an existing template")
    init.add_argument("--json", action="store_true")
    validate = sub.add_parser("validate", help=command_spec(("validate",)).summary)
    _add_single_fdf_arguments(validate, execute=False)
    render = sub.add_parser("render", help=command_spec(("render",)).summary)
    render.add_argument("fdf", type=Path)
    render.add_argument("--output", type=Path, default=Path(".qraft-render"))
    render.add_argument("--json", action="store_true")
    profiles = sub.add_parser("profile", help=command_spec(("profile",)).summary)
    profile_sub = profiles.add_subparsers(dest="action", required=True)
    profile_sub.add_parser("list").add_argument("--json", action="store_true")
    for action in ("show", "validate"):
        profile_command = profile_sub.add_parser(action)
        profile_command.add_argument("reference", nargs="?")
        profile_command.add_argument("--json", action="store_true")
    status = sub.add_parser("status", help=command_spec(("status",)).summary)
    status.add_argument("--runs-root", type=Path, default=Path(".qraft-runs"))
    status.add_argument("--json", action="store_true")
    resume = sub.add_parser("resume", help=command_spec(("resume",)).summary)
    resume.add_argument("fdf", nargs="?", type=Path)
    resume.add_argument("--profile")
    resume.add_argument("--runs-root", type=Path, default=Path(".qraft-runs"))
    resume.add_argument("--partition")
    resume.add_argument("--nodes", type=int)
    resume.add_argument("--np", dest="mpi_ranks", type=int)
    resume.add_argument("--cpus-per-rank", type=int)
    resume.add_argument("--launcher", choices=launcher_registry.names())
    resume.add_argument("--siesta", dest="executable")
    resume.add_argument("--walltime-seconds", type=int)
    resume.add_argument("--json", action="store_true")

    single_plan = sub.add_parser(
        "plan", help=command_spec(("plan",)).summary
    )
    _add_single_fdf_arguments(single_plan, execute=False)
    single_run = sub.add_parser("_fdf-run", prog="qraft run", help=command_spec(("_fdf-run",)).summary)
    _add_single_fdf_arguments(single_run, execute=True)

    project = sub.add_parser("project", help=command_spec(("project",)).summary)
    project_sub = project.add_subparsers(dest="action", required=True)
    project_init = project_sub.add_parser(
        "init",
        help="create a preparation-only project from real researcher inputs",
    )
    project_init.add_argument("path", type=Path)
    project_init.add_argument("--project-id", required=True)
    project_init.add_argument("--title")
    project_init.add_argument("--system-id", required=True)
    project_init.add_argument("--fdf", type=Path, required=True)
    project_init.add_argument("--structure", type=Path, required=True)
    project_init.add_argument(
        "--pseudo-manifest",
        type=Path,
        required=True,
    )
    project_init.add_argument("--dry-run", action="store_true")
    project_init.add_argument("--json", action="store_true")
    for action in ("inspect", "validate", "load"):
        command = project_sub.add_parser(action)
        command.add_argument("path", type=Path)
        command.add_argument("--json", action="store_true")

    fdf = sub.add_parser("fdf", help=command_spec(("fdf",)).summary)
    fdf_sub = fdf.add_subparsers(dest="action", required=True)
    fdf_inspect = fdf_sub.add_parser("inspect")
    fdf_inspect.add_argument("path", type=Path)
    fdf_inspect.add_argument("--json", action="store_true")

    inp = sub.add_parser("input", help=command_spec(("input",)).summary)
    inp_sub = inp.add_subparsers(dest="action", required=True)
    inp_validate = inp_sub.add_parser("validate")
    inp_validate.add_argument("path", type=Path)
    inp_validate.add_argument("--pseudo-manifest", type=Path)
    inp_validate.add_argument("--require-pseudos", action="store_true")
    inp_validate.add_argument("--profile", type=Path)
    inp_validate.add_argument(
        "--engine-version",
        choices=("5.4.2",),
        default="5.4.2",
    )
    inp_validate.add_argument(
        "--explain",
        action="store_true",
        help="render evidence and remediation for every finding",
    )
    inp_validate.add_argument("--json", action="store_true")
    inp_rules = inp_sub.add_parser(
        "rules",
        help="list the versioned built-in SIESTA validation rules",
    )
    inp_rules.add_argument(
        "--engine-version",
        choices=("5.4.2",),
        default="5.4.2",
    )
    inp_rules.add_argument("--json", action="store_true")

    environment = sub.add_parser("environment", help=command_spec(("environment",)).summary)
    environment_sub = environment.add_subparsers(dest="action", required=True)
    environment_check = environment_sub.add_parser("check")
    environment_check.add_argument("--siesta", default="siesta")
    environment_check.add_argument(
        "--launcher",
        choices=("auto", "direct", "srun", "mpiexec", "mpirun"),
        default="auto",
    )
    environment_check.add_argument("--require-slurm", action="store_true")
    environment_check.add_argument(
        "--working-directory",
        type=Path,
        default=Path("."),
    )
    environment_check.add_argument("--json", action="store_true")

    pseudo = sub.add_parser("pseudo", help=command_spec(("pseudo",)).summary)
    pseudo_sub = pseudo.add_subparsers(dest="action", required=True)
    pseudo_verify = pseudo_sub.add_parser("verify")
    pseudo_verify.add_argument("manifest", type=Path)
    pseudo_verify.add_argument("--species", nargs="*")
    pseudo_verify.add_argument("--json", action="store_true")

    campaign = sub.add_parser("campaign", help=command_spec(("campaign",)).summary)
    campaign_sub = campaign.add_subparsers(dest="action", required=True)
    create = campaign_sub.add_parser("create")
    create.add_argument("--project", type=Path, required=True)
    create.add_argument("--campaign-id", required=True)
    create.add_argument("--dry-run", action="store_true")
    create.add_argument("--json", action="store_true")
    for action in ("validate", "simulate", "status"):
        command = campaign_sub.add_parser(action)
        command.add_argument("campaign")
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--json", action="store_true")
    worker = campaign_sub.add_parser("worker")
    worker.add_argument("campaign", type=Path)
    worker.add_argument("--root", type=Path)
    worker.add_argument("--json", action="store_true")
    progress = campaign_sub.add_parser("progress")
    progress.add_argument("path", type=Path)
    progress.add_argument("--json", action="store_true")
    watch = campaign_sub.add_parser("watch")
    watch.add_argument("path", type=Path)
    watch.add_argument("--interval", type=float, default=10.0)
    watch.add_argument(
        "--iterations", type=int, default=0,
        help="0 watches until a terminal state; positive values bound refreshes",
    )
    watch.add_argument("--json", action="store_true")

    workflow = sub.add_parser("workflow", help=command_spec(("workflow",)).summary)
    workflow_sub = workflow.add_subparsers(dest="action", required=True)
    workflow_recipes = workflow_sub.add_parser(
        "recipes", help="list registered workflow recipes"
    )
    workflow_recipes.add_argument("--json", action="store_true")
    workflow_recipe = workflow_sub.add_parser(
        "recipe", help="show one registered workflow recipe"
    )
    workflow_recipe.add_argument("recipe_id")
    workflow_recipe.add_argument("--json", action="store_true")
    workflow_create = workflow_sub.add_parser(
        "create", help="create a canonical WorkflowDefinition from a scientific intent"
    )
    workflow_create.add_argument("intent", type=Path)
    workflow_create.add_argument("--output", type=Path, required=True)
    workflow_create.add_argument("--dry-run", action="store_true")
    workflow_create.add_argument("--json", action="store_true")
    workflow_compose = workflow_sub.add_parser(
        "compose", help="preview or create a researcher-selected modular workflow"
    )
    workflow_compose.add_argument("intent", type=Path)
    workflow_compose.add_argument("--output", type=Path, required=True)
    workflow_compose.add_argument("--dry-run", action="store_true")
    workflow_compose.add_argument("--json", action="store_true")
    workflow_validate = workflow_sub.add_parser(
        "validate", help="validate schema, artifacts, and graph consistency"
    )
    workflow_validate.add_argument("definition", type=Path)
    workflow_validate.add_argument("--json", action="store_true")
    workflow_preflight = workflow_sub.add_parser(
        "preflight",
        help="validate all external SIESTA FDF inputs in the resolved DAG",
    )
    workflow_preflight.add_argument("definition", type=Path)
    workflow_preflight.add_argument("--profile", type=Path)
    workflow_preflight.add_argument("--pseudo-manifest", type=Path)
    workflow_preflight.add_argument(
        "--require-pseudos",
        action="store_true",
    )
    workflow_preflight.add_argument("--json", action="store_true")
    workflow_plan_parser = workflow_sub.add_parser(
        "plan", help="show the resolved topological execution plan"
    )
    workflow_plan_parser.add_argument("definition", type=Path)
    workflow_plan_parser.add_argument("--json", action="store_true")
    workflow_graph_parser = workflow_sub.add_parser(
        "graph", help="render dependencies as text, Mermaid, or JSON"
    )
    workflow_graph_parser.add_argument("definition", type=Path)
    workflow_graph_parser.add_argument(
        "--format", choices=("text", "mermaid", "json"), default="text"
    )
    workflow_compile = workflow_sub.add_parser(
        "compile", help="write a deterministic workflow.lock.json"
    )
    workflow_compile.add_argument("definition", type=Path)
    workflow_compile.add_argument("--output", type=Path, required=True)
    workflow_compile.add_argument("--force", action="store_true")
    workflow_compile.add_argument("--dry-run", action="store_true")
    workflow_compile.add_argument("--json", action="store_true")

    scientific = sub.add_parser("scientific", help=command_spec(("scientific",)).summary)
    scientific_sub = scientific.add_subparsers(dest="action", required=True)
    scientific_decide = scientific_sub.add_parser(
        "decide", help="record APPROVE or REJECT for reviewed convergence evidence"
    )
    scientific_decide.add_argument("report", type=Path)
    scientific_decide.add_argument("--approval-id", required=True)
    scientific_decide.add_argument("--decision", choices=("APPROVE", "REJECT"), required=True)
    scientific_decide.add_argument("--actor", required=True)
    scientific_decide.add_argument("--decided-at", required=True)
    scientific_decide.add_argument("--output", type=Path, required=True)
    scientific_decide.add_argument("--json", action="store_true")
    scientific_profile = scientific_sub.add_parser(
        "profile", help="materialize an approved numerical profile from matching decision and evidence"
    )
    scientific_profile.add_argument("report", type=Path)
    scientific_profile.add_argument("--approval", type=Path, required=True)
    scientific_profile.add_argument("--profile-id", required=True)
    scientific_profile.add_argument("--output", type=Path, required=True)
    scientific_profile.add_argument("--json", action="store_true")

    prepared_run = sub.add_parser(
        "run",
        help=command_spec(("run",)).summary,
    )
    prepared_run_sub = prepared_run.add_subparsers(
        dest="action",
        required=True,
    )
    run_prepare = prepared_run_sub.add_parser(
        "prepare",
        help="adapt a workflow lock to a self-contained Slurm package",
    )
    run_prepare.add_argument("workflow_lock", type=Path)
    run_prepare.add_argument("--source-root", type=Path, required=True)
    run_prepare.add_argument("--profile", type=Path, required=True)
    run_prepare.add_argument("--output", type=Path, required=True)
    run_prepare.add_argument("--run-id", required=True)
    run_prepare.add_argument("--snapshot", type=Path)
    run_prepare.add_argument("--candidate")
    run_prepare.add_argument("--confirm", action="store_true")
    run_prepare.add_argument("--partition")
    run_prepare.add_argument("--nodes", type=int)
    run_prepare.add_argument("--ranks-per-node", type=int)
    run_prepare.add_argument("--cpus-per-task", type=int, default=1)
    run_prepare.add_argument("--account")
    run_prepare.add_argument("--qos")
    run_prepare.add_argument("--walltime")
    run_prepare.add_argument("--required-feature", action="append", default=[])
    run_prepare.add_argument("--compatibility-evidence", type=Path)
    run_prepare.add_argument("--dry-run", action="store_true")
    run_prepare.add_argument("--json", action="store_true")
    run_candidates = prepared_run_sub.add_parser(
        "candidates", help="rank Slurm snapshot candidates without submission"
    )
    run_candidates.add_argument("--workflow", type=Path, required=True)
    run_candidates.add_argument("--profile", type=Path, required=True)
    run_candidates.add_argument("--snapshot", type=Path, required=True)
    run_candidates.add_argument("--json", action="store_true")
    run_discover = prepared_run_sub.add_parser(
        "discover", help="capture a read-only Slurm capability snapshot"
    )
    run_discover.add_argument("--cluster-id", required=True)
    run_discover.add_argument("--output", type=Path, required=True)
    run_discover.add_argument("--json", action="store_true")
    run_resources = prepared_run_sub.add_parser(
        "resources", help="show live Slurm resources without selecting one"
    )
    run_resources.add_argument("--account")
    run_resources.add_argument("--qos")
    run_resources.add_argument("--cpus-per-task", type=int, default=1)
    run_resources.add_argument("--walltime", default="00:20:00")
    run_resources.add_argument("--json", action="store_true")
    run_placement = prepared_run_sub.add_parser(
        "placement", help="derive one explicit live Slurm placement"
    )
    run_placement.add_argument("--partition", required=True)
    run_placement.add_argument("--nodes", type=int)
    run_placement.add_argument("--account")
    run_placement.add_argument("--qos")
    run_placement.add_argument("--cpus-per-task", type=int, default=1)
    run_placement.add_argument("--walltime", default="00:20:00")
    run_placement.add_argument("--output", type=Path, required=True)
    run_placement.add_argument("--json", action="store_true")
    run_import = prepared_run_sub.add_parser(
        "snapshot-import", help="import saved read-only scheduler command output"
    )
    run_import.add_argument("--cluster-id", required=True)
    run_import.add_argument("--output", type=Path, required=True)
    run_import.add_argument("--sinfo", type=Path)
    run_import.add_argument("--scontrol-partitions", type=Path)
    run_import.add_argument("--scontrol-nodes", type=Path)
    run_import.add_argument("--sacctmgr", type=Path)
    run_import.add_argument("--sjstat", type=Path)
    run_import.add_argument("--observed-at", default=None)
    run_import.add_argument("--json", action="store_true")
    for action in ("inspect", "status", "resume"):
        command = prepared_run_sub.add_parser(action)
        command.add_argument("package", type=Path)
        if action == "resume":
            command.add_argument(
                "--previous-job-terminal",
                action="store_true",
                help="confirm that scheduler evidence shows the prior job is terminal",
            )
        command.add_argument("--json", action="store_true")

    results = sub.add_parser("results", help=command_spec(("results",)).summary)
    results_sub = results.add_subparsers(dest="action", required=True)
    dos_pdos = results_sub.add_parser(
        "dos-pdos", help="export total DOS table and PDOS provenance without interpretation"
    )
    dos_pdos.add_argument("package", type=Path)
    dos_pdos.add_argument("--output", type=Path, required=True)
    dos_pdos.add_argument("--dry-run", action="store_true")
    dos_pdos.add_argument("--json", action="store_true")
    bands = results_sub.add_parser(
        "bands", help="export a SIESTA band table without interpretation"
    )
    bands.add_argument("package", type=Path)
    bands.add_argument("--output", type=Path, required=True)
    bands.add_argument("--dry-run", action="store_true")
    bands.add_argument("--json", action="store_true")
    optics = results_sub.add_parser("optics", help="export EPSIMG without interpretation")
    optics.add_argument("package", type=Path); optics.add_argument("--output", type=Path, required=True)
    optics.add_argument("--dry-run", action="store_true"); optics.add_argument("--json", action="store_true")

    examples = sub.add_parser("examples", help=command_spec(("examples",)).summary)
    example_sub = examples.add_subparsers(dest="action", required=True)
    example_sub.add_parser("list").add_argument("--json", action="store_true")
    for action in ("inspect", "validate"):
        command = example_sub.add_parser(action)
        command.add_argument("example")
        command.add_argument("--json", action="store_true")
    stage = example_sub.add_parser("stage")
    stage.add_argument("example"); stage.add_argument("--pseudo-root", dest="source", type=Path, required=True)
    stage.add_argument("--output", type=Path, required=True); stage.add_argument("--policy", choices=("copy", "link"), required=True)
    stage.add_argument("--dry-run", action="store_true"); stage.add_argument("--json", action="store_true")
    pack = example_sub.add_parser("package")
    pack.add_argument("example"); pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--dry-run", action="store_true"); pack.add_argument("--json", action="store_true")
    run = example_sub.add_parser("run")
    run.add_argument("example"); run.add_argument("--campaign-id", required=True); run.add_argument("--json", action="store_true")
    example_results = example_sub.add_parser("results")
    example_results_sub = example_results.add_subparsers(dest="results_action", required=True)
    example_import = example_results_sub.add_parser("import")
    example_import.add_argument("bundle", type=Path); example_import.add_argument("--campaign-id")
    example_import.add_argument("--output", type=Path, required=True); example_import.add_argument("--dry-run", action="store_true")
    example_import.add_argument("--json", action="store_true")

    remote = sub.add_parser("remote", help=command_spec(("remote",)).summary)
    remote_sub = remote.add_subparsers(dest="action", required=True)
    package = remote_sub.add_parser("package")
    package.add_argument("campaign"); package.add_argument("--output", type=Path)
    package.add_argument("--dry-run", action="store_true"); package.add_argument("--json", action="store_true")
    m4_package = remote_sub.add_parser("m4-package")
    m4_package.add_argument("--profile", type=Path, required=True)
    m4_package.add_argument("--output", type=Path, required=True)
    m4_package.add_argument("--json", action="store_true")
    controller_package = remote_sub.add_parser("controller-package")
    controller_package.add_argument("campaign", type=Path)
    controller_package.add_argument("--output", type=Path, required=True)
    controller_package.add_argument("--dry-run", action="store_true")
    controller_package.add_argument("--json", action="store_true")
    results = remote_sub.add_parser("results")
    results_sub = results.add_subparsers(dest="results_action", required=True)
    imp = results_sub.add_parser("import")
    imp.add_argument("bundle", type=Path); imp.add_argument("--campaign-id"); imp.add_argument("--output", type=Path)
    imp.add_argument("--dry-run", action="store_true"); imp.add_argument("--json", action="store_true")
    environment = remote_sub.add_parser("environment")
    environment_sub = environment.add_subparsers(dest="environment_action", required=True)
    env_package = environment_sub.add_parser("package")
    env_package.add_argument("--output", type=Path); env_package.add_argument("--pseudo-manifest", type=Path)
    env_package.add_argument("--status-labels", type=Path)
    env_package.add_argument("--dry-run", action="store_true"); env_package.add_argument("--json", action="store_true")
    env_import = environment_sub.add_parser("import")
    env_import.add_argument("bundle", type=Path); env_import.add_argument("--output", type=Path)
    env_import.add_argument(
        "--canonical-profile", type=Path,
        help="optional explicit destination for an accepted external cluster profile",
    )
    env_import.add_argument("--dry-run", action="store_true"); env_import.add_argument("--json", action="store_true")
    expected_paths = {
        command.path for command in command_surface() if len(command.path) == 1
    }
    actual_paths = {(name,) for name in sub.choices}
    if actual_paths != expected_paths:
        missing = ", ".join(" ".join(path) for path in sorted(expected_paths - actual_paths))
        unexpected = ", ".join(" ".join(path) for path in sorted(actual_paths - expected_paths))
        raise RuntimeError(
            "parser command surface does not match command specification"
            f"; missing: {missing or '-'}; unexpected: {unexpected or '-'}"
        )
    # Keep compatibility parsers dispatchable, but derive ordinary discovery
    # solely from the immutable command specification. Their public spellings
    # remain ``qraft run FDF`` and ``qraft env`` respectively.
    visible_names = {command.name for command in parser_visible_command_surface()}
    sub._choices_actions[:] = [
        action for action in sub._choices_actions
        if action.dest in visible_names
    ]
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        from .repl import run_repl

        return run_repl()
    legacy_run_actions = {
        "prepare", "candidates", "discover", "resources", "placement",
        "snapshot-import",
        "inspect", "status", "resume",
    }
    domain_index = 0
    while domain_index < len(raw):
        token = raw[domain_index]
        if token in {"--workspace", "--examples-root"}:
            domain_index += 2
            continue
        if token.startswith(("--workspace=", "--examples-root=")):
            domain_index += 1
            continue
        break
    if domain_index < len(raw) and raw[domain_index] == "run":
        following = raw[domain_index + 1] if domain_index + 1 < len(raw) else None
        if (
            following is None
            or following in {"-h", "--help"}
            or (following not in legacy_run_actions and not following.startswith("-"))
        ):
            raw[domain_index] = "_fdf-run"
    invocation = shlex.join(("qraft", *raw))
    args = build_parser().parse_args(raw)
    args._invocation = invocation
    try:
        return _dispatch(args)
    except (
        OSError,
        ValueError,
        PermissionError,
        RuntimeError,
        KeyError,
        QraftError,
    ) as exc:
        print(f"QRAFT_ERROR: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.domain == "init":
        path = args.path.resolve()
        if path.exists() and not args.force:
            raise ValueError(
                f"campaign template already exists: {path} (use --force to overwrite)"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_CAMPAIGN_TEMPLATE, encoding="utf-8", newline="\n")
        result = {
            "status": "CREATED",
            "path": str(path),
            "next_step": f"edit {path.name}, then run: qraft validate {path}",
        }
        if args.json:
            _emit(result, True)
        else:
            print(f"Created campaign template: {path}")
            print("Edit the FDF and pseudopotential paths, then validate it:")
            print(f"  qraft validate {path}")
        return 0
    if args.domain in {"env", "config"}:
        overrides = {
            "partition": args.partition,
            "nodes": args.nodes,
            "mpi_ranks": args.mpi_ranks,
            "cpus_per_rank": args.cpus_per_rank,
            "launcher": args.launcher,
            "executable": args.executable,
            "walltime_seconds": args.walltime_seconds,
        }
        application = QraftApplication(ApplicationConfiguration(
            profile=args.profile,
            project_config=args.project_config,
            recipe=args.recipe,
        ))
        if args.domain == "env":
            report = application.environment(command_overrides=overrides)
            _emit(report.to_dict(), True) if args.json else print(render_environment(report))
        else:
            config = application.config(command_overrides=overrides)
            _emit(config, True) if args.json else print(render_config(config))
        return 0
    if args.domain == "profile":
        application = QraftApplication()
        if args.action == "list":
            result: Any = {"profiles": application.profiles()}
        else:
            result = application.profile(args.reference)
        _emit(result, args.json)
        return 0
    if args.domain == "status":
        result = QraftApplication(ApplicationConfiguration(
            runs_root=args.runs_root,
        )).status()
        _emit(result, True) if args.json else print(_render_compact_status(result))
        return 0
    if args.domain == "resume":
        overrides = {
            "partition": args.partition,
            "nodes": args.nodes,
            "mpi_ranks": args.mpi_ranks,
            "cpus_per_rank": args.cpus_per_rank,
            "launcher": args.launcher,
            "executable": args.executable,
            "walltime_seconds": args.walltime_seconds,
        }
        application = (
            QraftApplication(ApplicationConfiguration(
                fdf=args.fdf, profile=args.profile, runs_root=args.runs_root,
            ))
            if args.fdf else QraftApplication.from_session(args.runs_root)
        )
        result = application.run(
            command_overrides=overrides, invocation=getattr(args, "_invocation", None),
            preflight_callback=(None if args.json else lambda value: print(render_preflight(value))),
        )
        _emit(result, args.json)
        if "technical_validation" in result:
            return 0 if result["technical_validation"] == "PASS" else 3
        return 0 if result["status"] == "REUSED_VALIDATED_ATTEMPT" or result["attempt"]["result"]["technical_validation"]["status"] == "PASS" else 3
    if args.domain == "validate":
        overrides = {
            "partition": args.partition,
            "nodes": args.nodes,
            "mpi_ranks": args.mpi_ranks,
            "cpus_per_rank": args.cpus_per_rank,
            "memory_mb": args.memory_mb,
            "launcher": args.launcher,
            "executable": args.executable,
            "executable_arguments": args.siesta_argument,
            "walltime_seconds": args.walltime_seconds,
            "launcher_command": args.launcher_command,
            "launcher_arguments": args.launcher_argument,
        }
        application = QraftApplication(ApplicationConfiguration(
            fdf=args.fdf, profile=args.profile,
            pseudo_manifest=args.pseudo_manifest,
            project_config=args.project_config, recipe=args.recipe,
        ))
        report = application.validate(command_overrides=overrides)
        _emit(report, True) if args.json else print(render_preflight(report))
        return 0 if report["status"] == "PASS" else 2
    if args.domain == "render":
        application = QraftApplication(ApplicationConfiguration(fdf=args.fdf))
        result = application.render(output_root=args.output)
        _emit(result, args.json)
        return 0
    if args.domain in {"plan", "_fdf-run"}:
        environment: dict[str, str] = {}
        for item in args.env:
            if "=" not in item or not item.split("=", 1)[0].strip():
                raise ValueError("--env must use NAME=VALUE")
            key, value = item.split("=", 1)
            environment[key.strip()] = value
        overrides = {
            "partition": args.partition,
            "nodes": args.nodes,
            "mpi_ranks": args.mpi_ranks,
            "cpus_per_rank": args.cpus_per_rank,
            "memory_mb": args.memory_mb,
            "launcher": args.launcher,
            "executable": args.executable,
            "executable_arguments": args.siesta_argument,
            "walltime_seconds": args.walltime_seconds,
            "launcher_command": args.launcher_command,
            "launcher_arguments": args.launcher_argument,
            "environment": environment or None,
        }
        application = QraftApplication(ApplicationConfiguration(
            fdf=args.fdf,
            profile=args.profile,
            pseudo_manifest=args.pseudo_manifest,
            project_config=args.project_config,
            recipe=args.recipe,
            runs_root=getattr(args, "runs_root", Path(".qraft-runs")),
        ))
        if args.domain == "plan":
            result = application.plan(command_overrides=overrides)
            if args.json:
                _emit(result, True)
            else:
                print(render_plan(result))
            return 0
        result = application.run(
            command_overrides=overrides,
            force_new_attempt=args.force_new_attempt,
            invocation=getattr(args, "_invocation", None),
            preflight_callback=(
                None if args.json else lambda value: print(render_preflight(value))
            ),
        )
        _emit(result, args.json)
        if "technical_validation" in result:
            return 0 if result["technical_validation"] == "PASS" else 3
        return 0 if result["status"] == "REUSED_VALIDATED_ATTEMPT" or result["attempt"]["result"]["technical_validation"]["status"] == "PASS" else 3
    if args.domain == "results":
        exporter = {"dos-pdos": DOSPDOSResultExporter, "bands": BandResultExporter, "optics": OpticalResultExporter}[args.action]()
        _emit(exporter.export(args.package, args.output, dry_run=args.dry_run), args.json)
        return 0
    if args.domain == "scientific":
        if args.action == "decide":
            _emit(create_decision(
                args.report, approval_id=args.approval_id, decision=args.decision,
                actor=args.actor, decided_at=args.decided_at, output=args.output,
            ), args.json)
        else:
            _emit(create_approved_profile(
                args.report, args.approval, profile_id=args.profile_id, output=args.output,
            ), args.json)
        return 0
    if args.domain == "environment":
        # Legacy spelling.  It intentionally delegates to the same installed
        # environment inspector as ``qraft env`` rather than preserving a
        # second public inspection contract.
        launcher = None if args.launcher == "auto" else args.launcher
        report = QraftApplication(ApplicationConfiguration(
            runs_root=args.working_directory / ".qraft-runs",
            overrides={
                "executable": args.siesta,
                **({"launcher": launcher} if launcher else {}),
            },
        )).environment()
        payload = report.to_dict()
        if args.json:
            # Preserve the historical envelope while deriving every probe from
            # the public inspector.  Existing automation can therefore migrate
            # without QRAFT maintaining a second inspection implementation.
            _emit({
                "status": "PASS" if payload["result"] == "READY" else "BLOCKED",
                "metadata": {"read_only": True, "job_submitted": False, "legacy": True},
                "environment": payload,
            }, True)
        else:
            print(render_environment(report))
        return 0 if payload["result"] == "READY" else 2
    if args.domain == "workflow":
        if args.action in {"recipes", "recipe", "create", "compose"}:
            service = WorkflowAuthoringService()
            if args.action == "recipes":
                _emit({"recipes": service.recipes()}, args.json)
                return 0
            if args.action == "recipe":
                _emit(service.recipe(args.recipe_id), args.json)
                return 0
            result = (
                service.compose_definition(args.intent, args.output, dry_run=args.dry_run)
                if args.action == "compose"
                else service.create_definition(args.intent, args.output, dry_run=args.dry_run)
            )
            _emit(result, args.json)
            return 0
        if args.action == "preflight":
            profile = (
                SiestaValidationProfile.load(args.profile)
                if args.profile
                else None
            )
            manifest = (
                PseudopotentialManifest.load(args.pseudo_manifest)
                if args.pseudo_manifest
                else None
            )
            report = WorkflowPreflightValidator().validate(
                args.definition,
                profile=profile,
                pseudopotential_manifest=manifest,
                require_pseudos=args.require_pseudos,
            )
            if args.json:
                _emit(report, True)
            else:
                print(
                    render_validation_report(
                        report,
                        title="WORKFLOW PREFLIGHT",
                    )
                )
            return (
                2
                if report.status.value in {"FAIL", "BLOCKED"}
                else 0
            )
        compilation = WorkflowCompiler().compile(args.definition)
        if not compilation.valid or compilation.compiled is None:
            _emit_workflow_validation(compilation, args.json)
            return 2
        if args.action == "validate":
            _emit_workflow_validation(compilation, args.json)
            return 0
        if args.action == "plan":
            _emit(
                workflow_plan(compilation.compiled)
                if args.json
                else render_workflow_plan(compilation.compiled),
                args.json,
            )
            return 0
        if args.action == "graph":
            if args.format == "json":
                print(
                    json.dumps(
                        workflow_graph(compilation.compiled),
                        sort_keys=True,
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                print(
                    render_workflow_graph(
                        compilation.compiled, output_format=args.format
                    )
                )
            return 0
        lock = compilation.lock_dict()
        if args.dry_run:
            _emit(
                {
                    "status": "DRY_RUN",
                    "output": str(args.output),
                    "content_sha256": lock["content_sha256"],
                    "filesystem_changes": 0,
                },
                args.json,
            )
            return 0
        digest = write_workflow_lock(
            compilation, args.output, overwrite=args.force
        )
        _emit(
            {
                "status": "WORKFLOW_COMPILED",
                "output": str(args.output.resolve()),
                "content_sha256": digest,
                "task_count": len(compilation.compiled.tasks),
                "execution_authorized": False,
            },
            args.json,
        )
        return 0
    if args.domain == "run":
        if args.action in {"resources", "placement"}:
            service = LiveSlurmPlacementService.discover()
            request = SlurmResourceRequest(
                nodes=(args.nodes if args.action == "placement" else None),
                cpus_per_task=args.cpus_per_task,
                walltime=args.walltime,
                account=args.account,
                qos=args.qos,
            )
            if args.action == "resources":
                _emit({
                    "status": "LIVE_SLURM_RESOURCES",
                    "observed_at": service.evidence.observed_at,
                    "authority": "STATIC_POLICY_COMPATIBILITY",
                    "current_queue_load_authority": False,
                    "partitions": service.show_resources(
                        resource_request=request
                    ),
                    "partition_selected": False,
                }, args.json)
                return 0
            selection = service.select(
                partition=args.partition,
                resource_request=request,
            )
            digest = write_live_selection_provenance(selection, args.output)
            _emit({
                "status": "LIVE_SLURM_PLACEMENT_SELECTED",
                "output": str(args.output.resolve()),
                "sha256": digest,
                "placement": selection.placement.to_dict(),
                "historical_snapshot_runtime_authority": False,
            }, args.json)
            return 0
        if args.action == "discover":
            snapshot = discover_snapshot(cluster_id=args.cluster_id)
            digest = write_snapshot(snapshot, args.output)
            _emit({"status": "SLURM_SNAPSHOT_CAPTURED", "output": str(args.output.resolve()), "sha256": digest, "snapshot": snapshot}, args.json)
            return 0
        if args.action == "snapshot-import":
            def read(path: Path | None) -> str:
                return path.read_text(encoding="utf-8") if path else ""
            snapshot = build_snapshot(
                cluster_id=args.cluster_id, observed_at=args.observed_at or utc_now(),
                sinfo=read(args.sinfo), scontrol_partitions=read(args.scontrol_partitions),
                scontrol_nodes=read(args.scontrol_nodes), sacctmgr=read(args.sacctmgr), sjstat=read(args.sjstat),
            )
            digest = write_snapshot(snapshot, args.output)
            _emit({"status": "SLURM_SNAPSHOT_IMPORTED", "output": str(args.output.resolve()), "sha256": digest, "snapshot": snapshot}, args.json)
            return 0
        if args.action == "candidates":
            # Loading the workflow proves this is attached to a canonical lock;
            # it does not add execution data to that scientific contract.
            from .workflows import load_workflow_lock
            load_workflow_lock(args.workflow)
            snapshot, _ = load_snapshot(args.snapshot)
            result = resolve_candidates(profile=SlurmExecutionProfile.load(args.profile), snapshot=snapshot)
            result["workflow_lock_path"] = str(args.workflow.resolve())
            result["snapshot_sha256"] = sha256_file(args.snapshot)
            result["runtime_authority_for_future_runs"] = False
            result["selection_requires_fresh_live_discovery"] = True
            _emit(result, args.json)
            return 0
        if args.action == "prepare":
            if args.snapshot is not None or args.candidate is not None:
                raise ValueError(
                    "historical Slurm snapshots are provenance only; "
                    "new execution selection requires live --partition discovery"
                )
            profile = SlurmExecutionProfile.load(args.profile)
            manual = (args.partition, args.nodes, args.ranks_per_node, args.account, args.qos, args.walltime)
            live_selection_requested = (
                args.partition is not None
                and args.snapshot is None
                and args.candidate is None
            )
            if args.candidate and any(item is not None for item in manual):
                raise ValueError("candidate selection and manual resource overrides are exclusive")
            if (
                not live_selection_requested
                and any(item is not None for item in manual)
                and not all(item is not None for item in manual)
            ):
                raise ValueError("manual selection requires partition, nodes, ranks-per-node, account, qos, and walltime")
            resolved_profile = None
            resolution = None
            live_provenance = None
            derived_placement = None
            if args.candidate:
                if args.snapshot is None:
                    raise ValueError("candidate selection requires --snapshot")
                if not args.confirm:
                    raise ValueError("candidate selection requires explicit --confirm")
                snapshot, _ = load_snapshot(args.snapshot)
                candidates = resolve_candidates(profile=profile, snapshot=snapshot, required_features=tuple(args.required_feature))
                chosen = next((item for item in candidates["candidates"] if item["candidate_id"] == args.candidate), None)
                if chosen is None or chosen["state"] == "INCOMPATIBLE":
                    raise ValueError("selected candidate is not compatible with the snapshot")
                resources = chosen["resources"]
                source_variant = chosen["source_variant"]
                pending_fields = list(chosen["review_codes"])
                if source_variant.get("accounts") is None:
                    pending_fields.append("ACCOUNT_AUTHORIZATION_UNKNOWN")
                if source_variant.get("qos") is None:
                    pending_fields.append("QOS_AUTHORIZATION_UNKNOWN")
                resolved_profile = profile.resolved(partition=chosen["partition"], account=profile.account, qos=profile.qos,
                                                    nodes=resources["nodes"], ranks_per_node=resources["ranks_per_node"], walltime=resources["walltime"])
                resolution = {"resolution_mode": "SNAPSHOT_CANDIDATE", "snapshot_schema_version": snapshot["schema_version"],
                              "snapshot_sha256": sha256_file(args.snapshot), "snapshot_observed_at": snapshot["observed_at"],
                              "candidate_id": chosen["candidate_id"], "selected_partition": chosen["partition"], "selected_account": profile.account,
                              "selected_qos": profile.qos, "selected_nodes": resources["nodes"], "selected_ranks_per_node": resources["ranks_per_node"],
                              "selected_total_ranks": resources["total_ranks"], "selected_walltime": resources["walltime"], "selected_features": resources["features"],
                              "selection_status": chosen["recommendation"], "selection_reason": chosen["ranking_reason"], "human_confirmed": True,
                              "resolution_timestamp": utc_now(), "pending_fields": sorted(set(pending_fields))}
            elif live_selection_requested:
                if not args.confirm:
                    raise ValueError("live partition selection requires explicit --confirm")
                if args.ranks_per_node is not None:
                    raise ValueError(
                        "live placement derives ranks-per-node; do not provide it"
                    )
                service = LiveSlurmPlacementService.discover()
                live_request = SlurmResourceRequest(
                    nodes=args.nodes,
                    cpus_per_task=args.cpus_per_task,
                    walltime=args.walltime or profile.walltime,
                    account=args.account or profile.account,
                    qos=args.qos or profile.qos,
                )
                selected = service.select(
                    partition=args.partition,
                    resource_request=live_request,
                )
                placement = selected.placement
                derived_placement = placement
                resolved_profile = profile.resolved(
                    partition=placement.partition,
                    account=str(live_request.account),
                    qos=str(live_request.qos),
                    nodes=placement.nodes,
                    ranks_per_node=placement.tasks_per_node,
                    walltime=placement.walltime,
                    cpus_per_task=placement.cpus_per_task,
                )
                live_provenance = selected.provenance()
                resolution = {
                    **live_provenance,
                    "resolution_mode": "LIVE_SLURM_HUMAN_SELECTION",
                    "human_confirmed": True,
                    "selected_partition": placement.partition,
                    "selected_account": live_request.account,
                    "selected_qos": live_request.qos,
                    "selected_nodes": placement.nodes,
                    "selected_ranks_per_node": placement.tasks_per_node,
                    "selected_total_ranks": placement.ntasks,
                    "selected_walltime": placement.walltime,
                    "selection_status": "HUMAN_SELECTION_SUPPORTED_BY_LIVE_EVIDENCE",
                    "pending_fields": [],
                }
            elif all(item is not None for item in manual):
                if not args.confirm:
                    raise ValueError("manual resource selection requires explicit --confirm")
                if args.snapshot is None or args.compatibility_evidence is None:
                    raise ValueError("manual compatibility selection requires --snapshot and --compatibility-evidence")
                snapshot, snapshot_sha = load_snapshot(args.snapshot)
                required_memory = memory_megabytes(profile.memory)
                required_walltime = walltime_seconds(args.walltime)
                compatible_variants = [
                    item for item in snapshot["partitions"]
                    if item["name"] == args.partition
                    and (item.get("min_nodes") is None or args.nodes >= int(item["min_nodes"]))
                    and (item.get("max_nodes") is None or args.nodes <= int(item["max_nodes"]))
                    and item.get("cpus_per_node") is not None and int(item["cpus_per_node"]) >= args.ranks_per_node
                    and set(args.required_feature).issubset(set(item.get("features") or ()))
                    and item.get("idle_nodes") is not None and int(item["idle_nodes"]) > 0
                    and (required_memory is None or item.get("memory_mb") is None or int(item["memory_mb"]) >= required_memory)
                    and (required_walltime is None or walltime_seconds(item.get("walltime")) is None or walltime_seconds(item.get("walltime")) >= required_walltime)
                    and (item.get("accounts") is None or args.account in item["accounts"])
                    and (item.get("qos") is None or args.qos in item["qos"])
                ]
                if not compatible_variants:
                    raise ValueError("manual selection is not supported by snapshot resource, authorization, or feature evidence")
                evidence = load_structured(args.compatibility_evidence)
                if evidence.get("schema_version") != "1.0" or not set(args.required_feature).issubset(set(evidence.get("compatible_features", []))):
                    raise ValueError("execution compatibility evidence does not support required features")
                if set(args.required_feature) & set(evidence.get("incompatible_features", [])):
                    raise ValueError("execution compatibility evidence marks required feature incompatible")
                resolved_profile = profile.resolved(partition=args.partition, account=args.account, qos=args.qos, nodes=args.nodes,
                                                    ranks_per_node=args.ranks_per_node, walltime=args.walltime)
                resolution = {"resolution_mode": "MANUAL_COMPATIBILITY_OVERRIDE", "snapshot_schema_version": snapshot["schema_version"], "snapshot_sha256": snapshot_sha,
                              "snapshot_observed_at": snapshot["observed_at"], "candidate_id": None, "selected_partition": args.partition, "selected_account": args.account,
                              "selected_qos": args.qos, "selected_nodes": args.nodes, "selected_ranks_per_node": args.ranks_per_node,
                              "selected_total_ranks": args.nodes * args.ranks_per_node, "selected_walltime": args.walltime, "selected_features": sorted(set(args.required_feature)),
                              "selection_status": "MANUAL_COMPATIBILITY_SELECTION_CONFIRMED", "selection_reason": "explicit human selection validated against snapshot and execution compatibility evidence", "human_confirmed": True,
                              "resolution_timestamp": utc_now(), "compatibility_evidence_sha256": sha256_file(args.compatibility_evidence), "task_placement_policy": "FULL_ALLOCATION_REMAP",
                              "pending_fields": []}
            result = RunPreparer(Path.cwd()).prepare(
                RunPreparationRequest(
                    workflow_lock=args.workflow_lock,
                    source_root=args.source_root,
                    execution_profile=args.profile,
                    output_root=args.output,
                    run_id=args.run_id,
                    dry_run=args.dry_run,
                    resolved_profile=resolved_profile,
                    execution_resolution=resolution,
                    cluster_snapshot=args.snapshot,
                    compatibility_evidence=args.compatibility_evidence,
                    live_slurm_provenance=live_provenance,
                    derived_placement=derived_placement,
                )
            )
            _emit(result, args.json)
            return 0
        inspector = RunInspector()
        if args.action == "inspect":
            _emit(inspector.inspect(args.package), args.json)
            return 0
        if args.action == "status":
            _emit(inspector.status(args.package), args.json)
            return 0
        plan = inspector.resume(
            args.package,
            previous_job_terminal=args.previous_job_terminal,
        )
        _emit(plan, args.json)
        return (
            2
            if plan.status
            in {
                "PREVIOUS_JOB_TERMINAL_CONFIRMATION_REQUIRED",
                "BLOCKED_REVIEW_REQUIRED",
            }
            else 0
        )
    if args.domain == "project":
        if args.action == "init":
            result = ProjectScaffolder().initialize(
                ProjectInitRequest(
                    root=args.path,
                    project_id=args.project_id,
                    title=args.title or args.project_id,
                    system_id=args.system_id,
                    fdf=args.fdf,
                    structure=args.structure,
                    pseudopotential_manifest=args.pseudo_manifest,
                    dry_run=args.dry_run,
                )
            )
            if args.json:
                _emit(result, True)
            else:
                print(render_project_init(result))
            return (
                2
                if result.decision.value in {"FAIL", "BLOCKED"}
                else 0
            )
        loader = ProjectPackageLoader()
        if args.action == "inspect":
            data = loader.inspect(args.path)
            _emit(data, args.json); return 0 if data["valid"] else 2
        validation = loader.validate(args.path)
        if args.action == "validate":
            _emit(primitive(validation), args.json); return 0 if validation.valid else 2
        package = loader.load(args.path)
        _emit({"project_id": package.project_id, "schema_version": package.schema_version, "systems": sorted(package.systems), "campaigns": sorted(package.campaigns), "status": "PROJECT_PACKAGE_LOADED"}, args.json)
        return 0
    if args.domain == "fdf":
        document = FDFParser().parse_path(args.path); data = _inspect_data(document); _emit(data, args.json)
        return 2 if any(item["severity"] == "ERROR" for item in data["diagnostics"]) else 0
    if args.domain == "input":
        if args.action == "rules":
            catalog = SiestaValidationCatalog.load_default()
            if catalog.engine_version != args.engine_version:
                raise ValueError(
                    f"no rules for SIESTA {args.engine_version}"
                )
            summary = catalog.public_summary()
            if args.json:
                _emit(summary, True)
            else:
                print(
                    f"SIESTA {catalog.engine_version} VALIDATION RULES "
                    f"({len(catalog.rules)})"
                )
                print(f"RULESET: {catalog.sha256}")
                for item in summary["rules"]:
                    print(
                        f"- {item['rule_id']}@{item['version']}: "
                        f"{item['summary']}"
                    )
                    print(f"  Evidence: {item['reference']}")
            return 0
        document = FDFParser().parse_path(args.path)
        initial = SiestaInputValidator().validate(document)
        pseudo_result = None
        if args.pseudo_manifest:
            manifest = PseudopotentialManifest.load(args.pseudo_manifest)
            pseudo_result = PseudopotentialVerifier().verify(
                manifest,
                initial.species,
            )
        profile = (
            SiestaValidationProfile.load(args.profile)
            if args.profile
            else None
        )
        catalog = SiestaValidationCatalog.load_default()
        if catalog.engine_version != args.engine_version:
            raise ValueError(
                f"no rules for SIESTA {args.engine_version}"
            )
        report = SiestaContextualValidator(
            catalog=catalog,
        ).validate(
            document,
            pseudo_result=pseudo_result,
            require_pseudos=args.require_pseudos,
            profile=profile,
            subject_id=initial.system_id or args.path.stem,
        )
        if args.json:
            _emit(report, True)
        else:
            print(render_validation_report(report, title="SIESTA INPUT"))
        return 2 if report.status.value in {"FAIL", "BLOCKED"} else 0
    if args.domain == "pseudo":
        manifest = PseudopotentialManifest.load(args.manifest)
        result = PseudopotentialVerifier().verify(manifest, tuple(args.species or [entry.species for entry in manifest.entries]))
        _emit(primitive(result), args.json); return 0 if result.status.value == "PASS" else 2
    if args.domain == "examples":
        service = ExampleService(ExampleRegistry((args.examples_root,)))
        if args.action == "list":
            data = [{"name": name, "path": str(path)} for name, path in service.registry.list()]; _emit(data, args.json); return 0
        if args.action == "inspect":
            _emit(service.inspect(args.example), args.json); return 0
        if args.action == "validate":
            result = service.validate(args.example); _emit(primitive(result), args.json); return 0 if result.valid else 2
        if args.action == "stage":
            result = service.stage(args.example, args.source, args.output, policy=args.policy, dry_run=args.dry_run)
            _emit(primitive(result), args.json); return 0 if result.status.value == "PASS" else 2
        if args.action == "package":
            _emit(service.package(args.example, args.output, dry_run=args.dry_run), args.json); return 0
        if args.action == "run":
            report = service.run(args.example, args.campaign_id, args.workspace / "examples" / args.example.replace("/", "_")); _emit(primitive(report), args.json)
            return 0 if report.decision == "PASS" else 2
        report = service.import_results(args.bundle, args.output, campaign_id=args.campaign_id, dry_run=args.dry_run)
        _emit(primitive(report), args.json); return 2 if report.status.value.endswith("INVALID") else 0
    if args.domain == "campaign":
        if args.action == "create":
            return _campaign_create(args)
        if args.action == "worker":
            campaign_path = args.campaign.resolve()
            root = (args.root or Path(os.environ.get("SLURM_SUBMIT_DIR", campaign_path.parent))).resolve()
            controller = CanonicalController.from_file(campaign_path, root=root)
            status = controller.run()
            _emit({
                "campaign_id": controller.config.campaign_id,
                "job_id": controller.slurm.job_id,
                "status": status.value,
                "summary": str(controller.summary_path),
                "login_node_persistent_process_required": False,
            }, args.json)
            return 0 if status is ExecutionStatus.COMPLETED else 2
        if args.action == "progress":
            snapshot = read_campaign_progress(args.path)
            _emit(
                snapshot if args.json else render_campaign_progress(snapshot),
                args.json,
            )
            return 0
        if args.action == "watch":
            if args.interval <= 0 or args.iterations < 0:
                raise ValueError("watch interval must be positive and iterations nonnegative")
            terminal = {
                ExecutionStatus.COMPLETED.value,
                ExecutionStatus.FAILED.value,
                ExecutionStatus.CANCELLED.value,
                ExecutionStatus.BLOCKED.value,
            }
            count = 0
            while True:
                snapshot = read_campaign_progress(args.path)
                if args.json:
                    print(json.dumps(snapshot, sort_keys=True, ensure_ascii=False))
                else:
                    if count:
                        print()
                    print(render_campaign_progress(snapshot))
                count += 1
                if (
                    snapshot["campaign_status"] in terminal
                    or (args.iterations and count >= args.iterations)
                ):
                    return 0
                time.sleep(args.interval)
        definition, campaign_dir = _load_definition(args.workspace, args.campaign)
        if args.action == "validate":
            validation = SiestaInputValidator().validate(FDFParser().parse_path(campaign_dir / "input.fdf"), require_pseudos=False)
            _emit({"campaign_id": definition.manifest.campaign_id, "status": validation.status.value, "findings": primitive(validation.findings)}, args.json)
            return 2 if validation.status.value in {"FAIL", "BLOCKED"} else 0
        if args.action == "status":
            state_path = args.workspace / "simulations" / "campaigns" / definition.manifest.campaign_id / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else None
            _emit({"campaign_id": definition.manifest.campaign_id, "campaign_status": definition.status, "simulation_state": state}, args.json); return 0
        if args.dry_run:
            _emit({"dry_run": True, "side_effects": 0, "campaign_id": definition.manifest.campaign_id, "tasks": [task.task_id for task in definition.manifest.tasks], "predicted_status": "PASS"}, args.json); return 0
        state, launcher, slurm = simulate_definition(definition, args.workspace / "simulations")
        _emit({"campaign_id": definition.manifest.campaign_id, "final_decision": state.final_decision.value if state.final_decision else None, "task_states": primitive(state.task_states), "allocations": slurm.submissions, "launches": len(launcher.launches), "real_evidence": False}, args.json)
        return 0 if state.final_decision and state.final_decision.value == "PASS" else 2
    if args.domain == "remote" and args.action == "package":
        definition, campaign_dir = _load_definition(args.workspace, args.campaign)
        output = args.output or (args.workspace / "remote_validation")
        project_root = Path(str(definition.metadata.get("project_root", "")))
        pseudo_path = project_root / "pseudopotentials" / "manifest.yaml"
        pseudo = PseudopotentialManifest.load(pseudo_path) if pseudo_path.is_file() else None
        plan = RemotePackager().package(definition, campaign_dir / "input.fdf", output, pseudopotentials=pseudo, dry_run=args.dry_run)
        _emit(primitive(plan), args.json); return 0
    if args.domain == "remote" and args.action == "m4-package":
        result = M4RemoteSmokePackager(Path.cwd()).build(args.profile, args.output)
        _emit(primitive(result), args.json)
        return 0
    if args.domain == "remote" and args.action == "controller-package":
        result = ControllerPackageBuilder(Path.cwd()).build(
            args.campaign, args.output, dry_run=args.dry_run
        )
        _emit(primitive(result), args.json)
        return 0
    if args.domain == "remote" and args.action == "results":
        output = args.output or (args.workspace / "imports" / args.bundle.name)
        report = RemoteResultImporter().import_bundle(args.bundle, output, expected_campaign_id=args.campaign_id, dry_run=args.dry_run)
        _emit(primitive(report), args.json); return 2 if report.status.value.endswith("INVALID") else 0
    if args.domain == "remote" and args.action == "environment":
        if args.environment_action == "package":
            output = args.output or (args.workspace / "remote_validation")
            manifest = PseudopotentialManifest.load(args.pseudo_manifest) if args.pseudo_manifest else None
            requirements = {item.filename: item.sha256 for item in manifest.entries if item.sha256} if manifest else {}
            status_data = load_structured(args.status_labels).get("status_labels", {}) if args.status_labels else None
            plan = EnvironmentProbePackager(requirements, status_data).package(output, dry_run=args.dry_run)
            _emit(primitive(plan), args.json); return 0
        output = args.output or (args.workspace / "environment_imports" / args.bundle.stem)
        report = RemoteEnvironmentImporter().import_bundle(
            args.bundle, output, dry_run=args.dry_run,
            canonical_profile_path=args.canonical_profile,
        )
        _emit(primitive(report), args.json); return 2 if report.status is RemoteEnvironmentStatus.REMOTE_ENVIRONMENT_FAILED else 0
    raise ValueError("unsupported command")


def _campaign_create(args: argparse.Namespace) -> int:
    package = ProjectPackageLoader().load(args.project)
    definition, variants = SiestaCampaignFactory().from_package(package, args.campaign_id)
    campaign_dir = args.workspace / "definitions" / definition.manifest.campaign_id
    if args.dry_run:
        _emit({"dry_run": True, "side_effects": 0, "campaign_id": definition.manifest.campaign_id, "planned_files": [str(campaign_dir / "definition.json"), str(campaign_dir / "input.fdf")], "predicted_status": definition.status}, args.json); return 0
    if campaign_dir.exists():
        raise FileExistsError(f"campaign definition already exists: {campaign_dir}")
    campaign_dir.mkdir(parents=True)
    (campaign_dir / "definition.json").write_text(json.dumps(_definition_data(definition), sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    source = package.root / package.system(package.campaign(args.campaign_id).system_id).input_template
    (campaign_dir / "input.fdf").write_bytes(source.read_bytes())
    if variants:
        variant_dir = campaign_dir / "variants"; variant_dir.mkdir()
        for index, variant in enumerate(variants, start=1):
            (variant_dir / f"variant_{index:03d}.fdf").write_text(variant.text, encoding="utf-8", newline="")
    _emit({"campaign_id": definition.manifest.campaign_id, "path": str(campaign_dir), "status": definition.status, "variants": len(variants), "real_execution_authorized": False}, args.json)
    return 0


def _definition_data(definition: CampaignDefinition) -> dict[str, Any]:
    return {"manifest": primitive(definition.manifest), "authorization": primitive(definition.authorization), "status": definition.status, "input_sha256": definition.input_sha256, "metadata": definition.metadata}


def _load_definition(workspace: Path, campaign: str) -> tuple[CampaignDefinition, Path]:
    campaign_dir = Path(campaign)
    if not campaign_dir.is_dir(): campaign_dir = workspace / "definitions" / campaign
    data = json.loads((campaign_dir / "definition.json").read_text(encoding="utf-8"))
    tasks = tuple(TaskSpec(item["task_id"], item["task_type"], item["target_id"], tuple(item["command"]), item["estimated_runtime_seconds"], item.get("metadata", {})) for item in data["manifest"]["tasks"])
    item = data["manifest"]
    manifest = CampaignManifest(item["campaign_id"], item["project_id"], tasks, item["created_at"], item["schema_version"])
    return CampaignDefinition(manifest, AuthorizationEnvelope(**data["authorization"]), data["status"], data["input_sha256"], data["metadata"]), campaign_dir


def _inspect_data(document) -> dict[str, Any]:
    return {"source": document.source, "sha256": document.original_sha256, "round_trip_exact": FDFParser().parse(document.render()).render() == document.render(), "newline_style": repr(document.newline_style), "scalars": [node.label for node in document.nodes if isinstance(node, FDFScalar)], "blocks": [node.name for node in document.nodes if isinstance(node, FDFBlock)], "includes": [node.target for node in document.nodes if isinstance(node, FDFInclude)], "unknown_lines": [node.span.start_line for node in document.nodes if isinstance(node, FDFUnknown)], "diagnostics": [primitive(item) for item in document.diagnostics]}


def _emit(data: Any, as_json: bool) -> None:
    payload = primitive(data)
    if as_json: print(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False))
    elif isinstance(payload, dict):
        for key, value in payload.items(): print(f"{key}: {value}")
    else: print(payload)


_CAMPAIGN_TEMPLATE = """# QRAFT CampaignSpec template
#
# Edit the FDF and pseudopotential manifest paths below. Runtime and placement
# stay outside this scientific campaign: use a profile or CLI options, e.g.
#   qraft validate campaign.yaml --profile local
#   qraft validate campaign.yaml --siesta /path/to/siesta
schema_version: "1.0"
campaign_id: my-siesta-campaign
engine: siesta
protocol: convergence
system:
  fdf: system.fdf
  pseudo_manifest: pseudos/manifest.yaml
parameters:
  mesh_cutoff:
    mode: scan
    values: [80, 100, 120]
    unit: Ry
  basis_size:
    mode: fixed
    value: DZP
criterion:
  metric: energy_per_atom
  delta: 0.01
  unit: eV
  consecutive: 1
# Set enabled to true and add type, steps, max_force, and unit to relax.
relaxation:
  enabled: false
"""


def _render_compact_status(data: Mapping[str, Any]) -> str:
    campaign = data.get("campaign")
    if not isinstance(campaign, dict):
        return "Campaign: NOT STARTED\nRun qraft run <campaign.yaml> to create a campaign state."
    points = campaign.get("points") if isinstance(campaign.get("points"), list) else []
    completed = sum(
        1 for point in points
        if isinstance(point, dict) and point.get("technical_status") == "PASS"
    )
    downstream = campaign.get("downstream")
    downstream = downstream if isinstance(downstream, dict) else None
    selected = downstream.get("selected_parameter") if downstream else None
    lines = [
        f"Campaign: {campaign.get('execution_state', 'UNKNOWN')}",
        f"Progress: {completed}/{len(points)} convergence points",
        f"Convergence: {campaign.get('scientific_decision', 'NOT_EVALUATED')}",
    ]
    if isinstance(selected, dict):
        name = str(selected.get("name", "selected value"))
        label = "MeshCutoff" if name == "mesh_cutoff" else name.replace("_", " ")
        value = selected.get("value")
        unit = selected.get("unit")
        lines.append(f"Selected {label}: {value}{f' {unit}' if unit else ''}")
    elif campaign.get("selected_point") is not None:
        lines.append(f"Selected point: {campaign['selected_point']}")
    if downstream:
        lines.append(f"Relaxation: {downstream.get('status', 'UNKNOWN')}")
    lines.append(f"Technical: {campaign.get('technical_validation', 'NOT_EVALUATED')}")
    lines.append(f"Scientific: {campaign.get('scientific_decision', 'NOT_EVALUATED')}")
    if campaign.get("execution_state") == "INTERRUPTED":
        lines.append("Resume available: yes")
    elif campaign.get("execution_state") == "FAILED":
        detail = downstream.get("technical_validation") if downstream else campaign.get("technical_validation")
        lines.append(f"Failure: {detail or 'see qraft status --json for details'}")
    return "\n".join(lines)


def _emit_workflow_validation(compilation, as_json: bool) -> None:
    report = primitive(compilation.report)
    data = {
        "valid": compilation.valid,
        "report": report,
        "workflow_lock_sha256": (
            compilation.lock_dict()["content_sha256"]
            if compilation.valid
            else None
        ),
        "execution_authorized": False,
    }
    if as_json:
        print(json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False))
        return
    print(
        f"WORKFLOW VALIDATION: {compilation.report.status.value}  "
        f"SUBJECT: {compilation.report.subject.subject_id}"
    )
    if not compilation.report.findings:
        print("No structural, graph, resource, or artifact errors detected.")
    for finding in compilation.report.findings:
        location = f" ({finding.location})" if finding.location else ""
        print(f"[{finding.status.value}] {finding.code}{location}")
        print(f"  {finding.message}")
        if finding.hint:
            print(f"  Suggested action: {finding.hint}")
    print("EXECUTION_AUTHORIZED: NO")


if __name__ == "__main__":
    raise SystemExit(main())
