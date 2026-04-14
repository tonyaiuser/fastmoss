#!/usr/bin/env python3
"""
TabCut (特看) 自动选品脚本
4个需求：视频榜日榜、新素材发现、发现视频、商品榜新品
"""

import argparse
import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import urlencode

import pandas as pd
from playwright.sync_api import sync_playwright

# === 配置 ===
USERNAME = os.environ.get("TABCUT_USER", "zhy0804@ycimedia.com")
PASSWORD = os.environ.get("TABCUT_PASS", "9RMapT4QDKspVvp")
MIN_VIEWS = 200_000
MIN_VIEWS_RECENT = 50_000   # 最近1天内的视频大幅降低门槛，抓早期潜力素材
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
HISTORY_DIR = os.path.join(OUTPUT_DIR, "history")

REGIONS = {
    "US": {"name_zh": "美国", "region_id": 1, "locale": "en-US"},
    "GB": {"name_zh": "英国", "region_id": 2, "locale": "en-GB"},
}

RUN_DIAGNOSTICS = []


def get_region_meta(region):
    region = (region or "US").upper()
    return REGIONS.get(region, REGIONS["US"])


def dated_region_path(prefix, region, today=None, ext="csv"):
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(OUTPUT_DIR, f"{prefix}_{region}_{today}.{ext}")


def history_path(name, region):
    return os.path.join(HISTORY_DIR, f"{name}_{region}.json")


def diagnostics_path(region, today=None):
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(OUTPUT_DIR, f"diagnostics_{region}_{today}.json")


def add_diagnostic(task, level, code, message, **details):
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task": task,
        "level": level,
        "code": code,
        "message": message,
    }
    if details:
        entry["details"] = details
    RUN_DIAGNOSTICS.append(entry)
    detail_text = f" | {json.dumps(details, ensure_ascii=False)}" if details else ""
    print(f"   [{level.upper()}][{task}] {message}{detail_text}")

# 排除的分类关键词（中英文）
EXCLUDED_CATEGORIES = [
    "食品饮料", "Food & Beverages", "Food",
    "保健食品", "Health", "Health & Wellness",
    "美容保健", "Beauty Supplements",
    "冲调饮品", "Instant Drinks", "Beverages",
    "Books & Magazines", "书籍", "图书", "Books",
    "Supplements", "保健品", "膳食补充剂", "Vitamins",
]

# 排除的分类 ID (视频榜/商品榜用)
EXCLUDED_CATEGORY_IDS = {7, 9}  # 7=Food & Beverages, 9=Health

# 排除的商品名关键词（食品饮料糖果等）
EXCLUDED_ITEM_KEYWORDS = [
    "candy", "lollipop", "gummy", "gummies", "chocolate",
    "drink mix", "drink mix", "beverage", "juice", "soda",
    "coffee", "tea bag", "matcha",
    "bread", "cookie", "cookies", "cake", "snack", "snacks",
    "protein powder", "whey protein", "creatine",
    "electrolyte", "boba", "icee",
    "nasal stick", "boomboom",
    "vitamin", "supplement",
    # 书籍
    "book set", "hardcover", "paperback", "biography", "biographies", "novel",
    # 食品（精准匹配）
    "olive oil", "sea moss", "beef jerky", "beef tallow", "tallow balm",
    "waffle cone", "ice cream",
]

# 全球知名IP关键词
GLOBAL_IP_KEYWORDS = [
    "disney", "marvel", "pokemon", "hello kitty", "barbie",
    "star wars", "harry potter", "one piece", "naruto",
    "sanrio", "nintendo", "lego", "nike", "adidas",
]


def login(page):
    """登录 TabCut"""
    print("[登录] 正在登录 TabCut...")
    page.goto("https://www.tabcut.com/workbench?loginType=signIn")
    page.wait_for_load_state("networkidle")
    time.sleep(3)

    page.locator('input[name="email"]').fill(USERNAME)
    page.locator('input[type="password"]').fill(PASSWORD)
    time.sleep(0.5)

    page.evaluate("""
        () => {
            document.querySelectorAll('button').forEach(b => {
                if (b.textContent.trim() === 'Log in') b.click();
            });
        }
    """)

    page.wait_for_load_state("networkidle")
    time.sleep(5)
    print(f"   ✓ 登录完成, URL: {page.url}")


