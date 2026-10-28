"""Star schema exported from vendor-recovery-engine's findings.

One fact table (one row per decided deduction or payment) and four small dimensions. Money stays
in integer USD cents, exactly as the engine computed it; the semantic model divides by 100 only in
its measures, so no rounding happens before aggregation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

AS_OF = "2026-07-31"

CATEGORIES = [  # code, label, kind; order = how the report lists them
    ("UNPAID_INVOICE", "Unpaid invoice", "Payment"),
    ("SHORTAGE", "Shortage claim", "Deduction"),
    ("FX_VARIANCE", "Exchange-rate variance", "Payment"),
    ("CHARGEBACK_LATE_SHIPMENT", "Late-shipment chargeback", "Deduction"),
    ("PRICE_CLAIM", "Price claim", "Deduction"),
    ("UNDERPAYMENT", "Underpayment", "Payment"),
    ("CHARGEBACK_ASN", "ASN chargeback", "Deduction"),
    ("DUPLICATE_DEDUCTION", "Duplicate deduction", "Deduction"),
]

STATUSES = [  # code, label, outcome
    ("CLAIMABLE", "Claimable", "Recover"),
    ("EXPIRED", "Past the window", "Lost"),
    ("NEEDS_REVIEW", "Needs review", "Review"),
    ("INSUFFICIENT_EVIDENCE", "Insufficient evidence", "Review"),
    ("ALREADY_RECOVERED", "Already recovered", "Closed"),
    ("NOT_CLAIMABLE", "Valid deduction", "Closed"),
]

FACT_COLUMNS = {
    "FindingKey": "string", "VendorCode": "string", "CategoryCode": "string", "Status": "string",
    "RefType": "string", "Ref": "string", "EventDate": "date32[pyarrow]", "DisputeDeadline": "date32[pyarrow]",
    "DaysLeft": "Int64", "Currency": "string", "RecoverableCents": "int64", "ExpiredCents": "int64",
    "ExpectedValueCents": "int64", "WinRate": "float64", "Urgent": "bool", "PriorityRank": "Int64",
    "MatchTier": "string", "Reason": "string", "SourceFile": "string", "SourceRow": "Int64",
}


@dataclass
class Star:
    findings: pd.DataFrame
    vendor: pd.DataFrame
    category: pd.DataFrame
    status: pd.DataFrame
    date: pd.DataFrame

    def tables(self) -> dict[str, pd.DataFrame]:
        return {"Findings": self.findings, "Vendor": self.vendor, "Category": self.category,
                "Status": self.status, "Date": self.date}


def build(findings: pd.DataFrame, vendors: pd.DataFrame) -> Star:
    """`findings` is vendor-recovery-engine's out/findings.parquet; `vendors` its portfolio_by_vendor.csv."""
    f = findings
    fact = pd.DataFrame({
        "FindingKey": f["vendor_code"] + "|" + f["ref"],
        "VendorCode": f["vendor_code"], "CategoryCode": f["category"], "Status": f["status"],
        "RefType": f["ref_type"], "Ref": f["ref"],
        "EventDate": f["event_date"].dt.date, "DisputeDeadline": f["dispute_deadline"].dt.date,
        "DaysLeft": f["days_left"], "Currency": f["currency"],
        "RecoverableCents": f["recoverable_usd_cents"], "ExpiredCents": f["expired_usd_cents"],
        "ExpectedValueCents": f["expected_value_usd_cents"], "WinRate": f["win_rate"],
        "Urgent": f["urgent"].fillna(False), "PriorityRank": f["priority_rank"],
        "MatchTier": f["match_tier"].replace("", "none").fillna("none"), "Reason": f["reason"],
        "SourceFile": f["source_file"], "SourceRow": f["source_row"].round().astype("Int64"),
    }).astype(FACT_COLUMNS).sort_values("FindingKey", ignore_index=True)

    vendor = (vendors[["vendor_code", "vendor_name"]]
              .rename(columns={"vendor_code": "VendorCode", "vendor_name": "Vendor"})
              .astype("string").sort_values("VendorCode", ignore_index=True))
    category = pd.DataFrame(
        [(c, label, kind, i) for i, (c, label, kind) in enumerate(CATEGORIES, 1)],
        columns=["CategoryCode", "Category", "Kind", "CategoryOrder"],
    ).astype({"CategoryCode": "string", "Category": "string", "Kind": "string", "CategoryOrder": "int64"})
    status = pd.DataFrame(
        [(c, label, outcome, i) for i, (c, label, outcome) in enumerate(STATUSES, 1)],
        columns=["Status", "StatusLabel", "Outcome", "StatusOrder"],
    ).astype({"Status": "string", "StatusLabel": "string", "Outcome": "string", "StatusOrder": "int64"})

    days = pd.date_range(f"{f['event_date'].min().year}-01-01", f"{f['dispute_deadline'].max().year}-12-31")
    date = pd.DataFrame({
        "Date": days.date, "Year": days.year, "Quarter": "Q" + days.quarter.astype(str),
        "MonthNumber": days.month, "Month": days.strftime("%Y-%m"), "MonthIndex": days.year * 12 + days.month,
    }).astype({"Date": "date32[pyarrow]", "Year": "int64", "Quarter": "string", "MonthNumber": "int64",
               "Month": "string", "MonthIndex": "int64"})

    _check(fact, vendor, category, status, date)
    return Star(fact, vendor, category, status, date)


def _check(fact, vendor, category, status, date) -> None:
    """Referential integrity: every fact row lands on exactly one row of each dimension."""
    assert fact["FindingKey"].is_unique, "duplicate findings"
    for col, dim, key in [("VendorCode", vendor, "VendorCode"), ("CategoryCode", category, "CategoryCode"),
                          ("Status", status, "Status")]:
        assert dim[key].is_unique, f"duplicate {key} in dimension"
        missing = set(fact[col]) - set(dim[key])
        assert not missing, f"{col} values with no dimension row: {sorted(missing)[:5]}"
    assert set(fact["EventDate"]) <= set(date["Date"]), "event dates outside the date table"


def load_from_vre(vre_out: Path) -> Star:
    return build(pd.read_parquet(vre_out / "findings.parquet"), pd.read_csv(vre_out / "portfolio_by_vendor.csv"))


def write(star: Star, out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, df in star.tables().items():
        p = out / f"{name.lower()}.parquet"
        df.to_parquet(p, index=False, compression="zstd")
        paths[name] = p
    return paths


def read(folder: Path) -> Star:
    t = {name: pd.read_parquet(folder / f"{name.lower()}.parquet")
         for name in ["Findings", "Vendor", "Category", "Status", "Date"]}
    return Star(t["Findings"], t["Vendor"], t["Category"], t["Status"], t["Date"])
