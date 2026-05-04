"""
AI 知识库四步流水线：采集 → 分析 → 整理 → 保存

运行方式：
    python3 pipeline/pipeline.py --sources github,hackernews --limit 20
    python3 pipeline/pipeline.py --sources github --limit 5 --dry-run
    python3 pipeline/pipeline.py --step 1 --step 2 --sources github
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from model_client import create_provider, chat_with_retry, estimate_cost

load_dotenv()
logger = logging.getLogger(__name__)

# ── 项目路径 ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR      = PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"
INDEX_FILE   = ARTICLES_DIR / "index.json"

# ── 标准标签池（与 CLAUDE.md 保持一致） ──────────────────────────────────

STANDARD_TAGS = [
    "large-language-model", "agent", "rag", "vector-database", "fine-tuning",
    "prompt-engineering", "multimodal", "code-generation", "benchmark",
    "reasoning", "multi-agent", "tool-use", "open-source", "mcp",
    "developer-tools", "workflow-automation", "ai-assistant",
]

# ── Step 1: 采集 ──────────────────────────────────────────────────────────

def collect_github(limit: int = 20) -> list[dict[str, Any]]:
    """从 GitHub Search API 采集近 7 天 AI 热门仓库。"""
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    params = {
        "q": f"AI OR LLM OR agent OR RAG OR MCP created:>{since}",
        "sort": "stars",
        "order": "desc",
        "per_page": min(limit, 50),
    }

    results: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                "https://api.github.com/search/repositories",
                params=params, headers=headers,
            )
            resp.raise_for_status()
            now = datetime.now(timezone.utc).isoformat()

            for i, repo in enumerate(resp.json().get("items", [])[:limit]):
                if not repo.get("description") or repo.get("fork"):
                    continue
                results.append({
                    "title":        repo["full_name"],
                    "source":       "github-trending",
                    "url":          repo["html_url"],
                    "description":  repo.get("description", ""),
                    "stars":        repo.get("stargazers_count", 0),
                    "language":     repo.get("language", ""),
                    "topics":       repo.get("topics", []),
                    "collected_at": now,
                    "published_at": repo.get("pushed_at", now),
                })

        logger.info("GitHub 采集完成: %d 条", len(results))
    except httpx.HTTPError as e:
        logger.error("GitHub API 调用失败: %s", e)

    return results


def collect_hackernews(limit: int = 20) -> list[dict[str, Any]]:
    """从 Hacker News Firebase API 采集 AI 相关热门文章。"""
    AI_KEYWORDS = {
        "ai", "llm", "gpt", "claude", "gemini", "agent", "rag", "embedding",
        "neural", "ml", "machine learning", "deep learning", "transformer",
        "diffusion", "fine-tun", "openai", "anthropic",
    }

    results: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=20.0) as client:
            top_ids = client.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json"
            ).json()[:100]

            now = datetime.now(timezone.utc).isoformat()
            collected = 0

            for story_id in top_ids:
                if collected >= limit:
                    break
                try:
                    item = client.get(
                        f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                    ).json()
                except Exception:
                    continue

                if item.get("type") != "story" or not item.get("title"):
                    continue

                hn_score = item.get("score", 0)
                title_lower = item["title"].lower()
                is_ai = any(kw in title_lower for kw in AI_KEYWORDS)

                if not is_ai and hn_score < 100:
                    continue

                url = item.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
                results.append({
                    "title":        item["title"],
                    "source":       "hackernews-top",
                    "url":          url,
                    "hn_url":       f"https://news.ycombinator.com/item?id={story_id}",
                    "description":  "",
                    "hn_score":     hn_score,
                    "comments":     item.get("descendants", 0),
                    "collected_at": now,
                    "published_at": now,
                })
                collected += 1

        logger.info("HN 采集完成: %d 条", len(results))
    except httpx.HTTPError as e:
        logger.error("HN API 调用失败: %s", e)

    return results


def step_collect(sources: list[str], limit: int) -> list[dict[str, Any]]:
    print(f"\n{'='*60}")
    print(f"  Step 1: 采集  sources={sources}  limit={limit}")
    print(f"{'='*60}")

    all_items: list[dict[str, Any]] = []
    if "github" in sources:
        all_items.extend(collect_github(limit))
    if "hackernews" in sources:
        all_items.extend(collect_hackernews(limit))

    # 写入原始文件（按 source 分组）
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    by_source: dict[str, list] = {}
    for item in all_items:
        by_source.setdefault(item["source"], []).append(item)

    for source, items in by_source.items():
        raw_file = RAW_DIR / f"{source}-{date_str}.json"
        # 幂等：已存在则按 url 去重后追加
        existing: list[dict] = []
        if raw_file.exists():
            with open(raw_file, encoding="utf-8") as f:
                data = json.load(f)
            existing = data.get("items", [])
        seen = {i["url"] for i in existing}
        new_items = [i for i in items if i["url"] not in seen]
        payload = {
            "source":       source,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "date":         date_str,
            "count":        len(existing) + len(new_items),
            "items":        existing + new_items,
        }
        with open(raw_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"  [{source}] {len(new_items)} 条新数据 → {raw_file.name}")

    print(f"  共采集 {len(all_items)} 条")
    return all_items


# ── Step 2: 分析 ──────────────────────────────────────────────────────────

ANALYZE_SYSTEM = "你是一个 AI/LLM 技术研究员，专注于评估开源项目和技术文章对 AI 工程师的实际价值。"

ANALYZE_PROMPT = """请分析以下技术条目，返回严格 JSON 格式（不要 markdown 代码块）。

