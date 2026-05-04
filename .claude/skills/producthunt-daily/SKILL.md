---
name: producthunt-daily
description: 采集 Product Hunt 当日 AI/Tech 热门产品日榜，生成中文摘要与相关性评分，写入 knowledge/raw/ 并整理为知识条目更新索引。覆盖采集→分析→管理完整流水线。
---

# Skill: Product Hunt 日榜采集与分析

## 用途

采集 Product Hunt 当日热门产品，筛选 AI/LLM/Agent/开发者工具相关条目，
生成中文摘要和相关性评分，完成从原始数据到知识条目的完整处理流水线。

## 触发方式

用户说"采集 Product Hunt"、"抓取今天的 PH 日榜"、"Product Hunt 今日热门"时使用本技能。

## 环境变量

```bash
PRODUCTHUNT_TOKEN=<your_token>   # Product Hunt API Developer Token（必须）
```

获取方式：登录 https://www.producthunt.com/v2/oauth/applications 创建应用，
获取 Developer Token（无需 OAuth 流程，直接使用 Bearer Token）。

---

## 阶段一：采集

### 1. GraphQL 查询

Product Hunt 使用 GraphQL API，端点：

```
POST https://api.producthunt.com/v2/api/graphql
Content-Type: application/json
Authorization: Bearer $PRODUCTHUNT_TOKEN
```

查询今日（UTC 日期）Top 30 产品：

```graphql
{
  posts(order: VOTES, postedAt: "{YYYY-MM-DD}", first: 30) {
    edges {
      node {
        id
        name
        tagline
        description
        url
        votesCount
        commentsCount
        website
        createdAt
        topics {
          edges {
            node { name }
          }
        }
      }
    }
  }
}
```

`{YYYY-MM-DD}` 替换为今日 UTC 日期，如 `2026-05-03`。

请求 Body 示例：
```json
{
  "query": "{ posts(order: VOTES, postedAt: \"2026-05-03\", first: 30) { edges { node { id name tagline description url votesCount commentsCount website createdAt topics { edges { node { name } } } } } } }"
}
```

### 2. 质量过滤

采集结果须满足**全部**以下条件才保留：

| 条件 | 说明 |
|------|------|
| `votesCount >= 50` | 过滤无热度的冷门产品 |
| `tagline` 非空 | 无描述无法生成摘要 |
| `name` 不含 `"Book"` / `"Course"` / `"Template"` | 排除内容资源类，保留工具产品 |

过滤后目标保留 **10-20 条**：

| 结果数量 | 处理 |
|----------|------|
| 10-20 条 | 直接进入分析阶段 |
| < 8 条   | 放宽 votesCount 至 ≥ 20 后重查；仍不足则写入现有结果并报告 |
| > 25 条  | 提高 votesCount 阈值至 ≥ 150 后重新筛选 |

### 3. 字段提取

每条记录提取以下字段：

| 输出字段 | API 字段 | 说明 |
|----------|----------|------|
| `id` | `id` | PH 产品 ID |
| `title` | `name` | 产品名称 |
| `tagline` | `tagline` | 一句话描述 |
| `description` | `description` | 详细描述（可为空） |
| `url` | `url` | PH 产品页 URL（`https://www.producthunt.com/posts/...`） |
| `website` | `website` | 产品官网 |
| `votes` | `votesCount` | 投票数 |
| `comments` | `commentsCount` | 评论数 |
| `topics` | `topics.edges[].node.name` | 话题标签列表 |
| `collected_at` | 当前 UTC 时间 | ISO 8601 |
| `posted_at` | `createdAt` | 发布时间 |

### 4. 写入原始文件

输出路径：`knowledge/raw/producthunt-daily-{YYYY-MM-DD}.json`

```json
{
  "source": "producthunt-daily",
  "collected_at": "2026-05-03T08:00:00Z",
  "date": "2026-05-03",
  "count": 15,
  "items": [
    {
      "id": "12345",
      "title": "ToolName",
      "tagline": "The best AI tool for X",
      "description": "...",
      "url": "https://www.producthunt.com/posts/toolname",
      "website": "https://toolname.com",
      "votes": 850,
      "comments": 120,
      "topics": ["Artificial Intelligence", "Developer Tools"],
      "posted_at": "2026-05-03T00:00:00Z",
      "collected_at": "2026-05-03T08:00:00Z"
    }
  ]
}
```

**幂等性**：若当天文件已存在，按 `id` 去重后追加，不覆盖已有条目。

---

## 阶段二：分析

对阶段一写入的原始文件进行深度分析，跳过已有 `analyzed_at` 字段的条目（幂等）。

### 1. 相关性预筛选

仅对以下条目执行完整分析，其余条目设 `score: 0` 直接跳过：

- `topics` 包含：`Artificial Intelligence`、`Machine Learning`、`Developer Tools`、`Productivity`、`No-Code`、`Open Source`
- 或 `tagline`/`description` 包含关键词（大小写不敏感）：`AI`、`LLM`、`GPT`、`Claude`、`agent`、`RAG`、`embedding`、`copilot`、`automation`、`workflow`、`API`

