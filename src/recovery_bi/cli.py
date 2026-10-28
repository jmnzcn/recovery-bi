"""recovery-bi: export the star schema, generate the Power BI project, check DAX parity."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="recovery-bi")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="build data/*.parquet from vendor-recovery-engine's out/ folder")
    e.add_argument("vre_out", type=Path)
    b = sub.add_parser("build", help="generate the .pbip project")
    b.add_argument("--local", action="store_true",
                   help="write to out/powerbi with this checkout's data path, ready to open in Power BI Desktop")
    sub.add_parser("queries", help="write parity/queries.json: the DAX queries the DaxRunner evaluates")
    c = sub.add_parser("parity", help="compare DaxRunner results with the pandas reference")
    c.add_argument("results", type=Path, nargs="?", default=ROOT / "parity" / "dax_results.json")
    a = p.parse_args(argv)

    if a.cmd == "export":
        from recovery_bi import data
        paths = data.write(data.load_from_vre(a.vre_out), ROOT / "data")
        for name, path in paths.items():
            print(f"{name:10s} {path.relative_to(ROOT)}  {path.stat().st_size / 1e6:.1f} MB")
    elif a.cmd == "build":
        from recovery_bi.build import PLACEHOLDER_DATA, build
        out = ROOT / ("out/powerbi" if a.local else "powerbi")
        data_path = str(ROOT / "data") if a.local else PLACEHOLDER_DATA
        files = build(ROOT / "data", out, data_path)
        print(f"{len(files)} files in {out.relative_to(ROOT)}  (DataFolder = {data_path})")
    elif a.cmd == "queries":
        from recovery_bi import parity
        path = ROOT / "parity" / "queries.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(parity.queries(), indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"{len(parity.queries())} queries -> {path.relative_to(ROOT)}")
    elif a.cmd == "parity":
        from recovery_bi import data, parity
        report = parity.compare(data.read(ROOT / "data"), json.loads(a.results.read_text(encoding="utf-8")))
        print(parity.render(report))
        return 0 if report["mismatches"] == 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
