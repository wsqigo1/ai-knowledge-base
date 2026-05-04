# AI 知识库 · 项目远景 v0.2

## 要做什么

### 数据源
- GitHub Trending（每日）
- Hacker News（每日）
- arXiv（每日）

### 采集与过滤
- 关键词初筛：`llm`、`ai`、`agent`（不区分大小写）
- AI 二次判断：去除关键词误匹配（如 `bonsai`、`email`）
- 跨源去重：按 `url` 字段去重，同一项目多源出现只保留一条

### 分析输出（每条知识条目）
- `summary`：3 句话，覆盖"是什么 / 用了什么技术 / 为什么值得关注"，写给自己看
- `relevance_score`：0–1 置信度，< 0.6 标记为需人工审核
- `tags`：英文关键词标签

### 运行机制
- 每天 UTC 00:00 自动触发完整流水线
- 数据保留：滚动 7 天，过期自动清理

## 不做什么

- **不做展示层**：JSON 文件是最终交付物，无网站/App/RSS（后续迭代）
- **不做搜索功能**：不支持跨条目查询
- **不做历史追踪**：不追踪项目 star 增长等时序变化（后续迭代）
- **不做推送通知**：不发邮件/微信/Slack

## 边界 & 验收

- 每天 UTC 00:00 运行，结束后 `knowledge/raw/` 下有当日文件
- 每条条目包含：`title`、`url`、`summary`、`relevance_score`、`tags`、`collected_at`
- `relevance_score < 0.6` 的条目写入文件但标记为待审核，不自动进入 `knowledge/articles/`

## 怎么验证

1. 早上打开 `knowledge/raw/`，有 3 个当日文件（github / hackernews / arxiv）
2. 随机抽 5 条 score ≥ 0.6 的条目，摘要内容与项目实际相符
3. 随机抽 5 条 score < 0.6 的条目，确认确实是低质量或无关内容

## MVP 目标日期

2026-05-04（今天）
