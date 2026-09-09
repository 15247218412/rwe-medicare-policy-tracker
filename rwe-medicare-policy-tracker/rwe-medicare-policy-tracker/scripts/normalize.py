#!/usr/bin/env python3
"""Normalize CSV fields used by the policy tracker."""
from pathlib import Path
import csv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

ENUMS = {
    "status": {"新增", "更新", "持续推进", "已完成", "待核实", "无变化", ""},
    "confidence": {"high", "medium", "low", ""},
}

def clean(s: str) -> str:
    return " ".join((s or "").replace("\u3000", " ").split())

for name in ["master.csv", "latest.csv", "regions.csv", "documents.csv", "organizations.csv"]:
    path = DATA / name
    if not path.exists():
        continue
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = f.seek(0) or None
    if not rows:
        continue
    fieldnames = list(rows[0].keys())
    for row in rows:
        for k in fieldnames:
            row[k] = clean(row.get(k, ""))
        for k, allowed in ENUMS.items():
            if k in row and row[k] not in allowed:
                print(f"WARN {name}: unexpected {k}={row[k]!r}")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator='\n')
        w.writeheader(); w.writerows(rows)
print("Normalization complete.")