def api_request(page, method, url, payload=None, headers=None, timeout=30000):
    """优先用浏览器上下文请求，避免页面内 fetch 被前端/风控拦截。"""
    req_headers = {"Accept": "application/json, text/plain, */*"}
    if headers:
        req_headers.update(headers)

    context = page.context
    response = context.request.fetch(
        url,
        method=method,
        data=payload,
        headers=req_headers,
        timeout=timeout,
        fail_on_status_code=False,
    )

    status = response.status
    text = response.text()
    if status >= 400:
        raise RuntimeError(f"HTTP {status} for {url}: {text[:500]}")

    try:
        return json.loads(text)
    except Exception as e:
        raise RuntimeError(f"Invalid JSON for {url}: {text[:500]}") from e


def is_excluded(item_name="", category_name="", category_id=None):
    """检查是否应该排除（分类或全球知名IP）"""
    # 检查分类 ID
    if category_id and category_id in EXCLUDED_CATEGORY_IDS:
        return True

    # 检查分类名称
    text = f"{item_name} {category_name}".lower()
    for kw in EXCLUDED_CATEGORIES:
        if kw.lower() in text:
            return True

    # 检查商品名食品饮料关键词
    for kw in EXCLUDED_ITEM_KEYWORDS:
        if kw in text:
            return True

    # 检查全球知名IP
    for ip_kw in GLOBAL_IP_KEYWORDS:
        if ip_kw in text:
            return True

    return False


# =============================================================================
# 历史指标存储（用于跨天 growth_boost）
# =============================================================================
import math


def metric_history_path(task_prefix, region):
    return os.path.join(HISTORY_DIR, f"{task_prefix}_metrics_{region}.json")


def load_metric_history(task_prefix, region):
    """加载历史指标，返回 {video_id: {views, likes, shares, comments, date}}"""
    path = metric_history_path(task_prefix, region)
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_metric_history(task_prefix, region, df):
    """保存当天指标到历史文件，自动清理 7 天前的条目"""
    path = metric_history_path(task_prefix, region)
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # 加载已有历史
    history = {}
    if os.path.exists(path):
        with open(path, "r") as f:
            history = json.load(f)

    # 清理过期条目
    history = {k: v for k, v in history.items() if v.get("date", "") >= cutoff}

    # 写入当天数据
    for _, row in df.iterrows():
        vid = str(row.get("video_id", ""))
        if vid:
            history[vid] = {
                "views": int(row.get("views", 0)),
                "likes": int(row.get("likes", 0)),
                "shares": int(row.get("shares", 0)),
                "comments": int(row.get("comments", 0)),
                "date": today,
            }

    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(history, f)
    print(f"   ✓ 历史指标已保存: {path} ({len(history)} 条)")


# =============================================================================
# 评分系统 v2：4 维度绝对评分
# =============================================================================
def _parse_pub_time(publish_time_str):
    """解析发布时间字符串为 datetime"""
    if not publish_time_str:
        return None
    try:
        s = str(publish_time_str)[:19]
        if "T" in s:
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def calc_score(views, publish_time_str, likes=0, shares=0, comments=0,
               sold_count=0, prev_views=None, now=None):
    """计算 5 维度评分:
    views_score:      绝对对数刻度 (100K=0, 10M=100)
    freshness_score:  指数衰减 (半衰期 36h)
    engagement_score: 互动率固定阈值
    velocity_score:   爆发力 = views_per_hour 对数刻度 + 跨天增长加成
    sales_score:      出单量对数刻度
    """
    if now is None:
        now = datetime.now()

    # --- views_score: 绝对对数刻度 (0-100) ---
    LOG_FLOOR = 5.0   # log10(100K)
    LOG_CEIL = 7.0    # log10(10M)
    log_views = math.log10(max(views, 1))
    views_score = max(0, min(100, (log_views - LOG_FLOOR) / (LOG_CEIL - LOG_FLOOR) * 100))

    # --- freshness_score: 指数衰减 (0-100) ---
    freshness_score = 0
    hours_ago = None
    pub_dt = _parse_pub_time(publish_time_str)
    if pub_dt:
        hours_ago = max(0, (now - pub_dt).total_seconds() / 3600)
        half_life_hours = 24
        freshness_score = 100 * (0.5 ** (hours_ago / half_life_hours))

    # --- engagement_score: 互动率固定阈值 (0-100) ---
    eng_rate = (likes + shares + comments) / max(views, 1)
    if eng_rate >= 0.05:
        engagement_score = 100
    elif eng_rate >= 0.023:
        engagement_score = 70 + (eng_rate - 0.023) / (0.05 - 0.023) * 30
    elif eng_rate >= 0.011:
        engagement_score = 40 + (eng_rate - 0.011) / (0.023 - 0.011) * 30
    elif eng_rate >= 0.003:
        engagement_score = (eng_rate - 0.003) / (0.011 - 0.003) * 40
    else:
        engagement_score = 0

    # --- velocity_score: 爆发力 (0-100) ---
    # 基于 views_per_hour 的对数刻度: 1K/h(=3.0) → 0, 100K/h(=5.0) → 100
    velocity_score = 0
    VPH_LOG_FLOOR = 3.0  # log10(1000)
    VPH_LOG_CEIL = 5.0   # log10(100000)
    if hours_ago is not None and hours_ago >= 0:
        vph = views / max(hours_ago, 1)
        log_vph = math.log10(max(vph, 1))
        velocity_score = max(0, min(100, (log_vph - VPH_LOG_FLOOR) / (VPH_LOG_CEIL - VPH_LOG_FLOOR) * 100))

    # 跨天增长加成: 渐进式，1.3x 起步
    if prev_views and prev_views > 0:
        growth = views / prev_views
        if growth >= 3.0:
            velocity_score = min(100, velocity_score + 20)
        elif growth >= 2.0:
            velocity_score = min(100, velocity_score + 15)
        elif growth >= 1.5:
            velocity_score = min(100, velocity_score + 10)
        elif growth >= 1.3:
            velocity_score = min(100, velocity_score + 5)

    # --- sales_score: 出单量对数刻度 (0-100) ---
    # 10单(=1.0) → 0, 10K单(=4.0) → 100
    sales_score = 0
    try:
        sc = float(sold_count or 0)
        if sc > 0:
            SOLD_LOG_FLOOR = 1.0   # log10(10)
            SOLD_LOG_CEIL = 4.0    # log10(10000)
            log_sold = math.log10(max(sc, 1))
            sales_score = max(0, min(100, (log_sold - SOLD_LOG_FLOOR) / (SOLD_LOG_CEIL - SOLD_LOG_FLOOR) * 100))
    except (ValueError, TypeError):
        sales_score = 0

    return {
        "views": views,
        "views_score": round(views_score, 1),
        "freshness_score": round(freshness_score, 1),
        "engagement_score": round(engagement_score, 1),
        "velocity_score": round(velocity_score, 1),
        "sales_score": round(sales_score, 1),
    }


