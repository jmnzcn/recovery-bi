"""The measures, each written twice: once in DAX for the semantic model, once in pandas as the
reference the DAX is checked against.

The two are written independently on purpose. The pandas side works on the exported star schema;
the DAX side is evaluated by Power BI's own engine (tools/DaxRunner). They must agree to the cent
on every slice in parity.SLICES.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

Ref = Callable[[pd.DataFrame], float | int | None]


@dataclass(frozen=True)
class Measure:
    name: str
    dax: str
    format: str
    folder: str
    description: str
    reference: Ref


def _usd(col: str, where: Callable[[pd.DataFrame], pd.Series] | None = None) -> Ref:
    def f(df: pd.DataFrame):
        d = df if where is None else df[where(df)]
        return None if d.empty else int(d[col].sum()) / 100
    return f


def _count(where: Callable[[pd.DataFrame], pd.Series] | None = None) -> Ref:
    def f(df: pd.DataFrame):
        n = len(df) if where is None else int(where(df).sum())
        return n or None  # DAX returns BLANK, not 0, when no row qualifies
    return f


def _ratio(num: Ref, den: Ref) -> Ref:
    def f(df: pd.DataFrame):
        n, d = num(df), den(df)
        return None if not d else (n or 0) / d
    return f


def _claimable(df: pd.DataFrame) -> pd.Series:
    return df["Status"] == "CLAIMABLE"


def _lost_share(df: pd.DataFrame):
    rec, exp = int(df["RecoverableCents"].sum()), int(df["ExpiredCents"].sum())
    return None if rec + exp == 0 else exp / (rec + exp)


def _avg_win_rate(df: pd.DataFrame):
    d = df.loc[_claimable(df), "WinRate"]
    return None if d.empty else float(d.mean())


def _vendors_with_claims(df: pd.DataFrame):
    return df.loc[_claimable(df), "VendorCode"].nunique() or None


FMT_USD = '\\$#,0.00;(\\$#,0.00);\\$#,0.00'
FMT_INT = "#,0"
FMT_PCT = "0.0%"

MEASURES: list[Measure] = [
    Measure("Total Findings", "COUNTROWS ( Findings )", FMT_INT, "Volume",
            "Deductions and payments the engine decided, whatever the outcome.", _count()),
    Measure("Claims", 'CALCULATE ( COUNTROWS ( Findings ), Findings[Status] = "CLAIMABLE" )', FMT_INT, "Volume",
            "Findings that can be disputed now, with evidence.", _count(_claimable)),
    Measure("Recoverable USD", "DIVIDE ( SUM ( Findings[RecoverableCents] ), 100 )", FMT_USD, "Money",
            "Money that can be claimed back now, in USD at the engine's exchange rates.", _usd("RecoverableCents")),
    Measure("Lost to Window USD", "DIVIDE ( SUM ( Findings[ExpiredCents] ), 100 )", FMT_USD, "Money",
            "Money that was recoverable but whose dispute window has closed.", _usd("ExpiredCents")),
    Measure("Expected Value USD", "DIVIDE ( SUM ( Findings[ExpectedValueCents] ), 100 )", FMT_USD, "Money",
            "Recoverable money weighted by each category's historical win rate.", _usd("ExpectedValueCents")),
    Measure("Urgent Claims", "CALCULATE ( [Claims], Findings[Urgent] = TRUE () )", FMT_INT, "Urgency",
            "Claims whose dispute window closes within 30 days of the as-of date.",
            _count(lambda d: _claimable(d) & d["Urgent"])),
    Measure("Urgent USD", "CALCULATE ( [Recoverable USD], Findings[Urgent] = TRUE () )", FMT_USD, "Urgency",
            "Recoverable money in claims that must be filed within 30 days.",
            _usd("RecoverableCents", lambda d: d["Urgent"])),
    # "+ 0": [Claims] is BLANK where nothing is claimable, and DIVIDE(BLANK, n) is BLANK, not 0 %.
    # The parity check caught that on slices with findings but no claims.
    Measure("Claim Rate", "DIVIDE ( [Claims] + 0, [Total Findings] )", FMT_PCT, "Ratios",
            "Share of findings that turned out to be claimable.", _ratio(_count(_claimable), _count())),
    Measure("Share Lost to Window",
            "VAR Recoverable = SUM ( Findings[RecoverableCents] )\n"
            "VAR Expired = SUM ( Findings[ExpiredCents] )\n"
            "RETURN DIVIDE ( Expired, Recoverable + Expired )", FMT_PCT, "Ratios",
            "Of all money that was ever recoverable, the share lost to missed deadlines.", _lost_share),
    Measure("Avg Win Rate", 'CALCULATE ( AVERAGE ( Findings[WinRate] ), Findings[Status] = "CLAIMABLE" )', FMT_PCT,
            "Ratios", "Average historical win rate of the open claims.", _avg_win_rate),
    Measure("Needs Review", 'CALCULATE ( COUNTROWS ( Findings ), Findings[Status] = "NEEDS_REVIEW" )', FMT_INT,
            "Volume", "Ambiguous references a person has to decide.",
            _count(lambda d: d["Status"] == "NEEDS_REVIEW")),
    Measure("Vendors with Claims",
            'CALCULATE ( DISTINCTCOUNT ( Findings[VendorCode] ), Findings[Status] = "CLAIMABLE" )', FMT_INT,
            "Volume", "Vendors with at least one open claim.", _vendors_with_claims),
    Measure("Open Claim USD", 'CALCULATE ( [Recoverable USD], Findings[Status] = "CLAIMABLE" )', FMT_USD, "Money",
            "Recoverable money restricted to claimable rows; blank elsewhere, so work-queue tables hide the rest.",
            _usd("RecoverableCents", _claimable)),
]

# Cumulative recoverable money by event date: needs the date context, so its reference lives in parity.
RUNNING_TOTAL = Measure(
    "Recoverable USD Running Total",
    "VAR LastDay = MAX ( 'Date'[Date] )\n"
    "VAR LastEvent = CALCULATE ( MAX ( Findings[EventDate] ), ALL ( Findings ) )\n"
    "RETURN\n"
    "    IF (\n"
    "        MIN ( 'Date'[Date] ) <= LastEvent,\n"
    "        CALCULATE ( [Recoverable USD], 'Date'[Date] <= LastDay, ALL ( 'Date' ) )\n"
    "    )",
    FMT_USD, "Money",
    "Recoverable money from deductions dated up to the end of the period; blank after the last deduction.",
    lambda df: None,
)

ALL_MEASURES = [*MEASURES, RUNNING_TOTAL]
BY_NAME = {m.name: m for m in ALL_MEASURES}
