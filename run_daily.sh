#!/bin/bash
# TabCut 每日自动选品脚本（双地区：US + GB）
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="/opt/homebrew/bin/python3"
LOG_FILE="$SCRIPT_DIR/output/run_$(date +%Y-%m-%d).log"

log() {
    echo "$1" >> "$LOG_FILE"
}

run_one_region() {
    local REGION="$1"
    echo "========================================" >> "$LOG_FILE"
    echo "开始运行地区: ${REGION} | $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"

    echo "[1/4] 抓取数据 (${REGION})..." >> "$LOG_FILE"
    if ! $PYTHON tabcut_scraper.py --region "$REGION" >> "$LOG_FILE" 2>&1; then
        log "   ${REGION} 抓取失败，停止该地区后续步骤（不生成报告、不推送、不发通知）"
        echo "失败: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
        echo "========================================" >> "$LOG_FILE"
        return 1
    fi

    echo "[2/4] 生成报告 (${REGION})..." >> "$LOG_FILE"
    $PYTHON generate_report.py --region "$REGION" >> "$LOG_FILE" 2>&1

    echo "[3/4] 推送到 GitHub Pages (${REGION})..." >> "$LOG_FILE"
    set +e
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
            git commit -m "Daily report ${REGION} $(date +%Y-%m-%d)" >> "$LOG_FILE" 2>&1
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

    echo "[4/4] 钉钉推送 (${REGION})..." >> "$LOG_FILE"
    $PYTHON notify_dingtalk.py --region "$REGION" >> "$LOG_FILE" 2>&1

    echo "完成地区: ${REGION} | $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
    echo "========================================" >> "$LOG_FILE"
}

run_one_region US
run_one_region GB
