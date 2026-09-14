"""Safe campaign/task/attempt workspace materialization."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import AlreadyExistsError, IntegrityError
from .filesystem import FileSystem, safe_join, validate_identifier
from .models import AuthorizationEnvelope, CampaignManifest, WorkspaceRecord, primitive


class WorkspaceManager:
    """Own deterministic paths and preserve every prior task attempt."""

    def __init__(self, project_root: Path, filesystem: FileSystem) -> None:
        self.root = project_root.resolve()
        self.fs = filesystem
        self.campaigns_root = self.root / "campaigns"

    def campaign_path(self, campaign_id: str) -> Path:
        return safe_join(self.campaigns_root, validate_identifier(campaign_id))

    def prepare_campaign(
        self,
        manifest: CampaignManifest,
        authorization: AuthorizationEnvelope,
    ) -> Path:
        validate_identifier(manifest.campaign_id, field_name="campaign_id")
        path = self.campaign_path(manifest.campaign_id)
        if self.fs.exists(path):
            try:
                stored_manifest = json.loads(self.fs.read_text(path / "campaign.json"))
                stored_authorization = json.loads(self.fs.read_text(path / "authorization.json"))
            except (OSError, json.JSONDecodeError) as exc:
                raise IntegrityError(f"existing campaign is incomplete: {path}") from exc
            if stored_manifest != primitive(manifest):
                raise IntegrityError("campaign id already belongs to another manifest")
            if stored_authorization != primitive(authorization):
                raise IntegrityError("campaign authorization is immutable")
            return path
        self.fs.mkdir(path, parents=True, exist_ok=False)
        self.fs.mkdir(path / "tasks", exist_ok=False)
        self.fs.atomic_write_json(path / "campaign.json", primitive(manifest))
        self.fs.atomic_write_json(path / "authorization.json", primitive(authorization))
        return path

    def next_attempt(self, campaign_id: str, task_id: str) -> WorkspaceRecord:
        validate_identifier(task_id, field_name="task_id")
        campaign = self.campaign_path(campaign_id)
        tasks = safe_join(campaign, "tasks")
        task_path = safe_join(tasks, task_id)
        if not self.fs.exists(task_path):
            self.fs.mkdir(task_path, parents=True, exist_ok=False)
        attempts = []
        for child in self.fs.list_dir(task_path):
            match = re.fullmatch(r"attempt_(\d{3})", child.name)
            if match:
                attempts.append(int(match.group(1)))
        number = max(attempts, default=0) + 1
        attempt_id = f"attempt_{number:03d}"
        attempt_path = safe_join(task_path, attempt_id)
        if self.fs.exists(attempt_path):
            raise AlreadyExistsError(f"attempt collision: {attempt_path}")
        self.fs.mkdir(attempt_path, exist_ok=False)
        record = WorkspaceRecord(campaign_id, task_id, attempt_id, str(attempt_path))
        self.fs.atomic_write_json(attempt_path / "workspace.json", primitive(record))
        return record
