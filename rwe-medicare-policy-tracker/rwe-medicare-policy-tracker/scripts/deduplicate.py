#!/usr/bin/env python3
"""Conservative deduplication for master.csv.
Keeps first record for exact duplicate source_url; warns on title/date duplicates.
"""
from pathlib import Path
import csv
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "data" / "master.csv"
with path.open("r", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f); rows = list(reader); fieldnames = reader.fieldnames

seen_url = set(); kept = []; removed = 0
for r in rows:
    u = (r.get("source_url") or "").strip()
    if u and u in seen_url:
        removed += 1
        continue
    if u: seen_url.add(u)
    kept.append(r)

similar = defaultdict(list)
for i, r in enumerate(kept):
    key = ((r.get("publish_date") or "").strip(), (r.get("province") or "").strip(),
           (r.get("organization") or "").strip(), (r.get("title") or "").strip())
    if all(key): similar[key].append(i)
for key, idxs in similar.items():
    if len(idxs) > 1:
        print("WARN possible duplicate:", key, "rows", idxs)

with path.open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
    w.writeheader(); w.writerows(kept)
print(f"Dedup complete. Removed exact URL duplicates: {removed}")
