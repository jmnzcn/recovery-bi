"""DAX parity: the measures evaluated by Power BI's engine against the pandas reference.

queries() lists DAX queries over several slices (totals, by category, status, vendor, vendor x
category, month). tools/DaxRunner runs them inside Power BI Desktop and writes the rows to
parity/dax_results.json. compare() recomputes every cell with measures.py and reports any cell
that differs: money by more than half a cent, counts at all, ratios by more than 1e-9.
"""
from __future__ import annotations

import math

import pandas as pd

from recovery_bi.data import Star
from recovery_bi.measures import BY_NAME, MEASURES, RUNNING_TOTAL

SLICES = {  # id: grouping columns as (table, column)
    "totals": [],
    "by_category": [("Category", "CategoryCode")],
    "by_status": [("Status", "Status")],
    "by_vendor": [("Vendor", "VendorCode")],
    "by_vendor_category": [("Vendor", "VendorCode"), ("Category", "CategoryCode")],
}
FACT_KEY = {"CategoryCode": "CategoryCode", "Status": "Status", "VendorCode": "VendorCode"}


def _dax_name(table: str, column: str) -> str:
    return f"'{table}'[{column}]"


def queries() -> list[dict]:
    out = []
    pairs = ", ".join(f'"{m.name}", [{m.name}]' for m in MEASURES)
    for sid, cols in SLICES.items():
        if cols:
            group = ", ".join(_dax_name(t, c) for t, c in cols)
            dax = f"EVALUATE SUMMARIZECOLUMNS ( {group}, {pairs} )"
        else:
            dax = f"EVALUATE ROW ( {pairs} )"
        out.append({"id": sid, "dax": dax})
    out.append({"id": "by_month", "dax": (
        "EVALUATE SUMMARIZECOLUMNS ( 'Date'[Month], "
        f'"Recoverable USD", [Recoverable USD], "{RUNNING_TOTAL.name}", [{RUNNING_TOTAL.name}] )')})
    return out


def _clean(key: str) -> str:
    """ADOMD returns 'Table[Column]' for group columns and '[Measure]' for measures."""
    return key[key.index("[") + 1:-1] if "[" in key else key


def reference(star: Star) -> dict[str, list[dict]]:
    f = star.findings
    out: dict[str, list[dict]] = {}
    for sid, cols in SLICES.items():
        keys = [FACT_KEY[c] for _, c in cols]
        groups = [((), f)] if not keys else f.groupby(keys, sort=True)
        rows = []
        for k, g in groups:
            k = k if isinstance(k, tuple) else (k,)
            row = {c: v for (_, c), v in zip(cols, k, strict=True)}
            row |= {m.name: m.reference(g) for m in MEASURES}
            rows.append(row)
        out[sid] = rows
    # Running total by event month, over every month of the date table.
    month = pd.Series(pd.to_datetime(f["EventDate"]).dt.strftime("%Y-%m"))
    by_month = f.assign(Month=month.values).groupby("Month")["RecoverableCents"].agg(["sum", "size"])
    last_event = pd.to_datetime(f["EventDate"]).max().strftime("%Y-%m")
    rows, cum_cents, cum_rows = [], 0, 0
    for m in sorted(star.date["Month"].unique()):
        s, n = (int(by_month.at[m, "sum"]), int(by_month.at[m, "size"])) if m in by_month.index else (0, 0)
        cum_cents, cum_rows = cum_cents + s, cum_rows + n
        monthly = s / 100 if n else None
        running = cum_cents / 100 if cum_rows and m <= last_event else None
        if monthly is not None or running is not None:
            rows.append({"Month": m, "Recoverable USD": monthly, RUNNING_TOTAL.name: running})
    out["by_month"] = rows
    return out


def _close(name: str, a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    m = BY_NAME[name]
    if m.format.startswith("\\$"):
        return abs(float(a) - float(b)) < 0.005
    if m.format == "#,0":
        return int(a) == int(b)
    return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)


def compare(star: Star, dax: dict) -> dict:
    ref = reference(star)
    report = {"engine": dax.get("engine"), "generated_utc": dax.get("generated_utc"),
              "slices": {}, "cells": 0, "mismatches": 0, "examples": []}
    for sid, ref_rows in ref.items():
        got_rows = [{_clean(k): v for k, v in r.items()} for r in dax["queries"].get(sid, [])]
        group_cols = [c for c in (ref_rows[0] if ref_rows else {}) if c not in BY_NAME]
        index = {tuple(r.get(c) for c in group_cols): r for r in got_rows}
        cells = bad = 0
        if len(got_rows) != len(ref_rows):
            bad += 1
            report["examples"].append(f"{sid}: {len(got_rows)} rows from DAX, {len(ref_rows)} expected")
        for r in ref_rows:
            key = tuple(r[c] for c in group_cols)
            g = index.get(key)
            for name in (c for c in r if c in BY_NAME):
                cells += 1
                if g is None or not _close(name, r[name], g.get(name)):
                    bad += 1
                    if len(report["examples"]) < 10:
                        report["examples"].append(f"{sid} {key} {name}: DAX {None if g is None else g.get(name)}"
                                                  f" vs reference {r[name]}")
        report["slices"][sid] = {"rows": len(ref_rows), "cells": cells, "mismatches": bad}
        report["cells"] += cells
        report["mismatches"] += bad
    return report


def render(report: dict) -> str:
    lines = [f"engine: {report['engine']}  ({report['generated_utc']})"]
    for sid, s in report["slices"].items():
        lines.append(f"  {sid:20s} {s['rows']:5d} rows  {s['cells']:6d} cells  {s['mismatches']} mismatches")
    lines.append(f"total: {report['cells']} cells compared, {report['mismatches']} mismatches")
    lines += [f"  ! {e}" for e in report["examples"]]
    return "\n".join(lines)
