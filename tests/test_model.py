"""Model rules (a small best-practice analyzer) and the contract between report and model."""
import filecmp
import re
from pathlib import Path

from recovery_bi import measures, pbir, tmdl
from recovery_bi.build import NAME, PLACEHOLDER_DATA, build

ROOT = Path(__file__).resolve().parents[1]


def _tmdl(project: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted((project / f"{NAME}.SemanticModel" / "definition").rglob("*.tmdl")))


def test_every_measure_has_format_folder_and_description():
    for m in measures.ALL_MEASURES:
        assert m.format and m.folder and len(m.description) > 20, m.name


def test_measures_are_explicit_only(project):
    text = _tmdl(project)
    assert "discourageImplicitMeasures" in text
    assert "summarizeBy: sum" not in text  # numbers aggregate only through measures


def test_money_is_aggregated_in_cents_then_divided(project):
    """No rounding before aggregation: money columns are integer cents, divided once inside the measure."""
    for m in measures.ALL_MEASURES:
        if m.format == measures.FMT_USD and "SUM (" in m.dax:
            assert re.search(r"DIVIDE \( SUM \( Findings\[\w+Cents\] \), 100 \)", m.dax), m.name


def test_relationships_are_single_direction_many_to_one(project):
    rel = (project / f"{NAME}.SemanticModel" / "definition" / "relationships.tmdl").read_text(encoding="utf-8")
    assert "crossFilteringBehavior: bothDirections" not in rel
    assert rel.count("relationship ") == len(tmdl.RELATIONSHIPS)
    for many_t, _, one_t, one_c in tmdl.RELATIONSHIPS:
        assert many_t == "Findings"
        assert tmdl.TABLES[[t.name for t in tmdl.TABLES].index(one_t)].columns[one_c].key


def test_keys_and_sort_columns_are_hidden_in_the_fact_table():
    fact = next(t for t in tmdl.TABLES if t.name == "Findings")
    for col in ["FindingKey", "VendorCode", "CategoryCode", "Status", "RecoverableCents", "ExpiredCents"]:
        assert fact.columns[col].hidden, col


def test_date_table_is_marked_and_contiguous(star):
    assert next(t for t in tmdl.TABLES if t.name == "Date").date_table
    d = star.date["Date"].astype("datetime64[ns]")
    assert d.is_monotonic_increasing and (d.diff().dropna().dt.days == 1).all()
    assert d.min().month == 1 and d.min().day == 1 and d.max().month == 12 and d.max().day == 31


def test_every_field_in_the_report_exists_in_the_model(star):
    tables = star.tables()
    for f in pbir.fields_used():
        if f.is_measure:
            assert f.name in measures.BY_NAME
        else:
            assert f.name in tables[f.table].columns, f.ref


def test_visuals_fit_on_their_page():
    for p in pbir.PAGES:
        boxes = [v.box for v in p.visuals]
        for x, y, w, h in boxes:
            assert x >= 0 and y >= 0 and x + w <= pbir.PAGE_W and y + h <= pbir.PAGE_H
        for i, a in enumerate(boxes):  # no two visuals overlap
            for b in boxes[i + 1:]:
                assert a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]


def test_committed_project_is_what_the_generator_produces(tmp_path, project):
    """The committed powerbi/ folder is generated output: rebuilding must not change a byte."""
    build(ROOT / "data", tmp_path, PLACEHOLDER_DATA)
    cmp = filecmp.dircmp(project, tmp_path, ignore=[".pbi"])

    def diffs(c):
        out = [*c.diff_files, *c.left_only, *c.right_only]
        for sub in c.subdirs.values():
            out += diffs(sub)
        return out

    assert diffs(cmp) == [], "run `recovery-bi build` and commit the result"
