#!/usr/bin/env python3
"""钉钉群机器人推送 TabCut 选品报告摘要"""

import os
import json
import time
import hmac
import hashlib
import base64
import urllib.parse
import urllib.request
from datetime import datetime

import pandas as pd
from deep_translator import GoogleTranslator

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

REGIONS = {"US": "美国", "GB": "英国"}

WEBHOOK_URL = os.environ.get(
    "DINGTALK_WEBHOOK",
    "https://oapi.dingtalk.com/robot/send?access_token=e43a345b41c83d7e0c98f4424418422a7202aac849c949aedc7fb922f6de810f"
)
DINGTALK_SECRET = os.environ.get(
    "DINGTALK_SECRET",
    "SECd15e451a75471a32526ae91a50ff0107727a2fe53dbe7d0e2f1103048236017b"
)

REPORT_BASE_URL = "https://tonyaiuser.github.io/fastmoss"


def get_signed_url():
    """生成带签名的钉钉 Webhook URL"""
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{DINGTALK_SECRET}"
    hmac_code = hmac.new(
        DINGTALK_SECRET.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{WEBHOOK_URL}&timestamp={timestamp}&sign={sign}"


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


def translate_name(name):
    """翻译单个商品名为中文"""
    try:
        return GoogleTranslator(source="en", target="zh-CN").translate(str(name)[:80])
    except Exception:
        return str(name)[:40]


def build_message(region="US"):
    region = (region or "US").upper()
    region_name = REGIONS.get(region, region)
    today = datetime.now().strftime("%Y-%m-%d")

    df1 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task1_video_rank_{region}_{today}.csv"))
    df2 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task2_new_material_{region}_{today}.csv"))
    df3 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task3_discover_video_{region}_{today}.csv"))
    df4 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task4_new_product_{region}_{today}.csv"))

    report_url = f"{REPORT_BASE_URL}/report_{region}_{today}.html"

    lines = [
        f"## 巴巴塔选品日报 {region_name}站 {today}",
        "",
        f"- 视频榜日榜: **{len(df1)}** 条",
        f"- 新素材发现: **{len(df2)}** 条",
        f"- 发现视频: **{len(df3)}** 条",
        f"- 商品榜新品: **{len(df4)}** 条",
        "",
    ]

    # Top 5 视频（中文商品名）
    if not df1.empty and "total_score" in df1.columns:
        lines.append("### Top 5 视频")
        top5 = df1.nlargest(5, "total_score")
        for i, (_, r) in enumerate(top5.iterrows(), 1):
            name_cn = translate_name(r.get("item_name", ""))
            views = fmt_number(r.get("views", 0))
            score = r.get("total_score", 0)
            ct = str(r.get("create_time", ""))[:10]
            lines.append(f"{i}. [{score:.0f}分] {name_cn} ({views}播放, {ct})")
        lines.append("")

    # Top 5 新商品（中文商品名）
    if not df4.empty:
        lines.append("### Top 5 新商品")
        top5p = df4.head(5)
        for i, (_, r) in enumerate(top5p.iterrows(), 1):
            name_cn = translate_name(r.get("item_name", ""))
            sold = fmt_number(r.get("sold_period", 0))
            price = r.get("price", "")
            lines.append(f"{i}. {name_cn} (${price}, 日销{sold})")
        lines.append("")

    lines.append(f"[查看完整报告]({report_url})")

    return "\n\n".join(lines)


def send_dingtalk(text):
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"巴巴塔选品日报 {datetime.now().strftime('%Y-%m-%d')}",
            "text": text
        }
    }

    data = json.dumps(payload).encode("utf-8")
    url = get_signed_url()
    req = urllib.request.Request(
        url,
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
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="US")
    args = parser.parse_args()
    msg = build_message(region=args.region)
    print("--- 推送内容 ---")
    print(msg)
    print("--- 发送中 ---")
    send_dingtalk(msg)
