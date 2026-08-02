"""Read-only export of hash-verified SIESTA EPSIMG spectra."""
from __future__ import annotations
import csv, hashlib, json, math
from pathlib import Path
from typing import Any, Mapping
from .execution.allocation_controller import ExecutionStatus, load_controller_config
from .execution.campaign_progress import read_campaign_progress
from .run_inspection import RunInspector
from .workflows import load_run_lock, load_workflow_lock

def _sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()

def parse_epsimg(path: Path) -> tuple[tuple[float, float], ...]:
    rows=[]; previous=None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line=raw.strip()
        if not line or line.startswith(("#", "!")): continue
        fields=line.replace("D","E").replace("d","e").split()
        if len(fields)!=2: raise ValueError(f"EPSIMG row {number} must have energy and epsilon_2")
        try: energy, epsilon=map(float, fields)
        except ValueError as exc: raise ValueError(f"invalid EPSIMG numeric row {number}") from exc
        if not math.isfinite(energy) or not math.isfinite(epsilon) or (previous is not None and energy<=previous): raise ValueError(f"invalid EPSIMG energy ordering at row {number}")
        previous=energy; rows.append((energy,epsilon))
    if not rows: raise ValueError("EPSIMG contains no spectrum rows")
    return tuple(rows)

class OpticalResultExporter:
    def export(self, package: Path, output: Path, *, dry_run: bool=False) -> dict[str, Any]:
        inspection=RunInspector().inspect(package); root=Path(inspection.package_path)
        if inspection.campaign_status != ExecutionStatus.COMPLETED.value: raise ValueError("optical export requires a completed campaign")
        config=load_controller_config(root/"campaign.yaml")
        tasks=[task for task in config.tasks if any(str(x).lower().endswith(".epsimg") for x in task.required_artifacts)]
        if len(tasks)!=1: raise ValueError("package must declare exactly one required EPSIMG artifact")
        task=tasks[0]; item=next(x for x in read_campaign_progress(root)["tasks"] if x["task_id"]==task.task_id); attempt_id=item.get("last_attempt")
        if item["status"]!=ExecutionStatus.COMPLETED.value or not isinstance(attempt_id,str): raise ValueError("optical task has no completed attempt")
        attempt=root/"work"/task.task_id/attempt_id; result=json.loads((attempt/"result_manifest.json").read_text(encoding="utf-8"))
        name=next(str(x) for x in task.required_artifacts if str(x).lower().endswith(".epsimg")); source=attempt/name
        if result.get("exit_code")!=0 or result.get("normal_termination") is not True or result.get("scf_converged") is not True or result.get("artifacts",{}).get(name)!=_sha(source): raise ValueError("EPSIMG result or hash verification failed")
        rows=parse_epsimg(source); target=output.resolve()
        if target.exists(): raise FileExistsError(f"result export destination already exists: {target}")
        response={"status":"OPTICAL_RESULT_EXPORT_READY" if dry_run else "OPTICAL_RESULT_EXPORTED","output":str(target),"files":["epsimg.csv","optical_export.json"],"rows":len(rows),"scientific_interpretation":"NOT_PERFORMED"}
        if dry_run:return response
        target.mkdir(parents=True); table=target/"epsimg.csv"
        with table.open("w",encoding="utf-8",newline="") as h:
            writer=csv.writer(h,lineterminator="\n"); writer.writerow(("energy_eV","epsilon_2")); writer.writerows(rows)
        workflow,_=load_workflow_lock(root/"workflow.lock.json"); run_lock,run=load_run_lock(root/"run.lock.json")
        manifest={"schema_version":"1.0","classification":"HASH_BOUND_OPTICAL_RESULT_EXPORT","scientific_interpretation":"NOT_PERFORMED","source":{"run_id":inspection.run_id,"workflow_id":inspection.workflow_id,"task_id":task.task_id,"attempt_id":attempt_id,"workflow_lock_sha256":workflow.content_sha256,"run_lock_sha256":run_lock.content_sha256,"source_artifact":source.relative_to(root).as_posix(),"source_sha256":_sha(source)},"spectrum":{"table":"epsimg.csv","table_sha256":_sha(table),"rows":len(rows),"columns":["energy_eV","epsilon_2"]}}
        out=target/"optical_export.json"; out.write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n",encoding="utf-8",newline="\n")
        response.update(table_sha256=_sha(table),manifest_sha256=_sha(out)); return response
