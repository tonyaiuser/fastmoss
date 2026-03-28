#!/bin/bash
# TabCut 每日自动选品脚本
# 用法: crontab 设置每天定时运行

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="/opt/homebrew/bin/python3"
LOG_FILE="$SCRIPT_DIR/output/run_$(date +%Y-%m-%d).log"

log() {
    echo "$1" >> "$LOG_FILE"
}

echo "========================================" >> "$LOG_FILE"
echo "开始运行: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"

# 1. 抓取数据
echo "[1/4] 抓取数据..." >> "$LOG_FILE"
if ! $PYTHON tabcut_scraper.py >> "$LOG_FILE" 2>&1; then
    log "   抓取失败，停止后续步骤（不生成报告、不推送旧页面、不发通知）"
    echo "失败: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
    echo "========================================" >> "$LOG_FILE"
    exit 1
fi

# 2. 生成报告
echo "[2/4] 生成报告..." >> "$LOG_FILE"
$PYTHON generate_report.py >> "$LOG_FILE" 2>&1

# 3. 推送到 GitHub Pages（失败不影响后续通知）
echo "[3/4] 推送到 GitHub Pages..." >> "$LOG_FILE"
set +e

# 不再依赖 cron 环境里临时获取 gh token。
# 直接使用本机已有 git 凭据/钥匙串配置进行 push；
# 若失败，仅记录日志，不影响后续通知。
export GIT_TERMINAL_PROMPT=0

git add docs/ >> "$LOG_FILE" 2>&1
git_add_docs_status=$?
git add -u >> "$LOG_FILE" 2>&1
git_add_u_status=$?

if [ $git_add_docs_status -ne 0 ] || [ $git_add_u_status -ne 0 ]; then
    log "   Git add 失败，跳过 GitHub Pages 推送，但继续执行通知"
else
    if git diff --cached --quiet; then
        log "   无变更，跳过提交"
    else
        git commit -m "Daily report $(date +%Y-%m-%d)" >> "$LOG_FILE" 2>&1
        git_commit_status=$?
        if [ $git_commit_status -ne 0 ]; then
            log "   Git commit 失败，跳过 GitHub Pages 推送，但继续执行通知"
        else
            git push origin main >> "$LOG_FILE" 2>&1
            git_push_status=$?
            if [ $git_push_status -ne 0 ]; then
                log "   Git push 失败（本机 git 凭据未生效或远端认证失败），已跳过，但不影响后续钉钉推送"
            else
                log "   GitHub Pages 推送成功"
            fi
        fi
    fi
fi

set -e

# 4. 钉钉推送
echo "[4/4] 钉钉推送..." >> "$LOG_FILE"
$PYTHON notify_dingtalk.py >> "$LOG_FILE" 2>&1

echo "完成: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"
