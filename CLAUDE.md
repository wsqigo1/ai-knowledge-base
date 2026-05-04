# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定义

**AI Knowledge Base** 是一个自动化技术情报系统，通过三阶段 Agent 流水线将 GitHub Trending、Hacker News、Product Hunt 等来源的 AI/LLM/Agent 资讯转化为结构化 JSON 知识条目。

## 三阶段 Agent 流水线

```
[collector agent] ──→ knowledge/raw/{source}-{date}.json
[analyzer agent]  ──→ 同文件，添加 summary/tags/score/analyzed_at
[organizer agent] ──→ knowledge/articles/{date}-{slug}.json + index.json
```

**关键约束**：
- collector 和 analyzer **只读取和返回数据，不写文件**；写文件由主 Agent 委派 organizer 执行
- organizer **禁止 WebFetch/Bash**，只操作已有数据
- 质量门控：`score < 6.0` 或 `summary < 50字` 或 `tags < 2个` 的条目被丢弃，原因记入 `knowledge/raw/filtered-{date}.json`

## 调用方式

在对话中直接描述任务，Claude Code 会委派对应的 skill 或 sub-agent：

```
# 单阶段（调用对应 skill）
采集今天的 GitHub Trending 数据
采集今天的 Hacker News 数据
采集今天的 Product Hunt 数据
分析 knowledge/raw/github-trending-2026-05-03.json，补充摘要和评分

# 完整流水线
执行今天的完整采集→分析→整理流水线
```

可用 skills：`github-trending`、`hackernews`、`producthunt-daily`、`tech-summary`

## 数据格式

### 原始数据（`knowledge/raw/`）

collector 写入，analyzer enriched 后在同一文件追加字段：

```json
{
  "source": "github-trending",
  "collected_at": "2026-05-03T08:00:00Z",
  "items": [
    {
      "id": "openai/swarm",
      "title": "swarm",
      "url": "https://github.com/openai/swarm",
      "summary": "...",
      "tags": ["multi-agent", "agent-framework"],
      "score": 8.5,
      "analyzed_at": "2026-05-03T09:00:00Z"
    }
  ]
}
```

### 知识条目（`knowledge/articles/`）

organizer 输出，每条一个文件，文件名为 `{date}-{slug}.json`：

```json
{
  "id": "kb-2026-05-03-001",
  "title": "...",
  "source": "github-trending",
  "source_id": "openai/swarm",
  "url": "https://github.com/openai/swarm",
  "summary": "中文摘要，100-200 字",
  "tags": ["multi-agent", "agent-framework", "open-source"],
  "score": 8.5,
  "collected_at": "...",
  "analyzed_at": "...",
  "organized_at": "...",
  "status": "published"
}
```

ID 规则：`kb-{YYYY-MM-DD}-{三位递增序号}`，从 index.json 当天最大序号 +1 开始。

### 索引文件（`knowledge/articles/index.json`）

organizer **增量追加**，永不全量重写。`entries` 按 `organized_at` 降序，`total_count` 必须等于 `entries` 数组长度。

## 分析评分公式

```
score = (技术深度(×0.25) + 实用价值(×0.30) + 时效性(×0.20) + 社区热度(×0.15) + 领域匹配(×0.10)) × 10
```

取值范围：1-10（整体乘以 10，便于直观比较）。

摘要要求：中文，100-200 字，结构为「是什么 → 解决什么问题 → 核心技术亮点 → 适用场景」，技术术语保留英文。

标签：3-5 个，英文小写连字符，优先从标准池选：`large-language-model`、`agent`、`rag`、`vector-database`、`fine-tuning`、`prompt-engineering`、`multimodal`、`code-generation`、`benchmark`、`reasoning`、`multi-agent`、`tool-use`

## 自动校验 Hook

每次 Write/Edit `knowledge/articles/*.json` 后，PostToolUse hook 自动运行：

1. `hooks/validate_json.py <filepath>` — 校验必填字段、`score` 范围(1-10)、`url` 格式、`collected_at` ISO 8601 格式
2. `hooks/check_quality.py <filepath>` — 检查摘要长度(100-200字)、标签数(3-5个)、score≥6.0，评级低于 B 时告警

手动运行：`python3 hooks/validate_json.py knowledge/articles/<file>.json`

## 语言约定

- 代码、JSON 键名、文件名、标签：英文
- `summary` 字段、分析注释：中文

## 环境变量

```bash
ANTHROPIC_API_KEY=sk-ant-...   # Claude API
GITHUB_TOKEN=ghp_...           # GitHub API（不设则限速 60次/小时）
```
