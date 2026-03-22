#!/bin/bash
# TabCut 每日自动选品脚本
# 用法: crontab 设置每天定时运行

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="/opt/homebrew/bin/python3"
LOG_FILE="$SCRIPT_DIR/output/run_$(date +%Y-%m-%d).log"

echo "========================================" >> "$LOG_FILE"
echo "开始运行: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"

# 1. 抓取数据
echo "[1/4] 抓取数据..." >> "$LOG_FILE"
$PYTHON tabcut_scraper.py >> "$LOG_FILE" 2>&1

# 2. 生成报告
echo "[2/4] 生成报告..." >> "$LOG_FILE"
$PYTHON generate_report.py >> "$LOG_FILE" 2>&1

# 3. 推送到 GitHub Pages
echo "[3/4] 推送到 GitHub Pages..." >> "$LOG_FILE"
git add docs/ >> "$LOG_FILE" 2>&1
git add -u >> "$LOG_FILE" 2>&1
if git diff --cached --quiet; then
    echo "   无变更，跳过提交" >> "$LOG_FILE"
else
    git commit -m "Daily report $(date +%Y-%m-%d)" >> "$LOG_FILE" 2>&1
    git push origin main >> "$LOG_FILE" 2>&1
fi

# 4. 钉钉推送
echo "[4/4] 钉钉推送..." >> "$LOG_FILE"
$PYTHON notify_dingtalk.py >> "$LOG_FILE" 2>&1

echo "完成: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"
