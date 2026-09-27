# attention-leverage

[![CI](https://github.com/xiongweilin/attention-leverage/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/xiongweilin/attention-leverage/actions/workflows/ci.yml)
[![SonarQube Cloud Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=metratio_attention-leverage&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=metratio_attention-leverage)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=metratio_attention-leverage&metric=coverage)](https://sonarcloud.io/summary/new_code?id=metratio_attention-leverage) [![Docs: EN / 中文](https://img.shields.io/badge/docs-EN%20%7C%20%E4%B8%AD%E6%96%87-blue.svg)](README.zh-CN.md)

[English](README.md) | [简体中文](README.zh-CN.md)

> 扩大机器的观察范围。压缩人的注意力负担。同时保留发现“自己对世界的模型正在过时”的能力。

`attention-leverage` 是一个以目标为驱动的信息获取和认知校准系统。

```text
输入
  ↓
模型理解 + 当前假设 + 长期覆盖历史
  ↓
目标 / 盲区 / 反证 / 环境 / 验证查询
  ↓
异构公开信息源
  ↓
确定性压缩
  ↓
语义资格判定
  ↓
注意力输出 + 认知地图
```

这个系统刻意不做无限信息流。它的目的，是让机器搜索得远得多，同时只让极少量信息真正进入人的注意力。

## 四个校准问题

每次运行现在可以分别回答四个问题：

1. **哪些内容你很可能已经很久没有看到？**
   - 基于搜索/观察覆盖记录，而不是没有证据的心理推断。
   - 系统明确区分 `未搜索` 与 `搜索过但没有结果`。

2. **哪些环境离你当前的信息暴露范围最远？**
   - 一个环境被建模为：人物 + 机构/地点 + 入口 + 默认规则 + 路径 + 时机 + 连接者/信任 + 成本/替代方案。
   - 输出尽量识别合法、公开、低成本的入口，而不是只描述身份象征。

3. **哪些变化可能迫使你重新解释当下？**
   - 旧框架和新的可能框架分别保存。
   - 在证据足够之前，新解释始终保持为暂定状态。

4. **哪些信号说明现有模型正在失效？**
   - 用户可以保存明确、可证伪的工作假设。
   - 语义层可以把反向信号关联到这些假设，并把假设标记为 `challenged`。
   - 当证据不足时，系统不会人为制造矛盾。

## 查询模式

第一次模型调用生成一个 `QueryPlan`，其中每条 route 都带有模式：

- `goal` — 直接回答当前目标；
- `blindspot` — 探测观察历史较少的类别/环境；
- `counterevidence` — 搜索能够证伪某个工作假设的证据；
- `environment` — 映射人物、机构、入口、规则、路径和时机；
- `verification` — 用更强证据确认一个可能产生重要后果的弱信号。

这样可以避免系统退化为纯粹的确认偏误引擎。

## 长期认知状态

SQLite 持久化的不只是文章历史，还包括：

- 条目身份和重复次数；
- 查询历史、来源类别、查询目的和结果数；
- 来源健康状态；
- 已保存目标；
- 有用 / 无关反馈；
- 明确的工作假设；
- 假设被挑战的时间戳；
- 反复出现的远距离环境；
- 每次运行生成的认知地图。

覆盖台账保持一个关键区分：

```text
从未搜索 ≠ 搜索过但什么都没找到 ≠ 被反复观察
```

因此，来源失败或空查询不会被静默转换成“不存在”的证据。

## 信息源池

默认池目前包含 25 个以上的内置公开信息源，覆盖不同的信息产生机制。

| 领域 | 来源 |
| --- | --- |
| 综合新闻 / 全球事件 | Google News RSS、GDELT |
| 社交 / 从业者弱信号 | Bluesky、Hacker News、Stack Overflow |
| 开源 / 软件包生态 | GitHub、npm、crates.io |
| 一般研究 | OpenAlex、arXiv、Crossref |
| 生物医学 / 健康 | Europe PMC、ClinicalTrials.gov |
| 监管 / 公共机构 | Federal Register、World Bank |
| 网络安全 | CISA KEV、NIST NVD |
| 自然灾害 | USGS earthquakes、NASA EONET |
| 人物 / 机构 | OpenAlex Authors、OpenAlex Institutions |
| 结构化实体 | Wikidata |
| 基金会 / 协会 / 非营利组织 | ProPublica Nonprofit Explorer |
| 资助 / fellowship / 机会时间 | Grants.gov |
| 长尾官方/小众环境 | 24 个预置 RSS/Atom feed + 可配置扩展 |
| 招聘 / 战略弱信号 | 10 个预置公开 Greenhouse board + 可配置扩展 |
| 可选企业披露 | SEC EDGAR（`SEC_USER_AGENT`） |
| 可选人道主义报告 | ReliefWeb（`RELIEFWEB_APPNAME`） |

十家新闻媒体重复同一个故事，不会被当作十种独立的信息机制。

## 环境模型

当证据支持时，语义层可以生成一个 `EnvironmentInsight`，包含：

- 环境名称以及它为什么在认知上较远；
- 公开/合法的入口；
- 从公开行为中可以观察到的隐藏/默认规则；
- 连接者角色，而不只是名人；
- 常见路径和转换；
- 申请/季节性时机；
- 成本更低的替代方案或外围入口；
- 证据条目 ID。

它的目标是回答这类问题：

> 这个环境中的人通常会在哪里自然相遇？  
> 真正帮助新人建立连接的是谁？  
> 圈内人默认“大家都已经知道”的事情是什么？  
> 哪些机会会在变得显而易见之前出现？  
> 哪些名义上的门槛是真实的，哪些存在公开替代路径？

## 确定性压缩

第二次模型调用之前，代码先处理便宜且可检查的工作：

- URL 和近似标题去重；
- freshness window；
- 排除词；
- 词法相关性；
- 历史新颖度；
- 来源反馈权重；
- authority 上下文；
- 类别多样性；
- 单来源 quota。

因此模型看到的是压缩后的候选集合，而不是未经处理的信息洪流。

## 语义资格判定

每个候选条目都会根据以下维度评估：

- 相关性；
- 新颖度；
- 重要性；
- 可行动性；
- 置信度；
- **模型压力** — 它对现有解释造成多强的压力；
- **环境距离** — 它是否暴露了一个结构上陌生的环境。

最终输出仍然是 `attention | watch | background`，但能够改变决策的反证和新出现的可进入环境，即使不是最熟悉的话题，也可以被提升优先级。

## 运行

Python 3.11+：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --reload
```

打开 `http://127.0.0.1:8000`。

当前模型客户端使用 OpenAI-compatible Responses API endpoint：

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=http://127.0.0.1:4101/v1
OPENAI_MODEL=...
LLM_TIMEOUT_SECONDS=90
```

即使没有模型配置，route、ranking 以及基础 coverage/blind-spot 输出仍可通过确定性 fallback 工作。

## Dashboard

Web UI 有四个页面：

- **运行** — 当前 digest、认知地图和按注意力排序的条目；
- **认知地图** — 低覆盖类别、反复出现的远距离环境和明确假设；
- **历史** — 之前的运行，以及它们产生了多少模型/环境挑战；
- **信息源** — 当前来源池和健康状态。

## 工作假设

API/UI 可以保存明确、可证伪的假设：

```text
POST /api/assumptions
GET  /api/assumptions
DELETE /api/assumptions/{id}
```

当一次运行返回有证据约束的模型挑战时，匹配的假设会被标记为 `challenged` 并记录时间戳，而不会被自动宣布为错误。

## CLI 与定时使用

```bash
attention-leverage "哪些公开入口能让我理解某个陌生行业的实际关系结构？"
attention-leverage --saved "agent-infra"
attention-leverage --saved '*' --json > latest.json
```

文本 CLI 输出包括：

- 长期未观察区域；
- 远距离环境；
- 触发重新解释的信号；
- 模型挑战；
- 按注意力排序的条目。

调度逻辑保持在语义核心之外：cron、systemd timer、GitHub Actions 或其他 scheduler 都可以调用同一条 pipeline。

## 添加长尾环境

仓库预置 24 个经过验证的公开 RSS/Atom feed，覆盖 Federal Reserve、BIS、SEC、FTC、GitHub、Cloudflare、Kubernetes、Rust、Python 和 NIST。通过 `config/sources.toml` 可以添加学校、协会、基金会、会议、公司 changelog、校友组织以及其他公开 feed：

```toml
[sources.rss]
enabled = true
feeds = [
  { name = "Official association", url = "https://example.org/feed.xml", authority = "primary" },
  { name = "Niche community", url = "https://community.example/rss", authority = "community" },
]
```

仓库还预置了 10 个公开 Greenhouse board（Figma、Coinbase、Scale AI、Airtable、Dropbox、Klaviyo、Vercel、xAI、Upstart 和 Intercom）。可以在同一个配置文件中增加或替换：

```toml
[sources.greenhouse]
enabled = true
boards = [
  { name = "Target company", token = "targetcompany" },
]
```

## 边界

- Discovery 不等于 verification。
- 公开信息不一定对新人具有实际可见性。
- 社交弱信号和 primary filing 在语义上并不等价。
- 空搜索结果不是“不存在”的证明。
- 认知距离根据系统的搜索/观察历史推断，而不是根据敏感个人属性推断。
- 系统不得根据一个人的信息覆盖情况推断阶层、种族、政治、健康、宗教或其他敏感属性。
- 反馈只会轻度调整来源权重，不能静默制造信息茧房。
- 被挑战的假设不自动等于错误。
- 一个看似合理的新解释不自动等于现实。

## 测试

```bash
pytest -q
```

CI 会编译应用、运行覆盖率测试，并在推送到 `main` 时执行 SonarQube Cloud。
