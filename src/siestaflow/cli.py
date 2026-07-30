"""Project-agnostic, local-only SIESTA preparation and simulation CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .engines.siesta.fdf_parser import FDFParser
from .engines.siesta.input_validator import SiestaInputValidator
from .engines.siesta.models import FDFBlock, FDFInclude, FDFScalar, FDFUnknown
from .engines.siesta.pseudopotentials import PseudopotentialManifest, PseudopotentialVerifier
from .examples import ExampleRegistry, ExampleService
from .models import AuthorizationEnvelope, CampaignManifest, TaskSpec, primitive
from .project_packages import ProjectPackageLoader, load_structured
from .remote import RemotePackager, RemoteResultImporter
from .remote_environment import EnvironmentProbePackager, RemoteEnvironmentImporter, RemoteEnvironmentStatus
from .siesta_campaigns import CampaignDefinition, SiestaCampaignFactory, simulate_definition
from .execution.allocation_controller import AllocationController, ExecutionStatus
from .execution.campaign_progress import read_campaign_progress, render_campaign_progress
from .m4_remote_package import M4RemoteSmokePackager
from .controller_package import ControllerPackageBuilder
from .workflows import (
    WorkflowCompiler,
    render_workflow_graph,
    render_workflow_plan,
    workflow_graph,
    workflow_plan,
    write_workflow_lock,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="siestaflow", description="SIESTA preparation, allocation-local execution, and evidence handling")
    parser.add_argument("--workspace", type=Path, default=Path(".siestaflow-work"))
    parser.add_argument("--examples-root", type=Path, default=_repo_root() / "examples")
    sub = parser.add_subparsers(dest="domain", required=True)

    project = sub.add_parser("project")
    project_sub = project.add_subparsers(dest="action", required=True)
    for action in ("inspect", "validate", "load"):
        command = project_sub.add_parser(action)
        command.add_argument("path", type=Path)
        command.add_argument("--json", action="store_true")

    fdf = sub.add_parser("fdf")
    fdf_sub = fdf.add_subparsers(dest="action", required=True)
    fdf_inspect = fdf_sub.add_parser("inspect")
    fdf_inspect.add_argument("path", type=Path)
    fdf_inspect.add_argument("--json", action="store_true")

    inp = sub.add_parser("input")
    inp_sub = inp.add_subparsers(dest="action", required=True)
    inp_validate = inp_sub.add_parser("validate")
    inp_validate.add_argument("path", type=Path)
    inp_validate.add_argument("--json", action="store_true")

    pseudo = sub.add_parser("pseudo")
    pseudo_sub = pseudo.add_subparsers(dest="action", required=True)
    pseudo_verify = pseudo_sub.add_parser("verify")
    pseudo_verify.add_argument("manifest", type=Path)
    pseudo_verify.add_argument("--species", nargs="*")
    pseudo_verify.add_argument("--json", action="store_true")

    campaign = sub.add_parser("campaign")
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

    workflow = sub.add_parser(
        "workflow", help="validate and compile scientific workflow DAGs"
    )
    workflow_sub = workflow.add_subparsers(dest="action", required=True)
    workflow_validate = workflow_sub.add_parser(
        "validate", help="validate schema, artifacts, and graph consistency"
    )
    workflow_validate.add_argument("definition", type=Path)
    workflow_validate.add_argument("--json", action="store_true")
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

    examples = sub.add_parser("examples")
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

    remote = sub.add_parser("remote")
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
    env_import.add_argument("--dry-run", action="store_true"); env_import.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except (OSError, ValueError, PermissionError, RuntimeError, KeyError) as exc:
        print(f"SIESTAFLOW_ERROR: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.domain == "workflow":
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
    if args.domain == "project":
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
        result = SiestaInputValidator().validate(FDFParser().parse_path(args.path)); _emit(primitive(result), args.json)
        return 2 if result.status.value in {"FAIL", "BLOCKED"} else 0
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
            controller = AllocationController.from_file(campaign_path, root=root)
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
        result = M4RemoteSmokePackager(_repo_root()).build(args.profile, args.output)
        _emit(primitive(result), args.json)
        return 0
    if args.domain == "remote" and args.action == "controller-package":
        result = ControllerPackageBuilder(_repo_root()).build(
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
            output = args.output or (_repo_root() / "remote_validation")
            manifest = PseudopotentialManifest.load(args.pseudo_manifest) if args.pseudo_manifest else None
            requirements = {item.filename: item.sha256 for item in manifest.entries if item.sha256} if manifest else {}
            status_data = load_structured(args.status_labels).get("status_labels", {}) if args.status_labels else None
            plan = EnvironmentProbePackager(requirements, status_data).package(output, dry_run=args.dry_run)
            _emit(primitive(plan), args.json); return 0
        output = args.output or (args.workspace / "environment_imports" / args.bundle.stem)
        profile_path = _repo_root() / "config" / "cluster_profiles" / "yoltla_siesta.yaml"
        report = RemoteEnvironmentImporter().import_bundle(args.bundle, output, dry_run=args.dry_run, canonical_profile_path=profile_path)
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
