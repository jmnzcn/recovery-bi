"""Every JSON file of the generated project validates against Microsoft's published schemas.

The schemas are vendored under tests/schemas (from github.com/microsoft/json-schemas, MIT). A
schema referenced but not vendored yet is downloaded once and saved there, so CI runs offline.
"""
import json
import urllib.request
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from referencing import Registry, Resource

from recovery_bi.build import NAME

SCHEMAS = Path(__file__).parent / "schemas"
PREFIX = "https://developer.microsoft.com/json-schemas/"
RAW = "https://raw.githubusercontent.com/microsoft/json-schemas/main/"


def _local(uri: str) -> Path:
    rel = uri.removeprefix(PREFIX).split("#")[0].replace("schema.embedded.json", "schema-embedded.json")
    return SCHEMAS / rel


def _retrieve(uri: str) -> Resource:
    path = _local(uri)
    if not path.exists():
        rel = path.relative_to(SCHEMAS).as_posix()
        for base in (RAW, PREFIX):
            try:
                text = urllib.request.urlopen(base + rel, timeout=20).read().decode()
                break
            except Exception:  # noqa: BLE001 - try the next mirror
                continue
        else:
            raise FileNotFoundError(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return Resource.from_contents(json.loads(path.read_text(encoding="utf-8")))


REGISTRY = Registry(retrieve=_retrieve)


def _files(project: Path) -> list[Path]:
    return sorted([*project.rglob("*.json"), *project.rglob("*.pbir"), *project.rglob("*.pbism"),
                   *project.rglob("*.pbip"), *project.rglob(".platform")])


def test_every_file_declares_a_schema(project):
    files = [f for f in _files(project) if "RegisteredResources" not in f.parts]
    assert len(files) > 20
    for f in files:
        assert json.loads(f.read_text(encoding="utf-8")).get("$schema", "").startswith(PREFIX), f


@pytest.mark.parametrize("rel", [p.relative_to(Path(__file__).resolve().parents[1] / "powerbi").as_posix()
                                 for p in _files(Path(__file__).resolve().parents[1] / "powerbi")
                                 if "RegisteredResources" not in p.parts])
def test_validates_against_published_schema(rel, project):
    doc = json.loads((project / rel).read_text(encoding="utf-8"))
    schema = _retrieve(doc["$schema"]).contents
    errors = sorted(Draft7Validator(schema, registry=REGISTRY).iter_errors(doc), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:5])


def test_report_points_at_the_model(project):
    pbir = json.loads((project / f"{NAME}.Report" / "definition.pbir").read_text(encoding="utf-8"))
    target = project / f"{NAME}.Report" / pbir["datasetReference"]["byPath"]["path"]
    assert (target / "definition.pbism").exists()
