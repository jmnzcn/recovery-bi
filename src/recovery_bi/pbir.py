"""Writes the report as PBIR: one JSON file per page and per visual, the format Power BI Desktop
reads from a .pbip project. Layout, fields and titles are declared in PAGES below; every field a
visual uses must exist in the semantic model (tests/test_report.py checks it).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from recovery_bi.measures import BY_NAME

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
NS = uuid.UUID("0b1c7e44-8f5d-4a3c-b2a6-5d3e9f7c1a22")

PAGE_W, PAGE_H = 1280, 720


@dataclass(frozen=True)
class Field:
    table: str
    name: str

    @property
    def is_measure(self) -> bool:
        return self.table == "Findings" and self.name in BY_NAME

    def expr(self) -> dict:
        kind = "Measure" if self.is_measure else "Column"
        return {kind: {"Expression": {"SourceRef": {"Entity": self.table}}, "Property": self.name}}

    @property
    def ref(self) -> str:
        return f"{self.table}.{self.name}"


def M(name: str) -> Field:  # noqa: N802 - reads like the DAX [Measure] it stands for
    return Field("Findings", name)


@dataclass
class Visual:
    key: str
    type: str
    roles: dict[str, list[Field]]
    box: tuple[int, int, int, int]  # x, y, w, h
    title: str | None = None
    sort: tuple[Field, str] | None = None  # field, "Ascending" | "Descending"
    objects: dict = field(default_factory=dict)


@dataclass
class Page:
    key: str
    title: str
    visuals: list[Visual]


def _lit(v) -> dict:
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, int | float):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}}


GAP, TOP = 16, 16


def _cards(measures: list[str], y: int = TOP, h: int = 110) -> list[Visual]:
    w = (PAGE_W - (len(measures) + 1) * GAP) // len(measures)
    def objects(m: str) -> dict:
        out = {"categoryLabels": [{"properties": {"show": _lit(False)}}]}  # the title already names it
        if BY_NAME[m].format == "#,0":  # counts in full (34,807, not 35K); money keeps auto units
            out["labels"] = [{"properties": {"labelDisplayUnits": _lit(1)}}]
        return out
    return [Visual(f"card_{i}", "card", {"Values": [M(m)]}, (GAP + i * (w + GAP), y, w, h), title=m,
                   objects=objects(m)) for i, m in enumerate(measures)]


PAGES = [
    Page("overview", "Overview", [
        *_cards(["Recoverable USD", "Claims", "Urgent USD", "Lost to Window USD", "Expected Value USD"]),
        Visual("by_category", "clusteredBarChart", {"Category": [Field("Category", "Category")],
                                                     "Y": [M("Recoverable USD")]},
               (GAP, 142, 620, 400), title="Recoverable now, by category",
               sort=(M("Recoverable USD"), "Descending")),
        Visual("running_total", "lineChart", {"Category": [Field("Date", "Month")],
                                              "Y": [M("Recoverable USD Running Total")]},
               (652, 142, 612, 400), title="Recoverable money, cumulative by deduction month",
               sort=(Field("Date", "Month"), "Ascending")),
        Visual("vendor_slicer", "slicer", {"Values": [Field("Vendor", "Vendor")]},
               (GAP, 558, 300, 146), title="Vendor"),
        Visual("status_slicer", "slicer", {"Values": [Field("Status", "StatusLabel")]},
               (332, 558, 300, 146), title="Decision"),
        Visual("ratios", "multiRowCard", {"Values": [M("Claim Rate"), M("Share Lost to Window"),
                                                     M("Avg Win Rate"), M("Needs Review")]},
               (652, 558, 612, 146), title="Rates"),
    ]),
    Page("vendors", "Vendors", [
        Visual("vendor_table", "tableEx", {"Values": [
            Field("Vendor", "Vendor"), M("Claims"), M("Recoverable USD"), M("Urgent USD"),
            M("Lost to Window USD"), M("Claim Rate"), M("Avg Win Rate")]},
            (GAP, TOP, 820, 688), title="Vendors by money recoverable now",
            sort=(M("Recoverable USD"), "Descending")),
        Visual("by_status", "donutChart", {"Category": [Field("Status", "StatusLabel")], "Y": [M("Total Findings")]},
               (852, TOP, 412, 400), title="What the engine decided"),
        Visual("category_slicer", "slicer", {"Values": [Field("Category", "Category")]},
               (852, 432, 412, 272), title="Category"),
    ]),
    Page("queue", "Work queue", [
        *_cards(["Urgent Claims", "Urgent USD", "Open Claim USD", "Needs Review"], h=100),
        Visual("queue_table", "tableEx", {"Values": [
            Field("Findings", "PriorityRank"), Field("Vendor", "Vendor"), Field("Findings", "Ref"),
            Field("Category", "Category"), M("Open Claim USD"), Field("Findings", "DisputeDeadline"),
            Field("Findings", "DaysLeft"), Field("Findings", "Reason"), Field("Findings", "SourceFile"),
            Field("Findings", "SourceRow")]},
            (GAP, 132, PAGE_W - 2 * GAP, 572), title="Claims to file, highest expected value first; each cites its source row",
            sort=(Field("Findings", "PriorityRank"), "Ascending")),
    ]),
]


def _name(*parts: str) -> str:
    return uuid.uuid5(NS, "/".join(parts)).hex[:20]


def visual_json(page: Page, v: Visual, z: int) -> dict:
    x, y, w, h = v.box
    query: dict = {"queryState": {role: {"projections": [
        {"field": f.expr(), "queryRef": f.ref, "nativeQueryRef": f.name} for f in fields]}
        for role, fields in v.roles.items()}}
    if v.sort:
        f, direction = v.sort
        query["sortDefinition"] = {"sort": [{"field": f.expr(), "direction": direction}], "isDefaultSort": False}
    visual: dict = {"visualType": v.type, "query": query, "drillFilterOtherVisuals": True}
    if v.objects:
        visual["objects"] = v.objects
    if v.title:
        visual["visualContainerObjects"] = {"title": [{"properties": {"show": _lit(True), "text": _lit(v.title)}}]}
    return {
        "$schema": f"{SCHEMA}/visualContainer/2.4.0/schema.json",
        "name": _name(page.key, v.key),
        "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z},
        "visual": visual,
    }


THEME = {
    "name": "Recovery",
    "dataColors": ["#2563EB", "#F97316", "#10B981", "#A855F7", "#EAB308", "#0EA5E9", "#EC4899", "#64748B"],
    "foreground": "#1F2937", "background": "#FFFFFF", "tableAccent": "#2563EB",
    "textClasses": {"title": {"fontFace": "Segoe UI Semibold", "fontSize": 12, "color": "#1F2937"},
                    "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 26, "color": "#111827"}},
}
THEME_FILE = "RecoveryTheme.json"


def write(folder: Path, model_folder_name: str) -> list[Path]:
    """Write <folder>/definition.pbir and <folder>/definition/**. Returns the files written."""
    d = folder / "definition"
    files: dict[Path, dict] = {}
    files[folder / "definition.pbir"] = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{model_folder_name}"}}}
    files[d / "version.json"] = {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"}
    files[d / "report.json"] = {
        "$schema": f"{SCHEMA}/report/3.0.0/schema.json",
        "themeCollection": {"customTheme": {
            "name": THEME_FILE, "type": "RegisteredResources",
            "reportVersionAtImport": {"visual": "2.4.0", "report": "3.0.0", "page": "2.0.0"}}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                              "items": [{"name": THEME_FILE, "path": THEME_FILE, "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized"},
    }
    files[d / "pages" / "pages.json"] = {"$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json",
                                         "pageOrder": [_name(p.key) for p in PAGES],
                                         "activePageName": _name(PAGES[0].key)}
    for p in PAGES:
        pd_ = d / "pages" / _name(p.key)
        files[pd_ / "page.json"] = {"$schema": f"{SCHEMA}/page/2.0.0/schema.json", "name": _name(p.key),
                                    "displayName": p.title, "displayOption": "FitToPage",
                                    "height": PAGE_H, "width": PAGE_W}
        for z, v in enumerate(p.visuals):
            files[pd_ / "visuals" / _name(p.key, v.key) / "visual.json"] = visual_json(p, v, z)
    files[folder / "StaticResources" / "RegisteredResources" / THEME_FILE] = THEME
    for path, obj in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8", newline="\n")
    return list(files)


def fields_used() -> set[Field]:
    out = set()
    for p in PAGES:
        for v in p.visuals:
            out |= {f for fs in v.roles.values() for f in fs}
            if v.sort:
                out.add(v.sort[0])
    return out
