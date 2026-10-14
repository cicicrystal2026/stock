#!/bin/bash
# 每日数据更新：抓日线 -> 抓资金流 -> 双策略扫描 -> 回放体检
# 用法：bash deploy/update.sh   （由 cron 每日 16:00 调用，也可手动执行）
set -e
cd "$(dirname "$0")/.."
PY="${PY:-python3}"

echo "=== $(date '+%F %T') 开始更新 ==="
$PY tools/fetch_daily.py
$PY tools/fetch_flow.py
$PY tools/screen.py
$PY tools/replay.py
echo "=== $(date '+%F %T') 更新完成 ==="