def finalize_scores(df):
    """权重聚合: freshness 35% + velocity 25% + sales 15% + engagement 15% + views 10%"""
    if df.empty:
        return df

    W_FRESH = 0.35
    W_VELOCITY = 0.25
    W_SALES = 0.15
    W_ENGAGE = 0.15
    W_VIEWS = 0.10

    # sales_score 列可能不存在（旧数据兼容）
    if "sales_score" not in df.columns:
        df["sales_score"] = 0.0

    df["total_score"] = (
        df["freshness_score"] * W_FRESH +
        df["velocity_score"] * W_VELOCITY +
        df["engagement_score"] * W_ENGAGE +
        df["views_score"] * W_VIEWS +
        df["sales_score"] * W_SALES
    ).round(1)

    df = df.sort_values("total_score", ascending=False)
    return df


def video_meets_threshold(create_time, views):
    try:
        ct_dt = datetime.strptime(create_time[:19], "%Y-%m-%dT%H:%M:%S") if "T" in create_time else datetime.strptime(create_time[:19], "%Y-%m-%d %H:%M:%S")
        is_recent = (datetime.now() - ct_dt).total_seconds() < 86400
    except Exception:
        is_recent = False
    threshold = MIN_VIEWS_RECENT if is_recent else MIN_VIEWS
    return views >= threshold


def finalize_video_collection(rows, key="video_id"):
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=[key], keep="first")
    return finalize_scores(df)


def trim_task_overlap(primary_df, secondary_df, key="video_id", task_name="task"):
    if primary_df is None or primary_df.empty or secondary_df is None or secondary_df.empty or key not in secondary_df.columns:
        return secondary_df
    primary_ids = {str(v) for v in primary_df.get(key, pd.Series(dtype=str)).dropna().tolist()}
    before = len(secondary_df)
    filtered = secondary_df[~secondary_df[key].astype(str).isin(primary_ids)].copy()
    removed = before - len(filtered)
    if removed > 0:
        add_diagnostic(task_name, "info", "overlap_trimmed", "Trimmed overlapping rows against upstream module", removed=removed, remaining=len(filtered))
    return filtered


