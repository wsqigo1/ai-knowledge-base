---
name: github-trending
description: 从 GitHub 采集近 7 天 AI/LLM/Agent/RAG/MCP 领域热门开源项目，经质量过滤后写入 knowledge/raw/github-trending-{date}.json。
---

# Skill: GitHub Trending 采集

## 用途

通过 GitHub Search API 采集近 7 天 AI/LLM/Agent 领域热门开源项目，
经质量过滤后写入 `knowledge/raw/github-trending-{YYYY-MM-DD}.json`。

## 触发方式

用户说"采集 GitHub Trending"、"抓取今天的 GitHub 热门项目"时使用本技能。

## 执行步骤

### 1. 搜索 API 调用

```
GET https://api.github.com/search/repositories
  ?q=AI+OR+LLM+OR+agent+OR+RAG+OR+MCP+created:>{7天前日期}&sort=stars&order=desc&per_page=50
```

请求头：
```
Accept: application/vnd.github.v3+json
Authorization: Bearer $GITHUB_TOKEN   # 有则加，无则限速 60 次/小时
```

`{7天前日期}` 格式为 `YYYY-MM-DD`，如今天是 2026-05-03，则填 `2026-04-26`。

### 2. 质量过滤

采集结果须满足**全部**以下条件才保留：

| 条件 | 说明 |
|------|------|
| `stargazers_count >= 50` | 过滤无热度的新仓库 |
| `description` 非空 | 无描述的项目无法生成摘要 |
| `fork == false` | 排除 Fork 仓库，只保留原创项目 |
| 名称不含 `awesome` | 排除 awesome-list 聚合类仓库 |

过滤后目标保留 **15-30 条**，质量标准：

| 结果数量 | 判断 | 处理 |
|----------|------|------|
| 15-30 条 | 正常范围 | 直接写入 |
| < 10 条 | 关键词可能需要扩展 | 放宽 stars 阈值至 ≥ 10 后重试；仍不足则写入现有结果并报告给用户 |
| > 50 条 | 过滤条件可能太宽松 | 提高 stars 阈值至 ≥ 200 后重新筛选 |

### 3. 字段提取

每条记录提取以下字段：

| 输出字段 | GitHub API 字段 | 说明 |
|----------|-----------------|------|
| `id` | `full_name` | 仓库全名，如 `openai/swarm` |
| `title` | `name` | 仓库短名，如 `swarm` |
| `url` | `html_url` | 仓库主页 URL |
| `description` | `description` | 原始描述 |
| `stars` | `stargazers_count` | Star 数 |
| `forks` | `forks_count` | Fork 数 |
| `language` | `language` | 主要编程语言 |
| `topics` | `topics` | 仓库 topic 标签列表 |
| `license` | `license.spdx_id` | 许可证，如 `MIT`；无则 `null` |
| `created_at` | `created_at` | 仓库创建时间（ISO 8601） |
| `updated_at` | `updated_at` | 最近更新时间（ISO 8601） |

### 4. README 增强（仅 Top 5）

对 stars 最高的 5 个仓库，额外抓取 README 前 500 字：

```
GET https://api.github.com/repos/{owner}/{repo}/readme
Accept: application/vnd.github.raw+json
```

将结果去除 Markdown 语法后，作为 `readme_excerpt` 字段附加到对应条目。
若请求失败，`readme_excerpt` 设为 `null`，不阻断整体流程。

### 5. 写入输出

输出路径：`knowledge/raw/github-trending-{YYYY-MM-DD}.json`

```json
{
  "source": "github-trending",
  "collected_at": "2026-05-03T08:00:00Z",
  "query": "AI OR LLM OR agent OR RAG OR MCP, past 7 days, sorted by stars",
  "count": 20,
  "items": [
    {
      "id": "openai/swarm",
      "title": "swarm",
      "url": "https://github.com/openai/swarm",
      "description": "Educational framework for multi-agent orchestration.",
      "stars": 18432,
      "forks": 1203,
      "language": "Python",
      "topics": ["agent", "llm", "openai"],
      "license": "MIT",
      "created_at": "2026-04-01T08:00:00Z",
      "updated_at": "2026-05-03T06:30:00Z",
      "readme_excerpt": "Swarm is an educational framework..."
    }
  ]
}
```

**幂等性**：若当天文件已存在，按 `id` 去重后追加，不覆盖已有条目。

## 错误处理

| 错误 | 处理策略 |
|------|----------|
| 401 认证失败 | 检查 `GITHUB_TOKEN` 是否设置，提示用户，终止采集 |
| 403/429 限速 | 读取 `X-RateLimit-Reset` 头，等待至重置时间后重试，最多 3 次 |
| 网络超时（>15s） | 跳过当前请求，记录到 `knowledge/raw/errors-{date}.json`，继续处理其余条目 |
| 空结果 | 放宽 stars 阈值后重试；仍为空则写入 `items: []` 并记录警告，不报错退出 |
| README 获取失败 | `readme_excerpt` 设为 `null`，不阻断整体流程 |
