"""Regenerate benchmarks/summary.csv from the SUMMARY.md master table.

SUMMARY.md is the source of truth (one markdown row per campaign); this script
keeps the CSV a faithful, Excel-sortable export of the same table so the two
never diverge again. Run it after adding a row to SUMMARY.md:

    python benchmarks/scripts/build_summary_csv.py
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parents[1]
SUMMARY_MD = BENCH_DIR / "SUMMARY.md"
SUMMARY_CSV = BENCH_DIR / "summary.csv"

HEADER = [
    "number", "date", "campaign", "models", "prompt", "dataset_n",
    "focus", "tp_recall", "fp_rate", "cost", "decision", "artifacts",
]

ROW_RE = re.compile(r"^\|\s*(\d{2}[a-z0-9-]*)\s*\|")
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")


def strip_md(cell: str, keep_link_target: bool = False) -> str:
    """Flatten a markdown table cell to plain text for the CSV."""
    if keep_link_target:
        cell = LINK_RE.sub(lambda m: m.group(2), cell)
    else:
        cell = LINK_RE.sub(lambda m: m.group(1), cell)
    cell = cell.replace("**", "").replace("`", "")
    return " ".join(cell.split())


def main() -> None:
    rows = []
    for line in SUMMARY_MD.read_text(encoding="utf-8").splitlines():
        if not ROW_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) != len(HEADER):
            raise SystemExit(
                f"Row {cells[0] if cells else '?'} has {len(cells)} cells, "
                f"expected {len(HEADER)} — fix SUMMARY.md before regenerating."
            )
        rows.append(
            [strip_md(c, keep_link_target=(i == len(cells) - 1)) for i, c in enumerate(cells)]
        )

    # utf-8-sig so Excel on Windows opens the accents correctly
    with SUMMARY_CSV.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {SUMMARY_CSV}")


if __name__ == "__main__":
    main()