def build_hot_product_candidates(video_df):
    if video_df is None or video_df.empty:
        return pd.DataFrame()

    work_df = video_df.copy()
    if "item_id" not in work_df.columns:
        work_df["item_id"] = ""
    if "item_name" not in work_df.columns:
        work_df["item_name"] = ""

    work_df["product_key"] = work_df.apply(
        lambda r: str(r.get("item_id") or "").strip() or str(r.get("item_name") or "").strip().lower(),
        axis=1,
    )
    work_df = work_df[work_df["product_key"] != ""].copy()
    if work_df.empty:
        return pd.DataFrame()

    agg_rows = []
    for _, group in work_df.groupby("product_key", sort=False):
        group = group.sort_values("total_score", ascending=False)
        top = group.iloc[0]
        agg_rows.append({
            "item_id": top.get("item_id", ""),
            "item_name": top.get("item_name", ""),
            "item_cover": top.get("item_cover", ""),
            "item_price": top.get("item_price", ""),
            "item_category_l1": top.get("item_category_l1", ""),
            "item_category_l2": top.get("item_category_l2", ""),
            "sample_video_id": top.get("video_id", ""),
            "sample_video_url": top.get("video_url", ""),
            "sample_video_cover": top.get("video_cover", ""),
            "sample_creator_name": top.get("creator_name", ""),
            "sample_video_desc": top.get("video_desc", ""),
            "videos": int(group["video_id"].astype(str).nunique()) if "video_id" in group.columns else len(group),
            "creators": int(group["creator_id"].astype(str).nunique()) if "creator_id" in group.columns else 0,
            "sum_views": int(group["views"].fillna(0).sum()) if "views" in group.columns else 0,
            "max_views": int(group["views"].fillna(0).max()) if "views" in group.columns else 0,
            "best_score": round(float(group["total_score"].fillna(0).max()), 1) if "total_score" in group.columns else 0,
            "avg_score": round(float(group["total_score"].fillna(0).mean()), 1) if "total_score" in group.columns else 0,
            "video_sold_count": int(group["video_sold_count"].fillna(0).sum()) if "video_sold_count" in group.columns else int(group["item_sold"].fillna(0).sum()) if "item_sold" in group.columns else 0,
            "source_mode": "video_aggregate",
        })

    agg_df = pd.DataFrame(agg_rows)
    if agg_df.empty:
        return agg_df

    agg_df["decision_score"] = (
        agg_df["best_score"] * 0.4 +
        agg_df["avg_score"] * 0.2 +
        agg_df["videos"].clip(upper=5) * 8 +
        agg_df["creators"].clip(upper=5) * 6 +
        agg_df["video_sold_count"].clip(upper=5000).div(100)
    ).round(1)
    agg_df = agg_df.sort_values(["decision_score", "sum_views", "videos"], ascending=False)
    return agg_df.reset_index(drop=True)


def collect_search_videos(page, region, prev_metrics, days, task_name, include_task1_shape=False):
    now = datetime.now()
    begin = (now - timedelta(days=days)).strftime("%Y-%m-%d 00:00:00")
    end = now.strftime("%Y-%m-%d 23:59:59")
    all_videos = []
    seen_ids = set()
    page_no = 1

    while True:
        print(f"   第 {page_no} 页...", end=" ")
        result = api_request(
            page,
            "POST",
            "https://www.tabcut.com/api/analysis/video-search/videoListV2",
            payload={
                "pageNo": page_no,
                "pageSize": 20,
                "region": region,
                "sortField": "play_count_total",
                "videoCreateTimeBegin": begin,
                "videoCreateTimeEnd": end,
                "itemVideoFlag": 1,
            },
            headers={"Content-Type": "application/json"},
        )

        data = result.get("result", {}).get("data", [])
        total = result.get("result", {}).get("total", 0)
        if not data:
            print("无数据")
            break

        min_play = min(v.get("playCountTotal", 0) for v in data)
        print(f"{len(data)} 条 (总 {total}), 最小播放: {min_play:,}")

        for v in data:
            play_count = v.get("playCountTotal", 0)
            create_time = v.get("createTime", "") or ""
            if not video_meets_threshold(create_time, play_count):
                continue

            cat1 = v.get("itemTkLv1Name", "") or ""
            cat2 = v.get("itemTkLv2Name", "") or ""
            item_name = v.get("itemName", "") or ""
            if is_excluded(item_name=f"{item_name} {cat1} {cat2}".lower()):
                continue

            vid = str(v.get("videoId", ""))
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)

            prev = prev_metrics.get(vid, {})
            likes = v.get("likeCountTotal", 0)
            shares = v.get("shareCountTotal", 0)
            comments = v.get("commentCountTotal", 0)
            video_sold = v.get("videoSplitSoldCount", 0)
            scores = calc_score(
                play_count, create_time,
                likes=likes, shares=shares, comments=comments,
                sold_count=video_sold,
                prev_views=prev.get("views"),
            )

            video_url = v.get("tkVideoUrl") or ""
            if not video_url:
                author = v.get("authorUniqueId", "")
                video_url = f"https://www.tiktok.com/@{author}/video/{vid}" if author else ""

            row = {
                "video_id": v.get("videoId"),
                "video_cover": v.get("videoCoverUrl") or "",
                "video_desc": (v.get("videoDesc") or "")[:100],
                "video_url": video_url,
                "create_time": create_time,
                "views": play_count,
                "likes": likes,
                "shares": shares,
                "comments": comments,
                "creator_name": v.get("authorNickname") or v.get("authorUniqueId", ""),
                "creator_id": v.get("authorUniqueId", ""),
                "creator_avatar": v.get("authorAvatarUrl") or "",
                "item_id": v.get("itemId") or "",
                "item_name": item_name,
                "item_cover": v.get("itemCoverUrl") or "",
                "item_price": (v.get("priceAmount") or {}).get("region", ""),
                "item_sold": video_sold,
                "source_mode": "search",
                "views_score": scores["views_score"],
                "freshness_score": scores["freshness_score"],
                "engagement_score": scores["engagement_score"],
                "velocity_score": scores["velocity_score"],
                "sales_score": scores["sales_score"],
            }
            if include_task1_shape:
                row.update({
                    "rank": len(all_videos) + 1,
                    "hashtags": "",
                })
            else:
                row.update({
                    "interaction_rate": v.get("interactionRate", 0),
                    "creator_followers": v.get("authorFollowerCountTotal", 0),
                    "item_sold_total": v.get("itemSoldCountTotal", 0),
                    "item_category_l1": cat1,
                    "item_category_l2": cat2,
                    "video_sold_count": video_sold,
                })
            all_videos.append(row)

        if min_play < MIN_VIEWS_RECENT or page_no >= 50:
            break
        page_no += 1
        time.sleep(0.5)

    if not all_videos:
        add_diagnostic(task_name, "warning", "empty_result", "Search video collection returned no qualified rows", days=days)
    return all_videos


