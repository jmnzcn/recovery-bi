# Design notes

## 1. Why generate a Power BI project at all

A .pbix file is a binary: it cannot be reviewed in a pull request, diffed, or rebuilt. Since the
Power BI Project format (.pbip), the same report is a folder of text files:

| Part | Format | Here |
|---|---|---|
| Semantic model: tables, columns, relationships, measures, Power Query | **TMDL** (text) | written by `tmdl.py` |
| Report: pages, visuals, fields, sort, titles, theme | **PBIR** (one JSON file per page and per visual) | written by `pbir.py` |
| Item metadata | small JSON files with published schemas | written by `build.py` |

Once those files are generated, a report becomes a build artifact like any other: deterministic,
reviewed as a diff, validated in CI, and regenerated when the data or a measure changes.

## 2. One definition, two implementations

Every measure in `measures.py` is written twice: in DAX for the model, and in pandas as a
reference. They are written independently, and the reference is itself checked against
vendor-recovery-engine's own totals (`tests/test_reference.py`). The DAX is then evaluated by
Power BI Desktop's engine (`tools/DaxRunner`, through ADOMD.NET) on six slices and compared cell
by cell: 17,885 cells, money to the half-cent, counts exactly, ratios to 1e-9.

The first run found 56 mismatches out of 17,917 cells, all in `Claim Rate`: where a slice had findings but no claims,
`[Claims]` is BLANK and `DIVIDE(BLANK, n)` is BLANK too, so the report would have shown an empty
cell where the answer is 0 %. The fix (`[Claims] + 0`) is in the measure, with the reason.

## 3. What runs where

| Check | Where | Needs Power BI |
|---|---|---|
| Every JSON file validates against Microsoft's published schemas | CI (pytest) | no |
| TMDL parses and the model validates in Microsoft's Tabular Object Model | CI (.NET, Linux) | no |
| Model rules: explicit measures only, money aggregated in cents, single-direction many-to-one relationships, hidden keys, marked date table | CI (pytest) | no |
| Every field a visual uses exists; visuals fit the page without overlapping | CI (pytest) | no |
| The committed project is exactly what the generator produces | CI (pytest) | no |
| DAX parity on 17,885 cells | `scripts/verify.ps1` on Windows; the recorded results are re-checked in CI | yes, to record |

The DAX engine only ships with Power BI (Desktop, the service, or Analysis Services), so parity is
recorded locally and the results are committed. CI recomputes the reference and compares, so a
change to the data, a measure or the reference that was not re-verified in Power BI fails the
build.

## 4. Choices

- **Money in integer cents** until the measure divides once by 100: no rounding before aggregation,
  and the parity check can demand agreement to the cent.
- **Star schema**: one fact table, four dimensions, many-to-one single-direction relationships.
  The work-queue table uses `Open Claim USD`, which is BLANK outside claimable rows, so the table
  shows only claims without a visual-level filter.
- **Deterministic output**: lineage tags and file names are UUIDv5 of the object's path, so a
  rebuild is byte-identical and the diff of a change shows only that change.
- **Data path as a parameter** (`DataFolder`): the committed project points at a placeholder;
  `recovery-bi build --local` writes a copy pointing at the checkout, ready to open.

## 5. Limits

- The visual layout is declared in code and checked for bounds and overlap, but how it looks is
  only checked by opening it (`scripts/screenshots.ps1`).
- Parity needs Power BI Desktop on Windows; on other systems the recorded results are checked.
- The data is synthetic (vendor-recovery-engine's generated world), so the numbers say nothing
  about any real vendor.
