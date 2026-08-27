#!/usr/bin/env bash
# run-live.sh — 一键跑 Harness WS 探针 live 全套（连真实服务，落抓包证据）
# 用法：./run-live.sh [BASE] [USER] [PASSWORD]
#       默认 BASE=http://127.0.0.1:8000 USER=admin PASSWORD=admin123
# 说明：设置 HARNESS_PROBE_* 环境变量后调用 pytest live 套件；
#       任一契约断言失败即退出码非 0，抓包证据自动落盘 traces/live-<时间戳>.jsonl。
set -euo pipefail

BASE="${1:-http://127.0.0.1:8000}"
USER="${2:-admin}"
PASSWORD="${3:-admin123}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export HARNESS_PROBE_BASE="$BASE"
export HARNESS_PROBE_USER="$USER"
export HARNESS_PROBE_PASSWORD="$PASSWORD"

cd "$ROOT/backend/api"
exec python -m pytest tests/test_harness_probe_live.py -v