def collect_ranking_videos(page, region, prev_metrics, task_name):
    meta = get_region_meta(region)
    all_videos = []
    page_no = 1
    page_size = 24
    page_signatures = []

    while True:
        print(f"   第 {page_no} 页...", end=" ")
        query = urlencode({
            "region": region,
            "regionId": meta["region_id"],
            "rankDay": 1,
            "itemCategoryId": 0,
            "sort": 10,
            "pageNo": page_no,
            "pageSize": page_size,
        })
        result = api_request(page, "GET", f"https://www.tabcut.com/api/ranking/videos?{query}")
        data = result.get("result", {}).get("data", [])
        total = result.get("result", {}).get("total", 0)

        if not data:
            print("无数据")
            break

        signature = tuple(str(v.get("videoId", "")) for v in data[:5])
        page_signatures.append(signature)
        min_play = min(v.get("playCount", 0) for v in data)
        print(f"{len(data)} 条, 最小播放: {min_play:,}")

        for v in data:
            play_count = v.get("playCount", 0)
            create_time = v.get("createTime", "") or ""
            if not video_meets_threshold(create_time, play_count):
                continue

            items = v.get("itemList", [])
            item_names = [str(it.get("itemName") or "").strip() for it in items]
            item_names = [name for name in item_names if name]
            item_name_str = " | ".join(item_names)
            if is_excluded(item_name=item_name_str.lower()):
                continue

            vid = str(v.get("videoId", ""))
            prev = prev_metrics.get(vid, {})
            likes = v.get("likeCount", 0)
            shares = v.get("shareCount", 0)
            comments = v.get("commentCount", 0)
            item_sold = items[0].get("soldCount", 0) if items else 0
            scores = calc_score(
                play_count, create_time,
                likes=likes, shares=shares, comments=comments,
                sold_count=item_sold,
                prev_views=prev.get("views"),
            )

            all_videos.append({
                "rank": v.get("rank"),
                "video_id": v.get("videoId"),
                "video_cover": v.get("videoCoverUrl") or "",
                "video_desc": (v.get("videoDesc") or "")[:100],
                "video_url": f"https://www.tiktok.com/@{v.get('authorName', '')}/video/{v.get('videoId', '')}",
                "create_time": create_time,
                "views": play_count,
                "likes": likes,
                "shares": shares,
                "comments": comments,
                "creator_name": v.get("authorName", ""),
                "creator_id": v.get("authorUid", ""),
                "creator_avatar": v.get("authorAvatarUrl") or "",
                "item_id": items[0].get("itemId", "") if items else "",
                "item_name": item_name_str,
                "item_cover": items[0].get("itemCoverUrl", "") if items else "",
                "item_price": items[0].get("skuPrice", "") if items else "",
                "item_sold": item_sold,
                "hashtags": ", ".join(h.get("hashtagName") or "" for h in (v.get("hashtags") or [])),
                "source_mode": "ranking",
                "views_score": scores["views_score"],
                "freshness_score": scores["freshness_score"],
                "engagement_score": scores["engagement_score"],
                "velocity_score": scores["velocity_score"],
                "sales_score": scores["sales_score"],
            })

        if len(data) < page_size or min_play < MIN_VIEWS_RECENT:
            break
        page_no += 1
        if total and page_no > ((total + page_size - 1) // page_size):
            break
        time.sleep(0.5)

    duplicate_pages = sum(1 for count in Counter(page_signatures).values() if count > 1)
    is_broken = len(page_signatures) > 1 and duplicate_pages > 0
    if is_broken:
        add_diagnostic(task_name, "warning", "ranking_pagination_broken", "Ranking API pagination appears to repeat pages", pages=len(page_signatures), duplicate_signatures=duplicate_pages)
    elif len(all_videos) <= page_size and len(page_signatures) > 1:
        add_diagnostic(task_name, "warning", "ranking_low_unique_rows", "Ranking API returned multiple pages but very few unique rows", pages=len(page_signatures), unique_rows=len({str(v.get('video_id')) for v in all_videos}))
        is_broken = True

    return all_videos, {"pages": len(page_signatures), "is_broken": is_broken}


# =============================================================================
# 需求1: 视频榜 美国 日榜 播放量200K+
# =============================================================================
def task1_video_rank(page, region="US"):
    """需求1: 视频榜日榜"""
    meta = get_region_meta(region)
    print("\n" + "=" * 60)
    print(f"需求1: 视频榜 {meta['name_zh']} 日榜 播放量 >= 200K")
    print("=" * 60)

    prev_metrics = load_metric_history("task1", region)
    print(f"   历史指标: {len(prev_metrics)} 条")

    ranking_rows, ranking_meta = collect_ranking_videos(page, region, prev_metrics, "task1")
    df = finalize_video_collection(ranking_rows)

    if ranking_meta["is_broken"]:
        print("\n   [DEGRADED] Ranking API 不稳定，启用显式降级模式")
        fallback_rows = collect_search_videos(page, region, prev_metrics, days=2, task_name="task1", include_task1_shape=True)
        fallback_df = finalize_video_collection(fallback_rows)
        if len(fallback_df) > len(df):
            add_diagnostic("task1", "warning", "fallback_activated", "Task1 switched to degraded search-backed mode", ranking_rows=len(df), fallback_rows=len(fallback_df))
            df = fallback_df
            if not df.empty:
                df["source_mode"] = "search_fallback"
        else:
            add_diagnostic("task1", "warning", "fallback_skipped", "Fallback returned no improvement, keeping ranking output", ranking_rows=len(df), fallback_rows=len(fallback_df))
    elif df.empty:
        add_diagnostic("task1", "warning", "empty_result", "Task1 ranking collection produced no rows")

    today = datetime.now().strftime("%Y-%m-%d")
    path = dated_region_path("task1_video_rank", region, today)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n   ✓ 需求1完成: {path} ({len(df)} 条)")
    preview(df)

    if not df.empty:
        save_metric_history("task1", region, df)

    return df


# =============================================================================
# 需求2: 视频榜新素材发现（历史未出现过）
# =============================================================================
def task2_new_material(page, region="US", task1_df=None):
    """需求2: 新素材榜，独立看首次出现且值得盯的视频"""
    print("\n" + "=" * 60)
    print("需求2: 新素材榜（首次出现 + 高新鲜度）")
    print("=" * 60)

    prev_metrics = load_metric_history("task2", region)
    base_rows = collect_search_videos(page, region, prev_metrics, days=3, task_name="task2", include_task1_shape=False)
    base_df = finalize_video_collection(base_rows)

    history_file = history_path("video_history", region)
    history_ids = set()
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            history_ids = set(json.load(f))
    print(f"   历史记录: {len(history_ids)} 条")

    if base_df.empty:
        add_diagnostic("task2", "warning", "empty_result", "Task2 source pool produced no rows")
        print("   ⚠ 无视频数据")
        return pd.DataFrame()

    new_df = base_df[~base_df["video_id"].astype(str).isin({str(v) for v in history_ids})].copy()
    if task1_df is not None and not task1_df.empty:
        new_df = trim_task_overlap(task1_df.head(20), new_df, key="video_id", task_name="task2")

    if not new_df.empty:
        new_df = new_df.sort_values(["freshness_score", "velocity_score", "engagement_score", "views"], ascending=False)
    print(f"   新素材: {len(new_df)} 条 (源池 {len(base_df)} 条)")

    today = datetime.now().strftime("%Y-%m-%d")
    path = dated_region_path("task2_new_material", region, today)
    new_df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"   ✓ 需求2完成: {path}")

    history_ids.update(base_df["video_id"].astype(str).tolist())
    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(history_file, "w") as f:
        json.dump(list(history_ids), f)
    print(f"   ✓ 历史记录已更新: {len(history_ids)} 条")

    if not new_df.empty:
        save_metric_history("task2", region, new_df)
    preview(new_df)
    return new_df


