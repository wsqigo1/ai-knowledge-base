---
name: tech-summary
description: 对 knowledge/raw/ 下的原始采集条目调用 Claude API 生成中文摘要、提取标签、计算相关性评分，将结果回写到原始 JSON 文件（enriched）。
---

# Skill: 技术摘要生成

## 用途

对原始采集条目生成中文技术摘要、提取标签、计算相关性评分，
将结果回写到 `knowledge/raw/` 原始文件（enriched），供 Organizer 阶段消费。

## 触发方式

用户说"分析原始数据"、"生成摘要"、"enriched 数据"时使用本技能。

## 执行步骤

### 1. 读取原始数据

读取 `knowledge/raw/{source}-{date}.json`，遍历 `items` 数组，
跳过已有 `analyzed_at` 字段的条目（幂等）。

### 2. 构造 Prompt

对每条 item 调用 Claude API（`claude-haiku-4-5-20251001`）：

```
system:
你是一位 AI/LLM 技术研究员，专注于评估开源项目和技术文章对 AI 工程师的实际价值。

user:
请分析以下技术条目，返回严格 JSON 格式（不要 markdown 代码块）。

标题：{title}
描述：{description 或空}
链接：{url}
README 摘录：{readme_excerpt 或"无"}

返回格式：
{
  "summary": "100-200字中文摘要",
  "tags": ["tag1", "tag2"],
  "score": 8.5,
  "score_breakdown": {
    "practical_value": 0.90,
    "technical_depth": 0.80,
    "timeliness": 0.85,
    "community_heat": 0.90,
    "domain_match": 1.00
  }
}
```

### 3. 摘要写作规范

摘要须遵循三层结构，**100-200 字**，中文，技术术语保留英文：

1. **定位问题**：这是什么，解决了什么痛点
2. **阐述方案**：核心技术实现或方法
3. **评估价值**：适用场景、社区接受度、与现有方案对比

写作要求：
- 直接点明核心，**不要**以"这是一个…""该项目…"等模板句式开头
- 用具体数字而非空洞形容词（"支持 128k 上下文" 而非 "支持超长上下文"）
- 不照搬 description 原文，要有独立分析判断

### 4. 评分规范

五维加权公式：

```
score = (实用价值(×0.30) + 技术深度(×0.25) + 时效性(×0.20) + 社区热度(×0.15) + 领域匹配(×0.10)) × 10
```

取值范围：1.0-10.0。

各维度评分标准（0.0-1.0）：

| 维度 | 高分标准 | 低分标准 |
|------|----------|----------|
| 实用价值 | 可直接用于生产，有 API/SDK | 概念验证，无法直接使用 |
| 技术深度 | 有原创架构/算法/论文 | 无技术内容，纯资讯 |
| 时效性 | 最近 7 天发布或重大更新 | 旧内容重新传播 |
| 社区热度 | stars>1000 或 HN score>200 | stars<100 或 score<50 |
| 领域匹配 | 核心 LLM/Agent/RAG/MCP 方向 | 周边相关（数据处理、部署工具等） |

**批量处理原则**：每条条目独立打绝对分，不要因为同批次条目多而整体压低评分，
也不要因为条目少而整体抬高——避免相对排名造成的评分扭曲。

### 5. 调用规范

- 模型：`claude-haiku-4-5-20251001`
- 并发：最多 5 个并发请求
- 开启 Prompt Cache：system prompt 加 `cache_control: {"type": "ephemeral"}`
- 超时：单次请求 30 秒

```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=512,
    system=[{
        "type": "text",
        "text": "你是一位 AI/LLM 技术研究员...",
        "cache_control": {"type": "ephemeral"}
    }],
    messages=[{"role": "user", "content": prompt}]
)
```

### 6. 解析与回写

解析返回的 JSON，将以下字段写回原始 item（直接修改 `knowledge/raw/` 文件，不新建文件）：

```json
{
  "summary": "...",
  "tags": ["rag", "vector-search"],
  "score": 8.2,
  "score_breakdown": {
    "practical_value": 0.85,
    "technical_depth": 0.80,
    "timeliness": 0.75,
    "community_heat": 0.90,
    "domain_match": 0.80
  },
  "analyzed_at": "2026-05-03T09:00:00Z"
}
```

### 7. 标签规范

- 全部小写，用连字符分隔，每条 3-5 个
- 优先使用标准标签池：

```
large-language-model  agent             rag              mcp
vector-database       fine-tuning       prompt-engineering  multimodal
code-generation       open-source       benchmark        reasoning
embeddings            multi-agent       tool-use         agent-framework
```

新增标签须遵循小写连字符格式，不得使用缩写（`llm` → `large-language-model`）。

## 错误处理

| 错误 | 处理策略 |
|------|----------|
| 返回非 JSON | 重试一次；仍失败则 `summary: "[分析失败]"`，`score: 0` |
| API 限速（429） | 等待 10 秒后重试，最多 3 次 |
| 单条超时（>30s） | 标记失败，继续处理下一条，不中断整批 |
