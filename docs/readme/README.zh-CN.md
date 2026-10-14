# nace-kit

**[nace.ai Drex API](https://console.nace.ai) 的多 key 客户端、预设模板、CLI 与 MCP 服务 —— 用校准概率对文本或 JSON 做分类，Python 代码和 MCP agent 都能用。**

[English](../../README.md) | 简体中文

[![PyPI](https://img.shields.io/pypi/v/nace-kit)](https://pypi.org/project/nace-kit/)
[![Python](https://img.shields.io/pypi/pyversions/nace-kit)](https://pypi.org/project/nace-kit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/lincong1987/nace-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/lincong1987/nace-kit/actions/workflows/ci.yml)

> [!IMPORTANT]
> **社区项目，与 Nace AI 无隶属关系、未获其背书。** 只从 PyPI（[`nace-kit`](https://pypi.org/project/nace-kit/)）或 GitHub（[`lincong1987/nace-kit`](https://github.com/lincong1987/nace-kit)）安装；名字相似的项目不是本仓库。官方 Python SDK 与 MCP 服务见 [`nace-sdk`](https://pypi.org/project/nace-sdk/) 和 [`nace-mcp`](https://pypi.org/project/nace-mcp/)。

## 目录

- [为什么有这个项目](#为什么有这个项目)
- [快速开始](#快速开始)
- [工作原理](#工作原理)
- [与官方 SDK 对比](#与官方-sdk-对比)
- [问题类型](#问题类型)
- [文档管线](#文档管线)
- [给 agent 用的 MCP](#给-agent-用的-mcp)
- [命令行](#命令行)
- [常见问题](#常见问题)
- [参与贡献](#参与贡献)
- [许可证](#许可证)

## 为什么有这个项目

Drex 用校准概率回答关于任意文本或 JSON 的类型化问题——适合工单路由、问题分级、回复评判。官方 `nace-sdk` 覆盖整个 API；nace-kit 聚焦它外围的**运营能力**：

- **key 池** —— 多个 API key 合一使用。失效 key（401）或配额耗尽（429）在请求中途自动切到下一个。
- **响应缓存** —— Drex 输出是确定性的，相同请求由 LRU 缓存直接返回，不再重复计费。
- **用量统计** —— 每个 key 的调用数和 token 数，随时在 `client.usage` 里可见。
- **预设与类型化** —— `urgency()`、`sentiment()`、`severity()`、`priority()` 开箱即用；问题和响应全程 pydantic 类型化。
- **文档管线** —— 包装官方 SDK 的 parse / extract / ground，共享同一 key 池（`[docs]` 可选依赖）。

## 快速开始

需要 Python 3.11+（Windows / macOS / Linux）和一个或多个在[控制台](https://console.nace.ai)创建的 API key。

```bash
pip install nace-kit        # 或：uv add nace-kit / uvx nace-kit 一次性调用
export NACE_API_KEYS="nace_sk_...,nace_sk_..."   # key 池；单个 key 用 NACE_API_KEY
```

```python
from nace_kit import NaceClient, presets

client = NaceClient()  # 默认 drex-latest

# 二元问题 -> "是"的概率
r = client.classify("Help! My payouts have been failing for 3 days.", presets.urgency())
r.answers["is_urgent"].noul             # 0.7161

# state 可以是任意 JSON；多个问题合并为一次请求
r = client.classify(
    {"ticket": "#42", "subject": "payout failure", "days_stuck": 3},
    [presets.urgency(), presets.severity(), presets.priority()],
)

client.models()   # 可用模型列表；也可当作便宜的 key 健康检查
client.usage      # {'nace_sk_wn…': {'calls': 12, 'input_tokens': 300, ...}}
```

异步用法相同：`from nace_kit import AsyncNaceClient`。

## 工作原理

| 故障 | 行为 |
|---|---|
| 401 / 403（key 无效或失效） | 立即轮转到下一个 key |
| 429（配额），配置了多个 key | 立即轮转到下一个 key |
| 429，只配了一个 key | 同 key 退避重试（遵循 `Retry-After`） |
| 408 / 5xx / 网络错误 / 超时 | 同 key 重试——指数退避 + 抖动、感知 `Retry-After`、总预算 30 秒——耗尽后轮转 |
| 4xx（请求体被拒） | 立即抛错不重试（`NaceBadRequest`） |

key 在构造时校验格式（`nace_sk_` + 43 字符）；重试（`max_retries`、`backoff_*`、`retry_budget`）、缓存大小和超时都是构造参数。

## 与官方 SDK 对比

| | 官方 `nace-sdk` | `nace-kit` |
|---|---|---|
| 分类 API（三种题型、任意 JSON state、模型列表、类型化对象） | ✅ | ✅ |
| **多 key 池 + 故障转移** | ❌ 单 key | ✅ |
| **LRU 响应缓存** | ❌ | ✅ |
| **按 key 用量统计** | ❌ | ✅ |
| 退避重试、`Retry-After`、预算 | ✅ | ✅（与轮转结合） |
| 问题预设模板 | ❌ | ✅ |
| 文档管线（上传/解析/抽取/任务） | ✅ | ✅ 包装官方 SDK（`[docs]` 可选依赖） |
| `nace login` 凭证文件 | ✅ | ❌ 环境变量 |
| CLI + MCP 服务同包分发 | ❌ 独立的 `nace-mcp` | ✅ |

## 问题类型

| 类型 | `criteria` | 回答 |
|---|---|---|
| `noul` | 可选 `{"true": "…", "false": "…"}` 结果描述 | `{"noul": 0..1}` —— "是"的概率 |
| `choice` | `{标签: 描述}` —— 选出一个标签 | `{"choice": "billing", "probabilities": {...}, "confidence": …}` |
| `score` | `["低", "中", "高"]` —— 有序等级 | `{"score": 1.31, "legend": […], "probabilities": {...}, "confidence": …}` |

```python
from nace_kit import presets as p

p.noul("要退款吗？", true="明确或暗示要求退钱")
p.choice("这是什么问题？", {"billing": "支付问题", "technical": None})
p.score("用户多愤怒？", ["平静", "不满", "愤怒", "暴怒"])
```

对概率自己设阈值，不要把模型输出当最终裁决。

## 文档管线

文档操作包装官方 `nace-sdk`（MIT）——API 面是官方的，key 池是我们的：

```bash
pip install "nace-kit[docs]"
```

```python
from nace_kit import DocsClient

docs = DocsClient()   # 同一个 NACE_API_KEYS 池；401/429 自动轮转
job = docs.parse("https://example.com/report.pdf",
                 output={"formats": ["markdown"]}, wait=120)
job.result["document"]["markdown"]
```

`parse` / `split` / `classify_document` / `extract` / `ground` 创建任务并在传 `wait` 时轮询到完成；`docs.job(id)`、`docs.wait(id)`、`docs.jobs()` 负责后续管理。每个创建调用都带幂等键——调用中途轮转 key 不会重复计费。异步版 `AsyncDocsClient` 行为一致。

## 给 agent 用的 MCP

注册一次，所有项目可用。ZCode（`~/.zcode/cli/config.json` → `mcp.servers`）：

```json
"nace": {
  "type": "stdio",
  "command": "uvx",
  "args": ["nace-kit-mcp"],
  "env": { "NACE_API_KEYS": "nace_sk_...,nace_sk_..." }
}
```

Claude Desktop / Cursor：`mcpServers` 下同款结构。

工具：`classify`（完整批量接口）、`ask`（单问题封装，支持 noul / score / choice）、`list_models`，以及装了 `[docs]` 依赖后的 `parse_document`、`extract_data`、`get_document_job`。

偏好 skill？`nace-kit --install-skill` 会把一个 [Agent Skill](https://agentskills.io)（`SKILL.md`）装到 `~/.agents/skills/`（`--claude` 则装到 `~/.claude/skills/`），即使不注册 MCP，agent 也能获得使用指导——问题措辞、批量合并、阈值设定。

## 命令行

```bash
nace-kit "Camera 3 is showing a black screen." --no-cache
nace-kit "..." --ask "How angry is the user?" --kind score --levels calm annoyed angry furious
nace-kit "..." --ask "What is this about?" --kind choice --options billing:"payment issues" technical:"bugs"
nace-kit --models
```

## 常见问题

**缓存安全吗？**
Drex 对相同输入（同模型、state、问题）的输出是确定性的，所以缓存是精确的。传 `cache_size=0` 可关闭。

**调用的是哪个模型？**
默认 `drex-latest`，nace.ai 会在公告日期把它指向新版本；需要可复现请用 `NaceClient(model="drex-v2.0")` 固定。

**key 放哪里？**
`NACE_API_KEYS`（逗号分隔的 key 池）或 `NACE_API_KEY`。给 agent 用就写进 MCP 服务的 `env` 块。永远不要写进代码。

## 参与贡献

欢迎在 [lincong1987/nace-kit](https://github.com/lincong1987/nace-kit) 提 issue 和 PR。

```bash
uv sync            # httpx、mcp、pytest
uv run pytest -q   # 单元测试——无需网络和 key
```

## 许可证

[MIT](../../LICENSE) © nace-kit 贡献者。