标题：{title}
来源：{source}
描述：{description}
附加信息：{extra}

返回格式：
{{
  "summary": "100-200字中文摘要，结构：是什么→解决什么问题→核心技术亮点→适用场景",
  "tags": ["tag1", "tag2"],
  "score": 7.5
}}

评分公式（结果乘以 10，范围 1.0-10.0）：
  实用价值(×0.30) + 技术深度(×0.25) + 时效性(×0.20) + 社区热度(×0.15) + 领域匹配(×0.10)

优先从标准标签池选取（3-5 个）：
{tags}

摘要要求：技术术语保留英文，直接切入核心，禁用模板句式开头。"""


def step_analyze(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    print(f"\n{'='*60}")
    print(f"  Step 2: 分析  {len(items)} 条")
    print(f"{'='*60}")

    provider = create_provider()
    analyzed: list[dict[str, Any]] = []
    total_cost = 0.0
    tags_hint = "  ".join(STANDARD_TAGS)

    # 加载已分析的 url 集合（幂等：跳过 raw 文件中已有 analyzed_at 的条目）
    already_analyzed: set[str] = set()
    date_str = datetime.now().strftime("%Y-%m-%d")
    by_source_urls: dict[str, set[str]] = {}
    for item in items:
        src = item["source"]
        if src not in by_source_urls:
            raw_file = RAW_DIR / f"{src}-{date_str}.json"
            if raw_file.exists():
                with open(raw_file, encoding="utf-8") as f:
                    raw_data = json.load(f)
                by_source_urls[src] = {
                    r["url"] for r in raw_data.get("items", []) if "analyzed_at" in r
                }
            else:
                by_source_urls[src] = set()
        already_analyzed.update(by_source_urls[src])

    try:
        for i, item in enumerate(items):
            if item["url"] in already_analyzed:
                print(f"  [{i+1}/{len(items)}] [跳过已分析] {item['title'][:50]}")
                analyzed.append(item)
                continue
            print(f"  [{i+1}/{len(items)}] {item['title'][:55]}...")

            extra_parts = []
            if item.get("stars"):
                extra_parts.append(f"Stars: {item['stars']}")
            if item.get("hn_score"):
                extra_parts.append(f"HN Score: {item['hn_score']}")
            if item.get("language"):
                extra_parts.append(f"Language: {item['language']}")
            if item.get("topics"):
                extra_parts.append(f"Topics: {', '.join(item['topics'][:5])}")

            prompt = ANALYZE_PROMPT.format(
                title=item["title"],
                source=item["source"],
                description=item.get("description", "无描述"),
                extra="; ".join(extra_parts) or "无",
                tags=tags_hint,
            )

            try:
                response = chat_with_retry(
                    provider,
                    messages=[{"role": "user", "content": prompt}],
                    system=ANALYZE_SYSTEM,
                    temperature=0.3,
                    max_tokens=600,
                )
                total_cost += estimate_cost(provider.model, response.usage)

                raw = response.content.strip()
                # 优先提取第一个完整 JSON 对象，兼容 markdown 包裹和尾部多余文字
                m = re.search(r"\{.*?\}", raw, re.DOTALL)
                if not m:
                    raise json.JSONDecodeError("no JSON object found", raw, 0)
                analysis = json.loads(m.group())

                enriched = {
                    **item,
                    "summary":     analysis.get("summary", ""),
                    "tags":        analysis.get("tags", ["large-language-model"])[:5],
                    "score":       max(1.0, min(10.0, float(analysis.get("score", 5.0)))),
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                }

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning("分析失败 [%s]: %s", item["title"][:40], e)
                enriched = {
                    **item,
                    "summary":     item.get("description", "")[:200],
                    "tags":        ["large-language-model"],
                    "score":       5.0,
                    "analyzed_at": datetime.now(timezone.utc).isoformat(),
                }

            analyzed.append(enriched)

    finally:
        provider.close()

    # 回写分析结果到 raw 文件（按 source 分组，按 url 匹配）
    _writeback_analyzed(analyzed)

    print(f"  分析完成: {len(analyzed)} 条，估算成本: ${total_cost:.6f}")
    return analyzed


def _writeback_analyzed(items: list[dict[str, Any]]) -> None:
    """将 summary/tags/score/analyzed_at 回写到对应的 raw 文件。"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    # 按 source 分桶，建立 url → analysis 映射
    by_source: dict[str, dict[str, dict]] = {}
    for item in items:
        source = item["source"]
        by_source.setdefault(source, {})[item["url"]] = {
            "summary":     item.get("summary", ""),
            "tags":        item.get("tags", []),
            "score":       item.get("score", 5.0),
            "analyzed_at": item.get("analyzed_at", ""),
        }

    for source, url_map in by_source.items():
        raw_file = RAW_DIR / f"{source}-{date_str}.json"
        if not raw_file.exists():
            continue
        with open(raw_file, encoding="utf-8") as f:
            data = json.load(f)
        changed = False
        for raw_item in data.get("items", []):
            patch = url_map.get(raw_item.get("url", ""))
            if patch and "analyzed_at" not in raw_item:
                raw_item.update(patch)
                changed = True
        if changed:
            with open(raw_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)


