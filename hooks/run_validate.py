#!/usr/bin/env python3
"""
Claude Code PostToolUse hook 入口。
读取 stdin 中的 hook JSON，对 knowledge/articles/*.json 执行格式校验和质量检查，
通过 systemMessage 将结果反馈给用户。
"""

import json
import sys
import subprocess
import os

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))


def run_script(script: str, filepath: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, os.path.join(HOOKS_DIR, script), filepath],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(HOOKS_DIR),
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode, output


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    file_path = data.get("tool_input", {}).get("file_path", "")

    if "knowledge/articles/" not in file_path or not file_path.endswith(".json"):
        sys.exit(0)

    # 格式校验
    code, out = run_script("validate_json.py", file_path)
    if code != 0:
        print(json.dumps({"systemMessage": f"[validate] ❌ 格式校验失败\n{out}"}))
        sys.exit(0)

    # 质量检查
    code, out = run_script("check_quality.py", file_path)
    if code != 0:
        print(json.dumps({"systemMessage": f"[quality] ⚠️ 质量评分偏低\n{out}"}))


if __name__ == "__main__":
    main()
