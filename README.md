# LongRiver 长江水情私有日更新

基于 [cxumol/LongRiver](https://github.com/cxumol/LongRiver) 创建，保留上游 MIT 许可和出处。仓库为私有，默认每天北京时间 **08:30** 自动运行，也可在 Actions → Daily LongRiver Data → Run workflow 手动执行。GitHub 可能延迟启动。

## 首次运行核验（2026-10-26）

[完整运行已通过](https://github.com/Dpasang/longriver-data/actions/runs/40344115057)。从源站获得14站观测，观测时间均为北京时间2026-10-26 22:00。上游1,175个历史数据文件（133,468,338字节）均已导入，Git文件哈希逐一一致。历史CSV中92个文件、20,820行被标记为行结构或时间字段异常，另有1条JSON缺测时间；这些原始文件未被修改。此处为首次核验快照，后续状态以status/中的报告为准。

## 每天做什么

1. 下载上游 `master` 分支当前的数据文件，仅同步数据，不执行上游代码。
2. 对 JSON 可读性、CSV 表头及行结构、站点和观测时间进行检查，再原样保存到 `data/`。历史 CSV 存在字段变化导致的列错位时，保留原文件并写入质量清单，不自动猜测修复。
3. 访问原项目使用的长江委水情页面 `http://www.cjh.com.cn/sqindex.html`，提取 `sssq` 中的站点记录，独立保存当天快照。
4. 源站读取失败时，尝试使用上游各站最新记录，明确标记为 `upstream_fallback` 并记录源站失败类型。任一站最新记录超过 **48 小时**，本次更新判为失败；不会用旧数据覆盖 `latest/`。
5. 把有效数据和运行状态提交回本私有库；失败也保留状态文件并让任务显示失败。

无需添加 Cookie、GitHub PAT 或其他 Secret，使用 GitHub 为本仓库提供的临时任务令牌。

## 数据位置

| 位置 | 内容 |
|---|---|
| `data/YYYY-MM/` | 上游历史归档：月度 LongRiver.json 和分站 CSV，文件原值保留 |
| `snapshots/YYYY/MM/YYYY-MM-DD.json` | 本次获取来源、获取时间、观测时间范围及全部站点原始记录 |
| `snapshots/YYYY/MM/YYYY-MM-DD.csv` | 当天快照的表格版本 |
| `latest/data.json`、`latest/data.csv` | 最近一次通过时效与结构检查的快照 |
| `status/latest.json` | 最近一次运行是否成功、站点数、归档文件数、源站与上游来源、版本及异常 |
| `status/archive_quality.json` | 历史 CSV 结构异常、JSON 缺测时间等问题的文件、记录数和位置；原文件仍完整保留 |

同一天手动复跑会更新当天快照；Git 提交历史保留先前版本。站点按 `stcd`（缺少时按河流与站名）和观测时间选择最新记录。数据获取日期与源站观测日期分别记录。

## 证据与适用边界

- 初次核查发现，部分历史 CSV 在 `q`、`oq` 等字段变化后出现表头与行宽不一致，不能直接按原表头用于分析。请先检查 `status/archive_quality.json`，优先使用对应月度 JSON 的具名字段；本项目保留证据，不把“已归档”等同于“质量通过”。
- 历史 JSON 也可能保留 `tm: "-"` 等缺测标记，归档不修改这些值；最新快照的时效判断仅使用有效时间戳，缺测记录不能充当最新观测。
- 初始读取上游时看到 2020-07 至 2026-10 的月份目录；历史覆盖的实际起止日期、站点数和缺测情况需按文件核查。目录存在不等于每日、逐站完整。
- `q` 为原始流量字段，`z` 为原始水位字段，`tm` 按源站毫秒时间戳解析；`rvnm`、`stnm`、`stcd`、`wptn` 等原字段保留。没有填补缺值、插值或自行换算单位。
- 源站当前站点数量随页面变化；本仓库不将当前 14 站视作整个长江流域的完整站网。
- 每日一次源站快照不能重建当天全部小时变化；上游归档可提供额外记录，但其连续性需另行审核。
- 初次导入的是上游当前数据文件，不包含其全部 Git 提交历史。结构检查不等同于水文质量控制、官方数据授权或独立测量验证。MIT 许可适用于代码；原始数据使用仍应遵守来源要求。
- 原项目使用 HTTP 公开页面。本地测试中 HTTP 可读，HTTPS 握手未成功，因此沿用原地址且不向该站点发送凭据。
- Actions 使用账户现有配额。失败原因和数据来源以运行日志及 `status/latest.json` 为准。

## 本地运行

Python 3.12 或更高版本，无第三方依赖。

```text
python -m unittest discover -s tests -v
python collect.py --upstream path/to/LongRiver --root path/to/output
```

原项目说明与许可另存于 `upstream/README.txt` 和 `LICENSE.txt`。