# ── Step 3: 整理 ──────────────────────────────────────────────────────────

def _next_id(date_str: str) -> str:
    """从 index.json 计算当天下一个可用 ID。"""
    if not INDEX_FILE.exists():
        return f"kb-{date_str}-001"
    with open(INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)
    prefix = f"kb-{date_str}-"
    nums = [
        int(e["id"][len(prefix):])
        for e in index.get("entries", [])
        if e.get("id", "").startswith(prefix) and e["id"][len(prefix):].isdigit()
    ]
    return f"{prefix}{(max(nums) + 1 if nums else 1):03d}"


def step_organize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    print(f"\n{'='*60}")
    print(f"  Step 3: 整理  {len(items)} 条")
    print(f"{'='*60}")

    # 已有文章 URL（去重用）
    seen_urls: set[str] = set()
    if ARTICLES_DIR.exists():
        for f in ARTICLES_DIR.glob("*.json"):
            if f.name == "index.json":
                continue
            try:
                with open(f, encoding="utf-8") as fh:
                    seen_urls.add(json.load(fh).get("url", ""))
            except (json.JSONDecodeError, IOError):
                pass

    date_str = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()
    organized: list[dict[str, Any]] = []
    dropped = 0

    for item in items:
        url = item.get("url", "")

        # 质量门控
        if item.get("score", 0) < 6.0:
            logger.info("丢弃（score=%.1f）: %s", item.get("score", 0), item["title"][:40])
            dropped += 1
            continue

        # 去重
        if url in seen_urls:
            logger.info("跳过重复: %s", item["title"][:40])
            dropped += 1
            continue
        seen_urls.add(url)

        article_id = _next_id(date_str)
        # 让 _next_id 下次调用返回更大序号（临时注册到 index 供本批次去重）
        # 实际写入由 step_save 完成

        organized.append({
            "id":           article_id,
            "title":        item["title"],
            "source":       item["source"],
            "url":          url,
            "summary":      item.get("summary", ""),
            "tags":         item.get("tags", []),
            "score":        round(item.get("score", 5.0), 1),
            "collected_at": item.get("collected_at", now),
            "analyzed_at":  item.get("analyzed_at", now),
            "organized_at": now,
            "status":       "published",
        })

    print(f"  通过质量门控: {len(organized)} 条，丢弃: {dropped} 条")
    return organized


# ── Step 4: 保存 ──────────────────────────────────────────────────────────

def _slug(title: str) -> str:
    """生成文件名 slug（最长 40 字符）。"""
    s = re.sub(r"[^\w\s-]", "", title.lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s[:40]


def step_save(items: list[dict[str, Any]], dry_run: bool = False) -> list[Path]:
    print(f"\n{'='*60}")
    print(f"  Step 4: 保存  {len(items)} 条  dry_run={dry_run}")
    print(f"{'='*60}")

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    date_str = datetime.now().strftime("%Y-%m-%d")

    # 重新分配 ID（避免批内冲突）
    if not dry_run:
        _reassign_ids(items, date_str)

    for item in items:
        filename = f"{date_str}-{_slug(item['title'])}.json"
        filepath = ARTICLES_DIR / filename

        if dry_run:
            print(f"  [DRY RUN] {filename}")
        else:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False, indent=2)
            saved.append(filepath)
            print(f"  已保存: {filename}")

    if not dry_run:
        _update_index(items, date_str)
        print(f"  index.json 已更新（+{len(items)} 条）")

    return saved


