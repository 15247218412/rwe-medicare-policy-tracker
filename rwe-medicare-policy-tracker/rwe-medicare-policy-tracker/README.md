# 全国真实世界医保综合价值评价政策监测库

这是一个面向“真实世界医保综合价值评价”政策、试点、项目、可信评价点及结果应用的长期监测仓库。

## 目标

- 每两天执行一次增量检索；
- 优先覆盖国家医保局、31个省级医保部门、试点地区、国家可信评价点及相关医疗机构；
- 只重点报告新增或发生实质变化的信息；
- 保留原始网页 URL、附件 URL 和发布日期；
- 形成可持续积累的全国政策数据库。

## 仓库结构

```text
rwe-medicare-policy-tracker/
├─ AGENTS.md                    # Codex 的长期工作规范
├─ AUTOMATION_PROMPT.md         # Codex Automation 最终提示词
├─ SETUP_GUIDE.md               # GitHub + Codex 配置步骤
├─ data/
│  ├─ master.csv                # 全量事件库
│  ├─ latest.csv                # 本期新增/更新
│  ├─ regions.csv               # 地区状态库
│  ├─ documents.csv             # 政策及附件库
│  └─ organizations.csv         # 机构库
├─ provinces/                   # 各省长期档案
├─ reports/                     # 每两日增量报告
├─ sources/
│  ├─ official_sites.csv        # 官方站点种子表
│  └─ keywords.txt              # 检索关键词
├─ scripts/
│  ├─ normalize.py              # 数据标准化
│  ├─ deduplicate.py            # 去重
│  └─ build_report.py           # 根据 latest.csv 生成增量报告
└─ templates/
   ├─ province_template.md
   └─ report_template.md
```

## 当前官方依据

国家医保局于 2025-09-23 发布《关于开展真实世界医保综合价值评价试点工作的通知》（医保办发〔2025〕15号），明确部分先行地区开展试点，并提出 2026 年进入实践阶段、2027 年进入应用阶段。2026-01-16，首批 79 家医疗机构组成真实世界医保综合价值评价国家可信评价点网络。

首次使用请先阅读 `SETUP_GUIDE.md`，然后在 Codex 中运行一次“基线调查”，确认数据库结构无误后再启用每两日 Automation。