# =============================================================================
# 需求3: 发现视频 美国 近3天 带货 播放量200K+
# =============================================================================
def task3_discover_video(page, region="US", task1_df=None, task2_df=None):
    """需求3: 高潜商品榜，从视频侧聚合商品信号"""
    meta = get_region_meta(region)
    print("\n" + "=" * 60)
    print(f"需求3: 高潜商品榜 {meta['name_zh']} 近3天视频聚合")
    print("=" * 60)

    prev_metrics = load_metric_history("task3", region)
    print(f"   历史指标: {len(prev_metrics)} 条")

    rows = collect_search_videos(page, region, prev_metrics, days=3, task_name="task3", include_task1_shape=False)
    video_df = finalize_video_collection(rows)
    if task1_df is not None and not task1_df.empty:
        video_df = trim_task_overlap(task1_df.head(30), video_df, key="video_id", task_name="task3")
    if task2_df is not None and not task2_df.empty:
        video_df = trim_task_overlap(task2_df.head(20), video_df, key="video_id", task_name="task3")

    df = build_hot_product_candidates(video_df)
    if df.empty:
        add_diagnostic("task3", "warning", "empty_result", "Task3 product aggregation produced no rows")

    today = datetime.now().strftime("%Y-%m-%d")
    path = dated_region_path("task3_discover_video", region, today)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n   ✓ 需求3完成: {path} ({len(df)} 条)")
    preview(df)

    if not video_df.empty:
        save_metric_history("task3", region, video_df)

    return df


