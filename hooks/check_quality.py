#!/usr/bin/env python3
"""检查知识条目内容质量，评级低于 B 时输出警告并以非零退出。

五维评分（总分 100）：
  摘要质量(25) + 技术深度(25) + 格式规范(20) + 标签精度(15) + 空洞词检测(15)

评级：A≥80 / B≥60 / C<60
"""

import json
import re
import sys
import os

HOLLOW_WORDS = [
    "非常", "很", "极其", "十分", "相当", "非常好", "很好",
    "excellent", "amazing", "incredible", "revolutionary", "groundbreaking",
    "best", "greatest", "most powerful",
]

STANDARD_TAGS = {
    "large-language-model", "agent", "rag", "mcp", "vector-database",
    "fine-tuning", "prompt-engineering", "multimodal", "code-generation",
    "open-source", "benchmark", "reasoning", "embeddings", "multi-agent",
    "tool-use", "agent-framework", "developer-tools", "productivity",
    "workflow-automation", "ai-assistant", "no-code", "data-analysis", "nlp",
    "engineering-practice", "image-generation", "voice-ai",
}


def score_summary_quality(summary: str) -> tuple[int, list[str]]:
    """摘要质量：25 分。长度 100-200 字得满分，结构完整加分。"""
    issues = []
    pts = 0
    length = len(summary.strip())

    if 100 <= length <= 200:
        pts += 20
    elif 50 <= length < 100:
        pts += 10
        issues.append(f"摘要偏短（{length} 字，建议 100-200 字）")
    elif length > 200:
        pts += 15
        issues.append(f"摘要偏长（{length} 字，建议 100-200 字）")
    else:
        issues.append(f"摘要过短（{length} 字）")

    # 结构检查：含有「→」或「，」等连接词视为有结构
    if length >= 50 and ("→" in summary or summary.count("，") >= 3):
        pts += 5

    return pts, issues


def score_technical_depth(data: dict) -> tuple[int, list[str]]:
    """技术深度：25 分。score 高且 summary 含技术词。"""
    issues = []
    pts = 0
    score_val = data.get("score", 0)
    summary = data.get("summary", "")

    tech_keywords = [
        "API", "SDK", "RAG", "LLM", "Agent", "embedding", "fine-tun",
        "架构", "算法", "框架", "模型", "推理", "训练", "向量", "上下文",
        "transformer", "attention", "pipeline", "workflow",
    ]
    keyword_hits = sum(1 for kw in tech_keywords if kw.lower() in summary.lower())

    if score_val >= 8.0:
        pts += 15
    elif score_val >= 6.0:
        pts += 10
    else:
        issues.append(f"score {score_val:.1f} 偏低，技术深度不足")

    if keyword_hits >= 3:
        pts += 10
    elif keyword_hits >= 1:
        pts += 5
    else:
        issues.append("摘要缺少技术关键词")

    return pts, issues


def score_format_compliance(data: dict) -> tuple[int, list[str]]:
    """格式规范：20 分。必填字段完整、类型正确、日期合法。"""
    from datetime import datetime
    issues = []
    pts = 20

    required = ["id", "title", "source", "url", "collected_at", "summary", "tags", "score"]
    for field in required:
        if field not in data:
            pts -= 4
            issues.append(f"缺少字段: {field}")

    url = data.get("url", "")
    if url and not url.startswith("https://"):
        pts -= 3
        issues.append("url 未使用 https")

    collected_at = data.get("collected_at", "")
    if collected_at:
        try:
            datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
        except ValueError:
            pts -= 3
            issues.append(f"collected_at 格式非 ISO 8601: {collected_at!r}")

    return max(pts, 0), issues


