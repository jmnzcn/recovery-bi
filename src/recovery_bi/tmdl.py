"""Writes the semantic model as TMDL, the text format Power BI Desktop reads from a .pbip project.

Everything is derived from the exported tables (column names and types) and from measures.py, so
the model cannot drift from the data or from the reference implementation. Lineage tags are
deterministic (uuid5 of the object's path), so rebuilding produces byte-identical files.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from recovery_bi.measures import ALL_MEASURES, Measure

NS = uuid.UUID("7d3f0a52-2c1e-4f0e-9a51-1f6c2a9e8b10")


def tag(*path: str) -> str:
    return str(uuid.uuid5(NS, "/".join(path)))


def q(name: str) -> str:
    """Quote a TMDL object name when it is not a plain identifier."""
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


@dataclass
class ColumnSpec:
    hidden: bool = False
    key: bool = False
    sort_by: str | None = None
    fmt: str | None = None
    summarize: str = "none"


@dataclass
class TableSpec:
    name: str
    file: str
    description: str
    columns: dict[str, ColumnSpec] = field(default_factory=dict)
    date_table: bool = False
    measures: list[Measure] = field(default_factory=list)


TABLES = [
    TableSpec("Findings", "findings.parquet",
              "One row per deduction or payment the engine decided, with its verdict and the source row that proves it.",
              {"FindingKey": ColumnSpec(hidden=True), "VendorCode": ColumnSpec(hidden=True),
               "CategoryCode": ColumnSpec(hidden=True), "Status": ColumnSpec(hidden=True),
               "RecoverableCents": ColumnSpec(hidden=True), "ExpiredCents": ColumnSpec(hidden=True),
               "ExpectedValueCents": ColumnSpec(hidden=True), "WinRate": ColumnSpec(hidden=True, fmt="0%"),
               "EventDate": ColumnSpec(fmt="yyyy-mm-dd"), "DisputeDeadline": ColumnSpec(fmt="yyyy-mm-dd"),
               "DaysLeft": ColumnSpec(fmt="#,0"), "PriorityRank": ColumnSpec(fmt="#,0"),
               "SourceRow": ColumnSpec(fmt="0")},
              measures=ALL_MEASURES),
    TableSpec("Vendor", "vendor.parquet", "The 170 vendors in the synthetic world.",
              {"VendorCode": ColumnSpec(key=True)}),
    TableSpec("Category", "category.parquet", "Deduction and payment categories, in report order.",
              {"CategoryCode": ColumnSpec(key=True, hidden=True), "Category": ColumnSpec(sort_by="CategoryOrder"),
               "CategoryOrder": ColumnSpec(hidden=True)}),
    TableSpec("Status", "status.parquet", "What the engine decided for a finding.",
              {"Status": ColumnSpec(key=True, hidden=True), "StatusLabel": ColumnSpec(sort_by="StatusOrder"),
               "StatusOrder": ColumnSpec(hidden=True)}),
    TableSpec("Date", "date.parquet", "Calendar for event dates; marked as the model's date table.",
              {"Date": ColumnSpec(key=True, fmt="yyyy-mm-dd"), "Month": ColumnSpec(sort_by="MonthIndex"),
               "MonthIndex": ColumnSpec(hidden=True), "MonthNumber": ColumnSpec(hidden=True)},
              date_table=True),
]

RELATIONSHIPS = [  # many-side column, one-side column; all single-direction, many-to-one
    ("Findings", "VendorCode", "Vendor", "VendorCode"),
    ("Findings", "CategoryCode", "Category", "CategoryCode"),
    ("Findings", "Status", "Status", "Status"),
    ("Findings", "EventDate", "Date", "Date"),
]

DATA_TYPES = {"string": "string", "int64": "int64", "Int64": "int64", "float64": "double", "bool": "boolean",
              "date32[day][pyarrow]": "dateTime"}
M_TYPES = {"string": "type text", "int64": "Int64.Type", "double": "type number", "boolean": "type logical",
           "dateTime": "type date"}


def _data_type(s: pd.Series) -> str:
    return DATA_TYPES[str(s.dtype)]


def _description(text: str, indent: str) -> list[str]:
    return [f"{indent}/// {text}"]


def _expr_lines(expr: str, indent: str) -> list[str]:
    return [indent + line for line in expr.splitlines()]


def table_tmdl(spec: TableSpec, df: pd.DataFrame) -> str:
    out = [*_description(spec.description, ""), f"table {q(spec.name)}", f"\tlineageTag: {tag(spec.name)}"]
    if spec.date_table:
        out.append("\tdataCategory: Time")
    out.append("")
    for m in spec.measures:
        out += _description(m.description, "\t")
        if "\n" in m.dax:
            out += [f"\tmeasure {q(m.name)} =", *_expr_lines(m.dax, "\t\t\t")]
        else:
            out.append(f"\tmeasure {q(m.name)} = {m.dax}")
        out += [f"\t\tformatString: {m.format}", f"\t\tdisplayFolder: {m.folder}",
                f"\t\tlineageTag: {tag(spec.name, 'measure', m.name)}", ""]
    for col in df.columns:
        c = spec.columns.get(col, ColumnSpec())
        dt = _data_type(df[col])
        out.append(f"\tcolumn {q(col)}")
        out.append(f"\t\tdataType: {dt}")
        if c.fmt:
            out.append(f"\t\tformatString: {c.fmt}")
        if c.hidden:
            out.append("\t\tisHidden")
        if c.key:
            out.append("\t\tisKey")
        out.append(f"\t\tlineageTag: {tag(spec.name, 'column', col)}")
        out.append(f"\t\tsummarizeBy: {c.summarize}")
        out.append(f"\t\tsourceColumn: {col}")
        if c.sort_by:
            out.append(f"\t\tsortByColumn: {q(c.sort_by)}")
        out += ["", "\t\tannotation SummarizationSetBy = User", ""]
    types = ", ".join(f'{{"{col}", {M_TYPES[_data_type(df[col])]}}}' for col in df.columns)
    out += [
        f"\tpartition {q(spec.name)} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f'\t\t\t\t    Source = Parquet.Document(File.Contents(DataFolder & "\\{spec.file}")),',
        f"\t\t\t\t    Typed = Table.TransformColumnTypes(Source, {{{types}}})",
        "\t\t\t\tin",
        "\t\t\t\t    Typed",
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(out)


def write(tables: dict[str, pd.DataFrame], folder: Path, data_folder: str) -> list[Path]:
    """Write <folder>/definition/*.tmdl and definition.pbism. Returns the files written."""
    d = folder / "definition"
    (d / "tables").mkdir(parents=True, exist_ok=True)
    files: dict[Path, str] = {}
    files[d / "database.tmdl"] = "database\n\tcompatibilityLevel: 1600\n"
    order = ", ".join(f'"{n}"' for n in ["DataFolder", *(t.name for t in TABLES)])
    files[d / "model.tmdl"] = "\n".join([
        "model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures", "\tsourceQueryCulture: en-US", "",
        f"annotation PBI_QueryOrder = [{order}]", "",
        *(f"ref table {q(t.name)}" for t in TABLES), "",
    ])
    files[d / "expressions.tmdl"] = "\n".join([
        "/// Folder holding the exported parquet tables. Rebuild with `recovery-bi build` to point it at your checkout.",
        f'expression DataFolder = "{data_folder}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]',
        f"\tlineageTag: {tag('expression', 'DataFolder')}", "", "\tannotation PBI_ResultType = Text", "",
    ])
    rels = []
    for many_t, many_c, one_t, one_c in RELATIONSHIPS:
        rels += [f"relationship {tag('rel', many_t, many_c, one_t, one_c)}",
                 f"\tfromColumn: {q(many_t)}.{q(many_c)}", f"\ttoColumn: {q(one_t)}.{q(one_c)}", ""]
    files[d / "relationships.tmdl"] = "\n".join(rels)
    for spec in TABLES:
        files[d / "tables" / f"{spec.name}.tmdl"] = table_tmdl(spec, tables[spec.name])
    files[folder / "definition.pbism"] = _json({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {}})
    for path, text in files.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    return list(files)


def _json(obj) -> str:
    import json
    return json.dumps(obj, indent=2) + "\n"
