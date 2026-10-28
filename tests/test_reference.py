"""The pandas reference reproduces vendor-recovery-engine's own totals, and its BLANK semantics follow DAX."""
import json
from pathlib import Path

import pandas as pd

from recovery_bi import measures, parity

ROOT = Path(__file__).resolve().parents[1]


def test_totals_match_the_engine_summary(star):
    """data/vre_summary.json is the engine's summary.json for the run the data was exported from."""
    s = json.loads((ROOT / "data" / "vre_summary.json").read_text(encoding="utf-8"))
    f, m = star.findings, measures.BY_NAME
    assert m["Total Findings"].reference(f) == s["findings"]
    assert m["Claims"].reference(f) == s["claims"]
    assert m["Recoverable USD"].reference(f) == s["recoverable_usd"]
    assert m["Lost to Window USD"].reference(f) == s["expired_usd"]
    assert m["Expected Value USD"].reference(f) == s["expected_value_usd"]
    assert m["Urgent Claims"].reference(f) == s["urgent_claims"]
    assert m["Urgent USD"].reference(f) == s["urgent_usd"]
    for status, n in s["by_status"].items():
        assert (f["Status"] == status).sum() == n
    for c in s["by_category"]:
        g = f[f["CategoryCode"] == c["category"]]
        assert m["Recoverable USD"].reference(g) == c["recoverable_usd"]


def test_reference_returns_blank_like_dax(star):
    empty = star.findings.iloc[0:0]
    for m in measures.MEASURES:
        assert m.reference(empty) is None, m.name
    no_claims = star.findings[star.findings["Status"] == "NOT_CLAIMABLE"]
    assert measures.BY_NAME["Claims"].reference(no_claims) is None      # COUNTROWS of nothing is BLANK
    assert measures.BY_NAME["Claim Rate"].reference(no_claims) == 0.0   # but the rate is 0 %, not BLANK


def test_running_total_ends_at_the_grand_total(star):
    months = parity.reference(star)["by_month"]
    assert months[-1]["Recoverable USD Running Total"] == measures.BY_NAME["Recoverable USD"].reference(star.findings)
    values = [r["Recoverable USD Running Total"] for r in months]
    assert values == sorted(values)


def test_running_total_reference_matches_a_plain_cumsum(star):
    f = star.findings.assign(Month=pd.to_datetime(star.findings["EventDate"]).dt.strftime("%Y-%m"))
    cum = (f.groupby("Month")["RecoverableCents"].sum().cumsum() / 100).to_dict()
    for r in parity.reference(star)["by_month"]:
        if r["Month"] in cum:
            assert r["Recoverable USD Running Total"] == cum[r["Month"]]
