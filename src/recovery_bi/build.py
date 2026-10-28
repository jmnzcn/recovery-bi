"""Assembles the .pbip project: semantic model (TMDL) + report (PBIR) + the item metadata files."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from recovery_bi import data, pbir, tmdl

NAME = "RecoveryBI"
PLACEHOLDER_DATA = "C:\\recovery-bi\\data"


def _platform(kind: str, display: str, logical: str) -> dict:
    return {"$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": kind, "displayName": display},
            "config": {"version": "2.0", "logicalId": logical}}


def build(data_dir: Path, out: Path, data_path_in_model: str) -> list[Path]:
    """Generate the project under `out`, removing anything generated there before."""
    star = data.read(data_dir)
    model_dir, report_dir = out / f"{NAME}.SemanticModel", out / f"{NAME}.Report"
    for d in (model_dir, report_dir):
        if d.exists():
            shutil.rmtree(d)
    files = tmdl.write(star.tables(), model_dir, data_path_in_model)
    files += pbir.write(report_dir, model_dir.name)
    meta = {
        out / f"{NAME}.pbip": {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
            "version": "1.0", "artifacts": [{"report": {"path": report_dir.name}}],
            "settings": {"enableAutoRecovery": True}},
        model_dir / ".platform": _platform("SemanticModel", NAME, tmdl.tag("item", "model")),
        report_dir / ".platform": _platform("Report", NAME, tmdl.tag("item", "report")),
    }
    for path, obj in meta.items():
        path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8", newline="\n")
    return files + list(meta)
