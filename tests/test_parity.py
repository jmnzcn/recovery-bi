"""The DAX results recorded from Power BI Desktop agree with the reference on every cell.

parity/dax_results.json is produced by scripts/verify.ps1 (Power BI Desktop's own engine). This
test recomputes the reference and compares, so a change to the data, a measure or the reference
that is not re-verified in Power BI fails CI.
"""
import json
from pathlib import Path

from recovery_bi import parity

ROOT = Path(__file__).resolve().parents[1]


def test_queries_file_is_current():
    committed = json.loads((ROOT / "parity" / "queries.json").read_text(encoding="utf-8"))
    assert committed == parity.queries(), "run `recovery-bi queries` and re-verify in Power BI"


def test_power_bi_agrees_with_the_reference_on_every_cell(star):
    dax = json.loads((ROOT / "parity" / "dax_results.json").read_text(encoding="utf-8"))
    report = parity.compare(star, dax)
    assert report["cells"] > 15_000
    assert report["mismatches"] == 0, parity.render(report)
