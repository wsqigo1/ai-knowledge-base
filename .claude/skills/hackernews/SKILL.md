---
name: hackernews
description: 从 Hacker News 采集当日热门 AI/LLM 技术文章，筛选后写入 knowledge/raw/hackernews-top-{date}.json。
---

# Skill: Hacker News 采集

## 用途

从 Hacker News 采集当日热门技术文章，筛选 AI/LLM/Agent 相关条目，
写入 `knowledge/raw/hackernews-top-{YYYY-MM-DD}.json`。

## 触发方式

用户说"采集 Hacker News"、"抓取 HN 热门文章"时使用本技能。

## 执行步骤

### 1. 获取 Top Stories ID 列表

```
GET https://hacker-news.firebaseio.com/v0/topstories.json
```

返回最多 500 条 story ID，取前 100 条。

### 2. 批量获取 Story 详情

对每个 ID 并发请求（最多 10 个并发）：

```
GET https://hacker-news.firebaseio.com/v0/item/{id}.json
```

提取字段：

| 字段 | 来源 | 说明 |
|------|------|------|
| `id` | `id` | HN 条目 ID |
| `title` | `title` | 文章标题 |
| `url` | `url` | 原文链接（`url` 为空时用 HN 链接） |
| `score` | `score` | HN 热度分数 |
| `comments` | `descendants` | 评论数 |
| `author` | `by` | 发帖人用户名 |
| `hn_url` | 拼接 | `https://news.ycombinator.com/item?id={id}` |

跳过 `type != "story"` 的条目（Ask HN、Job 等）。

### 3. 相关性预筛选

仅保留满足以下任一条件的文章：
- `title` 包含关键词（大小写不敏感）：`AI`、`LLM`、`GPT`、`Claude`、`Gemini`、`agent`、`RAG`、`embedding`、`neural`、`ML`、`machine learning`、`deep learning`、`transformer`、`diffusion`、`fine-tun`
- `score >= 100`（高热度文章无论主题均保留，后续由 Analyzer 评分过滤）

### 4. 写入输出

输出路径：`knowledge/raw/hackernews-top-{YYYY-MM-DD}.json`

```json
{
  "source": "hackernews-top",
  "collected_at": "2026-05-03T08:00:00Z",
  "query": "AI OR LLM OR agent OR RAG, top stories, score >= 100",
  "count": 15,
  "items": [
    {
      "id": 43812345,
      "title": "Introducing Claude 4: Frontier Intelligence",
      "url": "https://anthropic.com/news/claude-4",
      "hn_url": "https://news.ycombinator.com/item?id=43812345",
      "score": 842,
      "comments": 312,
      "author": "pg"
    }
  ]
}
```

**幂等性**：若当天文件已存在，按 `id` 去重后追加，不覆盖已有条目。

## 错误处理

| 错误 | 处理策略 |
|------|----------|
| Firebase API 超时（>10s） | 重试最多 3 次，仍失败则跳过该条目 |
| `url` 字段为空（自发帖） | 使用 `hn_url` 作为链接 |
| 单条 item 请求失败 | 跳过，不中断整体采集 |
| 空结果 | 写入 `items: []` 并记录警告，不报错退出 |
