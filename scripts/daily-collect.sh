#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/wushengqiang/PycharmProjects/ai-knowledge-base"
PYTHON="/opt/miniconda3/bin/python3"
LOG_FILE="$PROJECT_DIR/logs/cron.log"

cd "$PROJECT_DIR"

# 加载环境变量
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 开始采集 =====" >> "$LOG_FILE"

$PYTHON pipeline/pipeline.py \
  --sources github,hackernews \
  --limit 20 \
  --verbose >> "$LOG_FILE" 2>&1

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 采集完成 =====" >> "$LOG_FILE"