# =============================================================================
# 需求4: 商品榜新品发现
# =============================================================================
def task4_new_product(page, region="US"):
    """需求4: 商品榜新品发现"""
    print("\n" + "=" * 60)
    print("需求4: 商品榜新品发现（历史未出现过）")
    print("=" * 60)

    # 获取今天的日期（YYYYMMDD格式）
    today_str = datetime.now().strftime("%Y%m%d")
    # 商品榜可能滞后一天
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    all_products = []

    for biz_date in [today_str, yesterday_str]:
        page_no = 1
        while page_no <= 50:
            print(f"   日期={biz_date} 第 {page_no} 页...", end=" ")

            # trpc API 需要编码参数
            input_params = {
                "pageNo": page_no,
                "pageSize": 24,
                "rankType": 1,
                "bizDate": biz_date,
                "region": region,
                "categoryId": "0",
                "orderType": "1",
                "sellerType": ""
            }

            params = urlencode({"input": json.dumps(input_params, ensure_ascii=False)})
            result = api_request(page, "GET", f"https://www.tabcut.com/api/trpc/ranking.goods.rankingData?{params}")

            # trpc 的数据结构多一层
            inner = result.get("result", {}).get("data", {})
            if isinstance(inner, dict) and "result" in inner:
                data = inner.get("result", {}).get("data", [])
                total = inner.get("result", {}).get("total", 0)
            else:
                data = []
                total = 0

            if not data:
                print("无数据")
                break

            print(f"{len(data)} 条 (总 {total})")

            for item in data:
                cat_id = item.get("categoryId")
                cat_name = item.get("categoryName", "")
                item_name = item.get("itemName", "")

                if is_excluded(item_name=item_name.lower(), category_name=cat_name.lower(), category_id=cat_id):
                    continue

                sold_info = item.get("soldCountInfo", {})
                gmv_info = item.get("gmvInfo", {})
                price_list = item.get("priceList", [{}])

                all_products.append({
                    "rank": item.get("rank"),
                    "item_id": item.get("itemId"),
                    "item_name": item_name,
                    "item_cover": item.get("itemPicUrl") or "",
                    "category": cat_name,
                    "category_id": cat_id,
                    "price": price_list[0].get("region", "") if price_list else "",
                    "sold_period": sold_info.get("periodCurrent", 0),
                    "sold_total": sold_info.get("total", 0),
                    "gmv_period": (gmv_info.get("periodCurrent") or {}).get("region", 0),
                    "seller_name": item.get("sellerName", ""),
                    "seller_type": item.get("sellerType", ""),
                    "commission_rate": item.get("commissionRate", 0),
                    "related_creators_90d": (item.get("relatedCreatorInfo") or {}).get("period90d", 0),
                    "related_videos_90d": (item.get("relatedVideoInfo") or {}).get("period90d", 0),
                    "biz_date": biz_date,
                })

            page_no += 1
            time.sleep(0.5)

        if all_products:
            break  # 只要有数据就用这个日期

    df = pd.DataFrame(all_products)
    if not df.empty:
        df = df.drop_duplicates(subset=["item_id"], keep="first")

    # 对比历史
    history_file = history_path("product_history", region)
    history_ids = set()
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            history_ids = set(json.load(f))
    print(f"   历史记录: {len(history_ids)} 条")

    new_df = df[~df["item_id"].isin(history_ids)].copy() if not df.empty else pd.DataFrame(columns=list(df.columns) if not df.empty else [
        "rank", "item_id", "item_name", "item_cover", "category", "category_id", "price",
        "sold_period", "sold_total", "gmv_period", "seller_name", "seller_type",
        "commission_rate", "related_creators_90d", "related_videos_90d", "biz_date"
    ])
    print(f"   新商品: {len(new_df)} 条 (从 {len(df)} 条中)")

    today = datetime.now().strftime("%Y-%m-%d")
    path = dated_region_path("task4_new_product", region, today)
    new_df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"   ✓ 需求4完成: {path}")

    # 更新历史
    if not df.empty:
        history_ids.update(df["item_id"].tolist())
        os.makedirs(HISTORY_DIR, exist_ok=True)
        with open(history_file, "w") as f:
            json.dump(list(history_ids), f)
        print(f"   ✓ 历史记录已更新: {len(history_ids)} 条")

    return new_df


