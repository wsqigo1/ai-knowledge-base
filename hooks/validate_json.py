#!/usr/bin/env python3
"""
JSON 格式校验脚本 — 检查知识库文章是否符合标准格式。

用法：
    python3 hooks/validate_json.py knowledge/articles/2026-05-03-xxx.json
    python3 hooks/validate_json.py knowledge/articles/*.json

退出码：
    0 — 全部通过
    1 — 存在校验失败
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ── 校验规则 ──────────────────────────────────────────────────────────────

# 必填字段及期望类型
REQUIRED_FIELDS: dict[str, type] = {
    "id":           str,
    "title":        str,
    "source":       str,
    "url":          str,
    "collected_at": str,
    "summary":      str,
    "tags":         list,
    "score":        float,
}

# ID 格式：{source}-{YYYY-MM-DD}-{slug}
# 例：github-trending-2026-05-03-openai-swarm
ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]+-\d{4}-\d{2}-\d{2}-.+$")

# score 范围
SCORE_MIN = 1.0
SCORE_MAX = 10.0

# URL 格式
URL_PATTERN = re.compile(r"^https://\S+$")

# 摘要最小长度（字符数）
SUMMARY_MIN_LENGTH = 50


# ── 校验函数 ──────────────────────────────────────────────────────────────

def validate_article(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    # 必填字段存在性 + 类型检查
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(f"缺少必填字段: {field}")
        else:
            # relevance_score 允许 int（也是合法浮点值）
            actual = data[field]
            if field == "score":
                if not isinstance(actual, (int, float)):
                    errors.append(f"字段类型错误: {field} 应为 float，实际为 {type(actual).__name__}")
            elif not isinstance(actual, expected_type):
                errors.append(
                    f"字段类型错误: {field} 应为 {expected_type.__name__}，实际为 {type(actual).__name__}"
                )

    # 有必填字段缺失时，后续校验无意义
    if errors:
        return errors

    # ID 格式
    if not ID_PATTERN.match(data["id"]):
        errors.append(
            f"ID 格式错误: '{data['id']}'，"
            "应为 '{source}-{YYYY-MM-DD}-{slug}'，例：github-trending-2026-05-03-openai-swarm"
        )

    # 标题非空
    if not data["title"].strip():
        errors.append("title 不能为空字符串")

    # URL 格式
    if not URL_PATTERN.match(data["url"]):
        errors.append(f"url 格式错误: '{data['url']}'，须以 https:// 开头且不含空格")

    # collected_at ISO 8601
    try:
        datetime.fromisoformat(data["collected_at"].replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"collected_at 须为 ISO 8601 格式，当前值: '{data['collected_at']}'")

    # 摘要长度
    summary_len = len(data["summary"].strip())
    if summary_len < SUMMARY_MIN_LENGTH:
        errors.append(f"summary 太短: {summary_len} 字，至少需要 {SUMMARY_MIN_LENGTH} 字")

    # 标签非空且元素均为非空字符串
    tags = data["tags"]
    if len(tags) == 0:
        errors.append("tags 不能为空数组")
    else:
        for i, tag in enumerate(tags):
            if not isinstance(tag, str) or not tag.strip():
                errors.append(f"tags[{i}] 格式错误: '{tag}'")

    # score 范围
    score = data["score"]
    if not (SCORE_MIN <= score <= SCORE_MAX):
        errors.append(
            f"score 超出范围: {score}，允许范围: {SCORE_MIN}-{SCORE_MAX}"
        )

    return errors


# ── CLI 入口 ──────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python3 hooks/validate_json.py <json_file> [json_file2 ...]")
        print("示例: python3 hooks/validate_json.py knowledge/articles/*.json")
        return 1

    total = 0
    failed = 0
    all_errors: dict[str, list[str]] = {}

    for filepath in sys.argv[1:]:
        path = Path(filepath)
        if not path.exists():
            print(f"[SKIP] 文件不存在: {filepath}")
            continue
        if path.suffix != ".json":
            print(f"[SKIP] 非 JSON 文件: {filepath}")
            continue
        if path.name == "index.json":
            continue

        total += 1
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            all_errors[filepath] = [f"JSON 解析失败: {e}"]
            failed += 1
            continue

        errs = validate_article(data)
        if errs:
            all_errors[filepath] = errs
            failed += 1

    # 汇总报告
    print(f"\n{'=' * 50}")
    print("JSON 格式校验结果")
    print(f"{'=' * 50}")

    if all_errors:
        for filepath, errs in all_errors.items():
            print(f"\n[FAIL] {filepath}")
            for e in errs:
                print(f"  - {e}")
    else:
        print("\n[PASS] 所有文件校验通过")

    print(f"\n总计: {total} 文件，{total - failed} 通过，{failed} 失败")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