### 2. 摘要生成规范

摘要须遵循三层结构，**100-200 字**，中文，技术术语保留英文：

1. **定位**：这是什么产品，解决什么问题
2. **核心功能**：主要特性与技术实现方式
3. **评估**：目标用户、与现有方案的差异、社区热度（votes 数字化表达）

写作要求：
- 直接切入核心，不以"这是一个…"等模板句开头
- 用 votes 数字体现热度（如"上线首日获得 850 票"）
- 不照抄 tagline/description，要有独立分析判断

### 3. 评分规范

五维加权公式：

```
score = (实用价值(×0.30) + 技术深度(×0.25) + 时效性(×0.20) + 社区热度(×0.15) + 领域匹配(×0.10)) × 10
```

取值范围：1.0-10.0。

各维度评分标准（0.0-1.0）：

| 维度 | 高分标准 | 低分标准 |
|------|----------|----------|
| 实用价值 | 可直接使用的 SaaS/工具，有免费层或开源 | 概念产品，无法立即使用 |
| 技术深度 | 有原创技术、API/SDK、可集成 | 纯界面包装，无技术内涵 |
| 时效性 | 今日首发或重大更新 | 老产品重新上架 |
| 社区热度 | votes > 500 | votes < 100 |
| 领域匹配 | 核心 AI/LLM/Agent/开发工具 | 生活类、消费类应用 |

### 4. 标签规范

- 3-5 个，英文小写，连字符分隔
- 优先使用标准标签池：

```
large-language-model  agent             rag              mcp
code-generation       prompt-engineering  no-code        developer-tools
productivity          open-source        multimodal      workflow-automation
ai-assistant          image-generation   voice-ai        data-analysis
```

### 5. 将分析结果回写至原始文件

将以下字段追加到每条 item（直接修改 `knowledge/raw/producthunt-daily-{date}.json`）：

```json
{
  "summary": "...",
  "tags": ["ai-assistant", "developer-tools"],
  "score": 8.2,
  "score_breakdown": {
    "practical_value": 0.90,
    "technical_depth": 0.75,
    "timeliness": 0.95,
    "community_heat": 0.85,
    "domain_match": 0.80
  },
  "analyzed_at": "2026-05-03T09:00:00Z"
}
```

---

## 阶段三：管理

### 1. 质量门控

`score < 6.0` 的条目**丢弃**，不生成知识条目。

### 2. 生成知识条目

通过质量门控的每条 item，生成独立文件：

路径：`knowledge/articles/{YYYY-MM-DD}-ph-{slug}.json`

slug 规则：取产品名称转小写，空格换连字符，仅保留字母数字连字符，最长 40 字符。

```json
{
  "id": "producthunt-daily-2026-05-03-{slug}",
  "title": "产品名称",
  "source": "producthunt-daily",
  "url": "https://www.producthunt.com/posts/...",
  "website": "https://...",
  "collected_at": "2026-05-03T08:00:00Z",
  "summary": "中文摘要",
  "tags": ["tag1", "tag2"],
  "score": 8.2,
  "votes": 850
}
```

### 3. 更新 index.json

路径：`knowledge/articles/index.json`

若文件已存在，按 `url` 去重后**追加**新条目，更新 `updated_at` 和 `total`：

```json
{
  "updated_at": "2026-05-03T10:00:00Z",
  "total": 30,
  "articles": [
    {
      "id": "producthunt-daily-2026-05-03-toolname",
      "title": "ToolName",
      "source": "producthunt-daily",
      "url": "https://www.producthunt.com/posts/toolname",
      "tags": ["ai-assistant", "developer-tools"],
      "score": 8.2,
      "votes": 850,
      "file": "knowledge/articles/2026-05-03-ph-toolname.json"
    }
  ]
}
```

### 4. 完成汇报

管理阶段结束后输出统计：

```
采集：X 条原始数据
过滤后：Y 条通过质量门控（score >= 6.0）
丢弃：Z 条（score < 6.0）
新增知识条目：Y 个文件
index.json 当前总条目：N
```

---

## 错误处理

| 错误 | 处理策略 |
|------|----------|
| 401 认证失败 | 检查 `PRODUCTHUNT_TOKEN` 是否设置，提示用户前往 PH 开发者后台获取，终止采集 |
| 429 限速 | 等待 30 秒后重试，最多 3 次 |
| 空结果（今日无产品） | 可能是时区问题（PH 以 PST 为准），尝试将日期改为昨日重试；仍为空则写入 `items: []` 并报告 |
| GraphQL 错误 | 打印 `errors` 字段内容，跳过本次采集，不中断整体流程 |
| 网络超时（> 15s） | 重试最多 3 次，失败则记录到 `knowledge/raw/errors-{date}.json` |
| 分析阶段 JSON 解析失败 | 标记 `score: 0`，`summary: "[分析失败]"`，继续处理下一条 |
