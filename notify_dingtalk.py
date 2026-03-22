#!/usr/bin/env python3
"""钉钉群机器人推送 TabCut 选品报告摘要"""

import os
import json
import urllib.request
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

WEBHOOK_URL = os.environ.get(
    "DINGTALK_WEBHOOK",
    "https://oapi.dingtalk.com/robot/send?access_token=e43a345b41c83d7e0c98f4424418422a7202aac849c949aedc7fb922f6de810f"
)

REPORT_BASE_URL = "https://tonyaiuser.github.io/fastmoss"


def read_csv_safe(path):
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame()


def fmt_number(n):
    try:
        n = float(n)
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        elif n >= 1_000:
            return f"{n/1_000:.1f}K"
        return f"{n:,.0f}"
    except (ValueError, TypeError):
        return str(n)


def build_message():
    today = datetime.now().strftime("%Y-%m-%d")

    df1 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task1_video_rank_{today}.csv"))
    df2 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task2_new_material_{today}.csv"))
    df3 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task3_discover_video_{today}.csv"))
    df4 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task4_new_product_{today}.csv"))

    report_url = f"{REPORT_BASE_URL}/report_{today}.html"

    lines = [
        f"## TabCut 选品日报 {today}",
        "",
        f"- 视频榜日榜: **{len(df1)}** 条",
        f"- 新素材发现: **{len(df2)}** 条",
        f"- 发现视频: **{len(df3)}** 条",
        f"- 商品榜新品: **{len(df4)}** 条",
        "",
    ]

    # Top 5 视频
    if not df1.empty and "total_score" in df1.columns:
        lines.append("### Top 5 视频")
        top5 = df1.nlargest(5, "total_score")
        for i, (_, r) in enumerate(top5.iterrows(), 1):
            name = str(r.get("item_name", ""))[:40]
            views = fmt_number(r.get("views", 0))
            score = r.get("total_score", 0)
            ct = str(r.get("create_time", ""))[:10]
            lines.append(f"{i}. [{score:.0f}分] {name} ({views}播放, {ct})")
        lines.append("")

    # Top 5 新商品
    if not df4.empty:
        lines.append("### Top 5 新商品")
        top5p = df4.head(5)
        for i, (_, r) in enumerate(top5p.iterrows(), 1):
            name = str(r.get("item_name", ""))[:40]
            sold = fmt_number(r.get("sold_period", 0))
            price = r.get("price", "")
            lines.append(f"{i}. {name} (${price}, 日销{sold})")
        lines.append("")

    lines.append(f"[查看完整报告]({report_url})")

    return "\n\n".join(lines)


def send_dingtalk(text):
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"TabCut 选品日报 {datetime.now().strftime('%Y-%m-%d')}",
            "text": text
        }
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
            if result.get("errcode") == 0:
                print("✓ 钉钉推送成功")
            else:
                print(f"✗ 钉钉推送失败: {result}")
    except Exception as e:
        print(f"✗ 钉钉推送异常: {e}")


if __name__ == "__main__":
    msg = build_message()
    print("--- 推送内容 ---")
    print(msg)
    print("--- 发送中 ---")
    send_dingtalk(msg)