def score_tag_accuracy(data: dict) -> tuple[int, list[str]]:
    """标签精度：15 分。数量 3-5 个，尽量使用标准标签。"""
    issues = []
    tags = data.get("tags", [])
    count = len(tags)

    if 3 <= count <= 5:
        pts = 10
    elif count == 2 or count == 6:
        pts = 6
        issues.append(f"标签数量 {count} 个（建议 3-5 个）")
    else:
        pts = 0
        issues.append(f"标签数量 {count} 个，不符合要求（建议 3-5 个）")

    if count > 0:
        standard_count = sum(1 for t in tags if t in STANDARD_TAGS)
        ratio = standard_count / count
        if ratio >= 0.6:
            pts += 5
        else:
            non_standard = [t for t in tags if t not in STANDARD_TAGS]
            issues.append(f"非标准标签占比过高: {non_standard}")

    return pts, issues


def score_hollow_words(summary: str) -> tuple[int, list[str]]:
    """空洞词检测：15 分。出现空洞词扣分。"""
    issues = []
    pts = 15
    found = [w for w in HOLLOW_WORDS if w.lower() in summary.lower()]
    if found:
        deduct = min(len(found) * 5, 15)
        pts -= deduct
        issues.append(f"摘要含空洞词: {found}")
    return max(pts, 0), issues


DIMENSIONS = [
    ("摘要质量", score_summary_quality, "summary", 25),
    ("技术深度", score_technical_depth, "data",    25),
    ("格式规范", score_format_compliance, "data",  20),
    ("标签精度", score_tag_accuracy, "data",       15),
    ("空洞词检测", score_hollow_words, "summary",  15),
]


def bar(pts: int, max_pts: int, width: int = 20) -> str:
    filled = round(pts / max_pts * width) if max_pts else 0
    return "█" * filled + "░" * (width - filled)


def check(filepath: str) -> tuple[bool, list[str]]:
    if not os.path.exists(filepath):
        return False, [f"文件不存在: {filepath}"]

    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    summary = data.get("summary", "")
    all_issues: list[str] = []
    total = 0

    for _, fn, arg_key, _ in DIMENSIONS:
        arg = summary if arg_key == "summary" else data
        pts, issues = fn(arg)
        total += pts
        all_issues.extend(issues)

    grade = "A" if total >= 80 else "B" if total >= 60 else "C"
    all_issues.append(f"质量评分: {total}/100，评级: {grade}")

    return grade in ("A", "B"), all_issues


def print_report(filepath: str) -> bool:
    if not os.path.exists(filepath):
        print(f"文件不存在: {filepath}")
        return False

    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    summary = data.get("summary", "")

    results: list[tuple[str, int, int, list[str]]] = []
    total = 0
    all_issues: list[str] = []

    for label, fn, arg_key, max_pts in DIMENSIONS:
        arg = summary if arg_key == "summary" else data
        pts, issues = fn(arg)
        results.append((label, pts, max_pts, issues))
        total += pts
        all_issues.extend(issues)

    grade = "A" if total >= 80 else "B" if total >= 60 else "C"
    grade_color = "\033[92m" if grade == "A" else "\033[93m" if grade == "B" else "\033[91m"
    reset = "\033[0m"

    print(f"\n{'─' * 52}")
    print(f"  质量检查  {os.path.basename(filepath)}")
    print(f"{'─' * 52}")

    for label, pts, max_pts, _ in results:
        pct_bar = bar(pts, max_pts)
        print(f"  {label:<6}  [{pct_bar}]  {pts:>2}/{max_pts}")

    print(f"{'─' * 52}")
    print(f"  总分     [{bar(total, 100)}]  {total:>2}/100  "
          f"评级: {grade_color}{grade}{reset}")
    print(f"{'─' * 52}")

    if all_issues:
        print()
        for issue in all_issues:
            print(f"  ⚠  {issue}")

    print()
    return grade in ("A", "B")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: check_quality.py <filepath>")
        sys.exit(1)

    fp = sys.argv[1]
    if os.path.basename(fp) == "index.json":
        sys.exit(0)

    ok = print_report(fp)
    sys.exit(0 if ok else 1)
