#!/usr/bin/env python3
"""Generate a basic Markdown report from data/latest.csv."""
from pathlib import Path
import csv
from datetime import date
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
latest = ROOT / "data" / "latest.csv"
reports = ROOT / "reports"; reports.mkdir(exist_ok=True)
with latest.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

counts = Counter(r.get("status", "") for r in rows)
today = date.today().isoformat()
out = reports / f"{today}.md"
lines = [
    "# 全国真实世界医保综合价值评价增量监测", "",
    f"**监测日期：{today}**", "",
    "## 一、本期概览", "",
    f"- 新增：{counts.get('新增',0)} 条",
    f"- 更新：{counts.get('更新',0)} 条",
    f"- 持续推进：{counts.get('持续推进',0)} 条",
    f"- 待核实：{counts.get('待核实',0)} 条", "",
    "## 二、本期新增/更新明细", "",
    "| 发布日期 | 地区 | 发布单位 | 类型 | 当前阶段 | 主要变化 | 官方链接 |", 
    "|---|---|---|---|---|---|---|"
]
for r in rows:
    region = "/".join(x for x in [r.get("province",""), r.get("city","")] if x)
    vals = [r.get("publish_date",""), region, r.get("organization",""), r.get("category",""),
            r.get("stage",""), r.get("change_summary",""), r.get("source_url","")]
    vals = [str(v).replace("|","/").replace("\n"," ") for v in vals]
    lines.append("| " + " | ".join(vals) + " |")
lines += ["", "## 三、重点地区进展", "", "（由 Codex 补充）", "",
          "## 四、全国趋势观察", "", "（仅基于已收集证据归纳）", "",
          "## 五、待核实事项", "", "（由 Codex 补充）", ""]
out.write_text("\n".join(lines), encoding="utf-8")
print(out)