def write_diagnostics(region):
    today = datetime.now().strftime("%Y-%m-%d")
    path = diagnostics_path(region, today)
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "region": region,
        "entries": RUN_DIAGNOSTICS,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n   ✓ Diagnostics 已写入: {path} ({len(RUN_DIAGNOSTICS)} 条)")


def preview(df, n=10):
    """打印前N条预览"""
    if df.empty:
        print("   ⚠ 无数据")
        return

    cols = ["total_score", "views", "create_time", "creator_name", "video_desc"]
    cols = [c for c in cols if c in df.columns]
    if not cols:
        cols = list(df.columns)[:5]

    print(f"\n   === 前 {min(n, len(df))} 条预览 ===")
    for i, (_, row) in enumerate(df.head(n).iterrows(), 1):
        parts = []
        if "total_score" in row:
            parts.append(f"分数:{row['total_score']:.0f}")
        if "views" in row:
            parts.append(f"播放:{row['views']:,}")
        if "create_time" in row:
            parts.append(f"时间:{str(row['create_time'])[:16]}")
        if "creator_name" in row:
            parts.append(f"达人:{str(row['creator_name'])[:15]}")
        if "item_name" in row:
            parts.append(f"商品:{str(row['item_name'])[:30]}")
        print(f"   {i:3d}. {' | '.join(parts)}")


def main():
    RUN_DIAGNOSTICS.clear()
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="US")
    args = parser.parse_args()
    region = (args.region or "US").upper()
    meta = get_region_meta(region)
    print("=" * 60)
    print(f"TabCut 自动选品工具 ({meta['name_zh']} {region})")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale=meta["locale"],
        )
        page = context.new_page()

        try:
            login(page)

            # 需求1: 视频榜日榜
            df1 = task1_video_rank(page, region=region)

            # 需求2: 新素材发现（独立新鲜池，避免与需求1重复）
            df2 = task2_new_material(page, region=region, task1_df=df1)

            # 需求3: 高潜商品榜（从视频侧聚合，避免继续做重复视频表）
            df3 = task3_discover_video(page, region=region, task1_df=df1, task2_df=df2)

            # 需求4: 商品榜新品
            df4 = task4_new_product(page, region=region)

            # 汇总
            print("\n" + "=" * 60)
            print("全部完成!")
            print("=" * 60)
            print(f"   需求1 视频榜日榜: {len(df1)} 条")
            print(f"   需求2 新素材发现: {len(df2)} 条")
            print(f"   需求3 高潜商品榜: {len(df3)} 条")
            print(f"   需求4 新品发现:   {len(df4)} 条")
            print(f"\n   文件保存在: {OUTPUT_DIR}")

        except Exception as e:
            add_diagnostic("run", "error", "unhandled_exception", str(e))
            print(f"\n错误: {e}")
            import traceback
            traceback.print_exc()
            page.screenshot(path=os.path.join(OUTPUT_DIR, "error_screenshot.png"))

        finally:
            write_diagnostics(region)
            time.sleep(5)
            browser.close()


if __name__ == "__main__":
    main()
