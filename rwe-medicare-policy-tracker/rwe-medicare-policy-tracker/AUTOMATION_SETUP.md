# 自动监测运行说明

## 已接入的流程

GitHub Actions → 固定官网访问 → DeepSeek Responses 联网检索 → 22字段校验与增量合并 → normalize.py → deduplicate.py → latest.csv → build_report.py → Markdown报告与省份自动记录 → Git提交与推送。

项目仍在 Git 根目录下的 `rwe-medicare-policy-tracker/rwe-medicare-policy-tracker` 中；工作流必须位于 Git 根目录的 `.github/workflows/monitor.yml`。无需移动现有文件。

## 启用

1. 在仓库 Settings → Secrets and variables → Actions → New repository secret 添加 `DEEPSEEK_API_KEY`。不要把密钥写入文件或聊天。
2. 可选 Repository variable `DEEPSEEK_MODEL`，默认 `deepseek-v4-flash`，须支持 Responses API 的 web_search 工具。
3. Actions → RWE Medicare Monitor → Run workflow → mode=test，执行离线验证。
4. 再以 mode=live 运行首次联网基线。该步骤会调用付费 API；初始32个官网分4组，加1组全网补漏，至少5次模型请求，搜索工具调用另计。后续历史来源增加时组数可能增加。
5. 查看 Actions 日志及生成的 data/collection.json、data/master.csv、data/latest.csv、reports/YYYY-MM-DD.md。
6. 每天北京时间09:17检查；距离上次成功运行满两个中国日历日才采集。不是精确48小时间隔；GitHub队列可能延迟。失败不前移成功时间，次日重试。手动live运行会立即采集。
7. 确保 Actions 可用，且仓库规则允许机器人向 main 推送。工作流声明 contents: write；分支保护若禁止直推，需要仓库管理员调整规则或改为PR流程。

旧 ChatGPT 定时任务没有被读取、迁移或停用。本实现由 GitHub Actions 独立调用联网 API；避免把原聊天任务的完成状态当作这里的运行状态。

## 本地验证

在三层同名文件夹的最内层项目目录运行（Python 3.12+，仅标准库，不需要安装依赖）：

```powershell
python -m unittest discover -s tests -v
python scripts/pipeline.py --help
```

配置本地环境变量 DEEPSEEK_API_KEY 后执行：

```powershell
python scripts/pipeline.py
```

单独运行原脚本仍兼容；完整流程应使用 pipeline.py，以免 latest.csv 与 master.csv 不一致。

## JSON/CSV 补录

`python scripts/pipeline.py --input <文件路径>`。CSV必须使用现有22字段表头；JSON结构如下：

```json
{
  "complete": true,
  "collected_at": "2026-09-08T09:17:00+08:00",
  "coverage": {"mode": "人工核验后导入"},
  "records": []
}
```

records 内每项是事件对象，字段来自 master.csv；必须含 title 和 source_url，字段值均为字符串。日期为 YYYY-MM-DD。
只有确已完成的检索才能传 complete=true；空数组表示该检索范围无新增，而非采集失败。
CSV导入视为人工提供的完整批次。相同批次重复导入不覆盖已有本期报告（最近100个批次去重）；新检索批次请包含新的 collected_at。
更新旧事件可使用原record_id。空字段不会清除历史值；同URL先合并再调用原去重脚本，避免“保留第一条”丢更新。
不同网址的同日、同省、同机构、同标题记录会保守视作转载。模糊语义去重依赖采集模型，仍需抽查。

## 数据与失败行为

- 首次默认回溯365天建立有限窗口基线；不是完整历史普查。可在执行环境设置 BASELINE_DAYS。
- 后续从上次成功日期向前回溯7天；失败间隔自动扩大检索期。
- 官网访问失败和检索缺口记录到 collection.json 与报告，不等同于“全国无变化”。
- government网页中能找到模型提供的短引文时，标记medium；这只验证来源和引文，不能替代完整语义事实审核。
- 非政府来源或自动引文核验失败统一待核实/low。机构官网、PDF、动态网页可能需要人工核验。
- API失败、未执行真实搜索、输出截断、JSON或枚举不合法：报错，不修改数据库和成功时间。
- 复用脚本在临时目录执行，全部成功才发布文件；本地不要并发运行。多文件写入由Git提交形成整体快照，本地突然断电仍可能留下部分文件。
- 无变化的新批次会清空 latest.csv，保留历史库，生成注明检索范围的报告。
- last_seen 表示最近一次记录实质变化的日期；不会因重复观察每天刷新。
- 报告按日期命名，同日新的成功批次会替换该日报；历史版本可从Git恢复。
- 只提交data、reports、provinces，密钥不写盘。推送失败会使任务失败并保留输出artifact；不强推、不自动解决远端冲突。
- 首次运行前master.csv仍保持原样，离线测试记录绝不进入正式数据。

## 接口资料

- [DeepSeek Responses](https://api-docs.deepseek.com/guides/responses_api/)
- [GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub scheduled events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

提交采集脚本、测试或工作流修改到main时，自动执行离线测试，不调用付费API。已有DEEPSEEK_API_KEY即可使用默认模型，无需配置其他变量。
DeepSeek未声明支持域名filters和include参数，本实现不发送它们；指定官网分组在结果端校验域名，排除项记入覆盖缺口。
