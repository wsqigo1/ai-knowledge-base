# CLAUDE.md — AI 知识库项目

> 本文件是项目的"记忆"——Claude Code 启动时自动加载，指导所有 Agent 的行为和代码规范。

## 项目定义

**AI Knowledge Base（AI 知识库）** 是一个自动化技术情报收集与分析系统。
它持续追踪 GitHub Trending、Hacker News、arXiv 等来源，将分散的技术资讯
转化为结构化、可检索的知识条目。

### 核心价值
- 每日自动采集 AI/LLM/Agent 领域的高质量技术文章与开源项目
- 通过 Agent 协作完成 **采集 → 分析 → 整理** 三阶段流水线
- 输出格式统一的 JSON 知识条目，便于下游应用消费

## 项目结构

```
ai-knowledge-base/
├── CLAUDE.md                          # 项目记忆文件（本文件）
├── .env.example                       # 环境变量模板
├── README.md                          # 使用说明
├── .claude/
│   ├── agents/
│   │   ├── collector.md               # 采集 Agent 角色定义
│   │   ├── analyzer.md                # 分析 Agent 角色定义
│   │   └── organizer.md               # 整理 Agent 角色定义
│   └── skills/
│       ├── github-trending/SKILL.md   # GitHub Trending 采集技能
│       ├── hackernews/SKILL.md        # Hacker News 采集技能
│       └── tech-summary/SKILL.md      # 技术摘要生成技能
├── scripts/
│   ├── collect.py                     # 采集脚本
│   ├── analyze.py                     # 分析脚本
│   └── organize.py                    # 整理脚本
└── knowledge/
    ├── raw/                           # 原始采集数据（JSON）
    └── articles/                      # 整理后的知识条目（JSON）
        └── index.json                 # 全量索引文件
```

## 编码规范

### 文件命名
- 原始数据：`knowledge/raw/{source}-{YYYY-MM-DD}.json`
  - 例：`knowledge/raw/github-trending-2026-05-03.json`
  - 例：`knowledge/raw/hackernews-top-2026-05-03.json`
- 知识条目：`knowledge/articles/{YYYY-MM-DD}-{slug}.json`
  - 例：`knowledge/articles/2026-05-03-openai-agents-sdk.json`
- 索引文件：`knowledge/articles/index.json`

### JSON 格式
- 使用 2 空格缩进
- 日期格式：ISO 8601（`YYYY-MM-DDTHH:mm:ssZ`）
- 字符编码：UTF-8
- 每个知识条目必须包含以下字段：

```json
{
  "id": "github-trending-2026-05-03-001",
  "title": "项目或文章标题",
  "source": "github-trending",
  "url": "https://github.com/...",
  "collected_at": "2026-05-03T08:00:00Z",
  "summary": "中文摘要，简明描述核心价值与技术要点",
  "tags": ["large-language-model", "agent", "rag"],
  "relevance_score": 0.85
}
```

### 语言约定
- 代码、JSON 键名、文件名、脚本：英文
- 摘要（`summary`）、分析注释、README 正文：中文
- 标签（`tags`）：英文小写，用连字符分隔（如 `large-language-model`）

## 工作流规则

### 三阶段流水线

```
[Collector] ──采集──→ knowledge/raw/
                          │
[Analyzer]  ──分析──→ knowledge/raw/ (enriched，添加 summary / relevance_score)
                          │
[Organizer] ──整理──→ knowledge/articles/ + index.json
```

### Agent 协作规则

1. **单向数据流**：Collector → Analyzer → Organizer，不可反向
2. **职责隔离**：每个 Agent 只操作自己权限范围内的文件
3. **幂等性**：重复运行同一天的采集不应产生重复条目（按 `url` 去重）
4. **质量门控**：`relevance_score < 0.6` 的条目，Organizer 应丢弃
5. **可追溯**：每个条目保留 `url` 和 `collected_at` 用于溯源

### 在 Claude Code 中调用各阶段

直接在对话中描述任务，Claude Code 会委派对应的子 Agent：

```
# 采集
采集今天的 GitHub Trending 数据，写入 knowledge/raw/

# 分析
分析 knowledge/raw/github-trending-2026-05-03.json，补充 summary 和 relevance_score

# 整理
整理今天所有已分析的原始数据，生成知识条目并更新 index.json
```

也可以要求一次性完成完整流水线：

```
执行今天的完整采集→分析→整理流水线
```

### 错误处理
- 网络请求失败时，记录错误并跳过该条目，不中断整体流程
- API 限流时，等待后重试，最多 3 次
- 数据格式异常时，写入 `knowledge/raw/errors-{YYYY-MM-DD}.json` 供人工排查

## 技术栈
- **运行时**：Claude Code + Claude API（claude-sonnet-4-6 / claude-haiku-4-5）
- **脚本语言**：Python 3.11+
- **数据源**：GitHub API v3、Hacker News API（Firebase）、arXiv API
- **输出格式**：JSON
- **版本管理**：Git

## 环境变量

```bash
ANTHROPIC_API_KEY=sk-ant-...     # Claude API 密钥
GITHUB_TOKEN=ghp_...             # GitHub API Token（提升限流上限）
```

## 注意事项
- 不要在代码中硬编码 API Key，始终从环境变量读取
- `knowledge/` 目录下的 JSON 文件不应提交到 Git（已加入 .gitignore）
- 每次运行前确认 `ANTHROPIC_API_KEY` 已设置
