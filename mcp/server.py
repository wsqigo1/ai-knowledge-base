#!/usr/bin/env python3
"""MCP Server for AI Knowledge Base — exposes search/get/list tools over stdio."""

import json
import os
import sys
from pathlib import Path

# Ensure the installed 'mcp' SDK is imported, not this local package directory.
_this_dir = str(Path(__file__).parent)
if _this_dir in sys.path:
    sys.path.remove(_this_dir)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

ARTICLES_DIR = Path(__file__).parent.parent / "knowledge" / "articles"

app = Server("ai-knowledge-base")


def _load_articles() -> list[dict]:
    articles = []
    for path in ARTICLES_DIR.glob("*.json"):
        if path.name == "index.json":
            continue
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict) and "id" in data:
                articles.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return articles


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_articles",
            description="按关键词搜索知识库文章的标题和摘要（大小写不敏感）",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "description": "最多返回条数（默认 5）", "default": 5},
                },
                "required": ["keyword"],
            },
        ),
        Tool(
            name="get_article",
            description="根据文章 ID 获取完整内容",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "文章 ID，如 kb-2026-05-03-001"},
                },
                "required": ["id"],
            },
        ),
        Tool(
            name="list_articles",
            description="列出知识库文章，可按 source 或 tag 过滤",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "来源筛选，如 github-trending、hackernews-top"},
                    "tag": {"type": "string", "description": "标签筛选，如 agent、rag"},
                    "limit": {"type": "integer", "description": "最多返回条数（默认 20）", "default": 20},
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "search_articles":
        return _search_articles(arguments.get("keyword", ""), int(arguments.get("limit", 5)))
    if name == "get_article":
        return _get_article(arguments.get("id", ""))
    if name == "list_articles":
        return _list_articles(
            arguments.get("source"),
            arguments.get("tag"),
            int(arguments.get("limit", 20)),
        )
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


def _search_articles(keyword: str, limit: int) -> list[TextContent]:
    kw = keyword.lower()
    results = []
    for article in _load_articles():
        title = article.get("title", "").lower()
        summary = article.get("summary", "").lower()
        if kw in title or kw in summary:
            results.append(article)
    results.sort(key=lambda a: a.get("score", 0), reverse=True)
    results = results[:limit]

    if not results:
        return [TextContent(type="text", text=f"没有找到包含「{keyword}」的文章。")]

    lines = [f"找到 {len(results)} 篇相关文章：\n"]
    for a in results:
        summary_preview = (a.get("summary") or "")[:100]
        lines.append(
            f"**{a['id']}** — {a.get('title', '')}\n"
            f"  来源: {a.get('source', '')} | 评分: {a.get('score', '')} | 标签: {', '.join(a.get('tags', []))}\n"
            f"  URL: {a.get('url', '')}\n"
            f"  摘要: {summary_preview}{'…' if len(a.get('summary', '')) > 100 else ''}\n"
        )
    return [TextContent(type="text", text="\n".join(lines))]


def _get_article(article_id: str) -> list[TextContent]:
    for article in _load_articles():
        if article.get("id") == article_id:
            return [TextContent(type="text", text=json.dumps(article, ensure_ascii=False, indent=2))]
    return [TextContent(type="text", text=f"未找到 ID 为「{article_id}」的文章。")]


def _list_articles(source: str | None, tag: str | None, limit: int) -> list[TextContent]:
    articles = _load_articles()
    if source:
        articles = [a for a in articles if a.get("source") == source]
    if tag:
        articles = [a for a in articles if tag in a.get("tags", [])]
    articles.sort(key=lambda a: a.get("score", 0), reverse=True)
    articles = articles[:limit]

    if not articles:
        return [TextContent(type="text", text="没有找到符合条件的文章。")]

    lines = [f"共 {len(articles)} 篇文章：\n"]
    for a in articles:
        lines.append(
            f"**{a['id']}** — {a.get('title', '')}\n"
            f"  来源: {a.get('source', '')} | 评分: {a.get('score', '')} | 标签: {', '.join(a.get('tags', []))}\n"
            f"  URL: {a.get('url', '')}\n"
        )
    return [TextContent(type="text", text="\n".join(lines))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
