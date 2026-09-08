#!/usr/bin/env python3
"""Generate a basic Markdown report from data/latest.csv."""
from pathlib import Path
import csv
from datetime import datetime, timedelta, timezone
import os, json
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
latest = ROOT / "data" / "latest.csv"
reports = ROOT / "reports"; reports.mkdir(exist_ok=True)
with latest.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

counts = Counter(r.get("status", "") for r in rows)
today = os.environ.get('MONITOR_DATE') or datetime.now(timezone(timedelta(hours=8))).date().isoformat()
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
    "| 发布日期 | 地区 | 发布单位 | 标题 | 类型 | 当前阶段 | 主要变化 | 官方链接 |",
    "|---|---|---|---|---|---|---|---|"
]
for r in rows:
    region = "/".join(x for x in [r.get("province",""), r.get("city","")] if x)
    vals = [r.get("publish_date",""), region, r.get("organization",""), r.get("title",""), r.get("category",""),
            r.get("stage",""), r.get("change_summary",""), r.get("source_url","")]
    vals = [str(v).replace("|","/").replace("\n"," ") for v in vals]
    lines.append("| " + " | ".join(vals) + " |")

regions = sorted({r.get("province", "") for r in rows if r.get("province")})
pending = [r for r in rows if r.get("status") == "待核实" or r.get("confidence") == "low"]
lines += ["", "## 三、重点地区进展", "", "、".join(regions) or "本期未记录地区变化。", "",
          "## 四、全国趋势观察", "", "本报告仅列数据库中的事件变化；条数不代表全国实际活动规模，不据此推断全国趋势。", "",
          "## 五、待核实事项", ""]
lines += [f"- {r['title']}：{r['source_url']}" for r in pending] or ["本期无新增待核实线索。"]
lines += ["", "## 六、本期无重大变化说明", "",
          "本期检索范围内未识别新增或实质更新；不等于全国没有变化。" if not rows else "本期记录的变化见明细表。", "",
          "## 七、检索范围与限制", ""]
coverage_path = ROOT / "data/collection.json"
coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else {}
lines.append(coverage.get("limitations", "本期使用导入数据，未执行全国联网检索。"))
for site in coverage.get("fixed_sites", []):
    if not site.get("ok"):
        lines.append("- 官网访问缺口：" + site.get("url", ""))
for batch in coverage.get("search_batches", []):
    for gap in batch.get("gaps", []):
        lines.append("- 检索缺口：" + str(gap).replace("\n", " "))
lines.append("")
out.write_text("\n".join(lines), encoding="utf-8")
# Preserve manually curated province text and replace only the generated section.
with (ROOT / "data/master.csv").open(encoding="utf-8-sig", newline="") as f:
    all_rows = list(csv.DictReader(f))
begin, end = "<!-- monitor:start -->", "<!-- monitor:end -->"
for province in regions:
    if any(c in province for c in '/\\:') or province in (".", ".."):
        raise ValueError("Unsafe province filename")
    path = ROOT / "provinces" / (province + ".md")
    text = path.read_text(encoding="utf-8-sig") if path.exists() else "# " + province + "\n"
    section = [begin, "## 自动监测记录", "", "最近更新时间：" + today, ""]
    for r in all_rows:
        if r.get("province") == province:
            section.append("- " + r["title"] + "｜" + r.get("stage", "") + "｜" + r["source_url"])
    section.append(end)
    if begin in text and end in text:
        text = text[:text.index(begin)] + "\n".join(section) + text[text.index(end) + len(end):]
    else:
        text = text.rstrip() + "\n\n" + "\n".join(section) + "\n"
    path.write_text(text, encoding="utf-8")
print(out)