def _reassign_ids(items: list[dict], date_str: str) -> None:
    """为本批次文章分配不冲突的顺序 ID。"""
    if not INDEX_FILE.exists():
        base = 0
    else:
        with open(INDEX_FILE, encoding="utf-8") as f:
            index = json.load(f)
        prefix = f"kb-{date_str}-"
        nums = [
            int(e["id"][len(prefix):])
            for e in index.get("entries", [])
            if e.get("id", "").startswith(prefix) and e["id"][len(prefix):].isdigit()
        ]
        base = max(nums) if nums else 0

    for i, item in enumerate(items):
        item["id"] = f"kb-{date_str}-{base + i + 1:03d}"


def _update_index(items: list[dict], date_str: str) -> None:
    """增量追加到 index.json，不重写整个文件。"""
    if INDEX_FILE.exists():
        with open(INDEX_FILE, encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {"last_updated": "", "total_count": 0, "entries": []}

    existing_urls = {e.get("url") for e in index["entries"]}
    new_entries = []

    for item in items:
        if item.get("url") in existing_urls:
            continue
        filename = f"{date_str}-{_slug(item['title'])}.json"
        new_entries.append({
            "id":           item["id"],
            "title":        item["title"],
            "source":       item["source"],
            "url":          item["url"],
            "file":         filename,
            "tags":         item["tags"],
            "score":        item["score"],
            "organized_at": item["organized_at"],
        })

    index["entries"] = new_entries + index["entries"]  # 最新在前
    index["total_count"] = len(index["entries"])
    index["last_updated"] = datetime.now(timezone.utc).isoformat()

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


# ── 主流程 ────────────────────────────────────────────────────────────────

def run_pipeline(
    sources: list[str],
    limit: int = 20,
    dry_run: bool = False,
    steps: list[int] | None = None,
) -> dict[str, Any]:
    run_steps = set(steps) if steps else {1, 2, 3, 4}
    start = datetime.now()

    print(f"\n{'#'*60}")
    print(f"  AI 知识库流水线  {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  sources={sources}  limit={limit}  dry_run={dry_run}")
    print(f"  steps={sorted(run_steps)}")
    print(f"{'#'*60}")

    raw: list[dict] = []
    analyzed: list[dict] = []
    organized: list[dict] = []
    saved: list[Path] = []

    if 1 in run_steps:
        raw = step_collect(sources, limit)
        if not raw:
            print("\n  没有采集到数据，流水线结束。")
            return {"collected": 0, "analyzed": 0, "organized": 0, "saved": 0}

    if 2 in run_steps and raw:
        analyzed = step_analyze(raw)

    if 3 in run_steps and analyzed:
        organized = step_organize(analyzed)

    if 4 in run_steps and organized:
        saved = step_save(organized, dry_run=dry_run)

    elapsed = (datetime.now() - start).total_seconds()
    stats = {
        "collected": len(raw),
        "analyzed":  len(analyzed),
        "organized": len(organized),
        "saved":     len(saved),
        "elapsed_s": round(elapsed, 1),
        "dry_run":   dry_run,
    }

    print(f"\n{'#'*60}")
    print(f"  完成！耗时 {elapsed:.1f}s")
    print(f"  采集 {stats['collected']} → 分析 {stats['analyzed']} "
          f"→ 整理 {stats['organized']} → 保存 {stats['saved']}")
    print(f"{'#'*60}\n")

    return stats


# ── CLI 入口 ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI 知识库采集流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 pipeline/pipeline.py --sources github,hackernews --limit 20
  python3 pipeline/pipeline.py --sources github --limit 5 --dry-run
  python3 pipeline/pipeline.py --step 1 --step 2 --sources hackernews
        """,
    )
    parser.add_argument("--sources", default="github,hackernews",
                        help="数据源，逗号分隔（默认: github,hackernews）")
    parser.add_argument("--limit", type=int, default=20,
                        help="每个源的最大采集数（默认: 20）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅模拟，不实际保存文件")
    parser.add_argument("--verbose", action="store_true",
                        help="显示详细日志")
    parser.add_argument("--step", type=int, action="append",
                        help="指定步骤（1-4），可多次使用")
    parser.add_argument("--provider",
                        help="覆盖 LLM_PROVIDER 环境变量")

    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    run_pipeline(
        sources=[s.strip() for s in args.sources.split(",")],
        limit=args.limit,
        dry_run=args.dry_run,
        steps=args.step,
    )


if __name__ == "__main__":
    main()
