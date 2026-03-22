#!/usr/bin/env python3
"""
TabCut (特看) 自动选品脚本
4个需求：视频榜日榜、新素材发现、发现视频、商品榜新品
"""

import json
import os
import time
from datetime import datetime, timedelta

import pandas as pd
from playwright.sync_api import sync_playwright

# === 配置 ===
USERNAME = os.environ.get("TABCUT_USER", "zhy0804@ycimedia.com")
PASSWORD = os.environ.get("TABCUT_PASS", "9RMapT4QDKspVvp")
MIN_VIEWS = 200_000
MIN_VIEWS_RECENT = 100_000  # 最近1天内的视频降低门槛
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
HISTORY_DIR = os.path.join(OUTPUT_DIR, "history")

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

    # 检查全球知名IP
    for ip_kw in GLOBAL_IP_KEYWORDS:
        if ip_kw in text:
            return True

    return False


def calc_score(views, publish_time_str, now=None):
    """计算评分: 播放量60% + 时间新鲜度40%"""
    if now is None:
        now = datetime.now()

    # 时间得分
    time_score = 0
    try:
        pub_dt = datetime.strptime(publish_time_str[:19], "%Y-%m-%dT%H:%M:%S") if "T" in publish_time_str else datetime.strptime(publish_time_str[:19], "%Y-%m-%d %H:%M:%S")
        days_ago = (now - pub_dt).total_seconds() / 86400
        if days_ago < 1:
            time_score = 100
        elif days_ago < 2:
            time_score = 70
        elif days_ago < 3:
            time_score = 40
        else:
            time_score = max(0, 10 - (days_ago - 3) * 2)
    except Exception:
        time_score = 0

    return {"views": views, "time_score": time_score}


def finalize_scores(df):
    """归一化播放量得分并计算总分"""
    if df.empty:
        return df

    max_views = df["views"].max()
    min_views = df["views"].min()
    if max_views > min_views:
        df["views_score"] = ((df["views"] - min_views) / (max_views - min_views) * 100).round(1)
    else:
        df["views_score"] = 100.0

    df["total_score"] = (df["views_score"] * 0.45 + df["time_score"] * 0.55).round(1)
    df = df.sort_values("total_score", ascending=False)
    return df


# =============================================================================
# 需求1: 视频榜 美国 日榜 播放量200K+
# =============================================================================
def task1_video_rank(page):
    """需求1: 视频榜日榜"""
    print("\n" + "=" * 60)
    print("需求1: 视频榜 美国 日榜 播放量 >= 200K")
    print("=" * 60)

    all_videos = []
    page_no = 1
    page_size = 24

    while True:
        print(f"   第 {page_no} 页...", end=" ")
        result = page.evaluate(f"""
            async () => {{
                const resp = await fetch('/api/ranking/videos?region=US&regionId=1&rankDay=1&itemCategoryId=0&sort=10&pageNo={page_no}&pageSize={page_size}');
                return await resp.json();
            }}
        """)

        data = result.get("result", {}).get("data", [])
        total = result.get("result", {}).get("total", 0)

        if not data:
            print("无数据")
            break

        min_play = min(v.get("playCount", 0) for v in data)
        print(f"{len(data)} 条, 最小播放: {min_play:,}")

        for v in data:
            play_count = v.get("playCount", 0)

            # 判断是否最近1天内的视频，降低播放量门槛
            ct_str = v.get("createTime", "")
            try:
                ct_dt = datetime.strptime(ct_str[:19], "%Y-%m-%dT%H:%M:%S") if "T" in ct_str else datetime.strptime(ct_str[:19], "%Y-%m-%d %H:%M:%S")
                is_recent = (datetime.now() - ct_dt).total_seconds() < 86400
            except Exception:
                is_recent = False
            threshold = MIN_VIEWS_RECENT if is_recent else MIN_VIEWS
            if play_count < threshold:
                continue

            # 获取商品信息
            items = v.get("itemList", [])
            item_names = [it.get("itemName", "") for it in items]
            item_name_str = " | ".join(item_names)

            # 排除检查（用商品名检查分类和IP）
            if is_excluded(item_name=item_name_str.lower()):
                continue

            scores = calc_score(play_count, v.get("createTime", ""))

            all_videos.append({
                "rank": v.get("rank"),
                "video_id": v.get("videoId"),
                "video_cover": v.get("videoCoverUrl") or "",
                "video_desc": (v.get("videoDesc") or "")[:100],
                "video_url": f"https://www.tiktok.com/@{v.get('authorName', '')}/video/{v.get('videoId', '')}",
                "create_time": v.get("createTime") or "",
                "views": play_count,
                "likes": v.get("likeCount", 0),
                "shares": v.get("shareCount", 0),
                "comments": v.get("commentCount", 0),
                "creator_name": v.get("authorName", ""),
                "creator_id": v.get("authorUid", ""),
                "creator_avatar": v.get("authorAvatarUrl") or "",
                "item_name": item_name_str,
                "item_cover": items[0].get("itemCoverUrl", "") if items else "",
                "item_price": items[0].get("skuPrice", "") if items else "",
                "item_sold": items[0].get("soldCount", "") if items else "",
                "hashtags": ", ".join(h.get("hashtagName") or "" for h in (v.get("hashtags") or [])),
                "time_score": scores["time_score"],
            })

        # 如果最小播放量已低于最低阈值，停止
        if min_play < MIN_VIEWS_RECENT:
            break

        page_no += 1
        time.sleep(0.5)

    df = pd.DataFrame(all_videos)
    if not df.empty:
        df = finalize_scores(df)

    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(OUTPUT_DIR, f"task1_video_rank_{today}.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n   ✓ 需求1完成: {path} ({len(df)} 条)")
    preview(df)
    return df


# =============================================================================
# 需求2: 视频榜新素材发现（历史未出现过）
# =============================================================================
def task2_new_material(page, task1_df=None):
    """需求2: 视频榜新素材发现"""
    print("\n" + "=" * 60)
    print("需求2: 视频榜新素材发现（历史未出现过）")
    print("=" * 60)

    # 如果没有 task1 数据，重新获取
    if task1_df is None or task1_df.empty:
        task1_df = task1_video_rank(page)

    if task1_df.empty:
        print("   ⚠ 无视频数据")
        return pd.DataFrame()

    # 加载历史视频 ID
    history_file = os.path.join(HISTORY_DIR, "video_history.json")
    history_ids = set()
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            history_ids = set(json.load(f))
    print(f"   历史记录: {len(history_ids)} 条")

    # 筛选新素材
    new_df = task1_df[~task1_df["video_id"].isin(history_ids)].copy()
    print(f"   新素材: {len(new_df)} 条 (从 {len(task1_df)} 条中)")

    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(OUTPUT_DIR, f"task2_new_material_{today}.csv")
    new_df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"   ✓ 需求2完成: {path}")

    # 更新历史记录
    history_ids.update(task1_df["video_id"].tolist())
    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(history_file, "w") as f:
        json.dump(list(history_ids), f)
    print(f"   ✓ 历史记录已更新: {len(history_ids)} 条")

    preview(new_df)
    return new_df


# =============================================================================
# 需求3: 发现视频 美国 近3天 带货 播放量200K+
# =============================================================================
def task3_discover_video(page):
    """需求3: 发现视频"""
    print("\n" + "=" * 60)
    print("需求3: 发现视频 美国 近3天 带货 播放量 >= 200K")
    print("=" * 60)

    now = datetime.now()
    begin = (now - timedelta(days=3)).strftime("%Y-%m-%d 00:00:00")
    end = now.strftime("%Y-%m-%d 23:59:59")

    all_videos = []
    page_no = 1

    while True:
        print(f"   第 {page_no} 页...", end=" ")
        result = page.evaluate(f"""
            async () => {{
                const resp = await fetch('/api/analysis/video-search/videoListV2', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        pageNo: {page_no},
                        pageSize: 20,
                        region: 'US',
                        sortField: 'play_count_total',
                        videoCreateTimeBegin: '{begin}',
                        videoCreateTimeEnd: '{end}',
                        itemVideoFlag: 1
                    }})
                }});
                return await resp.json();
            }}
        """)

        data = result.get("result", {}).get("data", [])
        total = result.get("result", {}).get("total", 0)

        if not data:
            print("无数据")
            break

        min_play = min(v.get("playCountTotal", 0) for v in data)
        print(f"{len(data)} 条 (总 {total}), 最小播放: {min_play:,}")

        for v in data:
            play_count = v.get("playCountTotal", 0)

            # 判断是否最近1天内的视频，降低播放量门槛
            ct_str = v.get("createTime", "")
            try:
                ct_dt = datetime.strptime(ct_str[:19], "%Y-%m-%dT%H:%M:%S") if "T" in ct_str else datetime.strptime(ct_str[:19], "%Y-%m-%d %H:%M:%S")
                is_recent = (datetime.now() - ct_dt).total_seconds() < 86400
            except Exception:
                is_recent = False
            threshold = MIN_VIEWS_RECENT if is_recent else MIN_VIEWS
            if play_count < threshold:
                continue

            # 排除分类
            cat1 = v.get("itemTkLv1Name", "") or ""
            cat2 = v.get("itemTkLv2Name", "") or ""
            item_name = v.get("itemName", "") or ""

            if is_excluded(item_name=f"{item_name} {cat1} {cat2}".lower()):
                continue

            scores = calc_score(play_count, v.get("createTime", ""))

            all_videos.append({
                "video_id": v.get("videoId"),
                "video_cover": v.get("videoCoverUrl") or "",
                "video_desc": (v.get("videoDesc") or "")[:100],
                "video_url": v.get("tkVideoUrl") or "",
                "create_time": v.get("createTime") or "",
                "views": play_count,
                "likes": v.get("likeCountTotal", 0),
                "shares": v.get("shareCountTotal", 0),
                "comments": v.get("commentCountTotal", 0),
                "interaction_rate": v.get("interactionRate", 0),
                "creator_name": v.get("authorNickname", ""),
                "creator_id": v.get("authorUniqueId", ""),
                "creator_avatar": v.get("authorAvatarUrl") or "",
                "creator_followers": v.get("authorFollowerCountTotal", 0),
                "item_name": item_name,
                "item_cover": v.get("itemCoverUrl") or "",
                "item_price": (v.get("priceAmount") or {}).get("region", ""),
                "item_sold_total": v.get("itemSoldCountTotal", 0),
                "item_category_l1": cat1,
                "item_category_l2": cat2,
                "video_sold_count": v.get("videoSplitSoldCount", 0),
                "time_score": scores["time_score"],
            })

        if min_play < MIN_VIEWS_RECENT:
            break

        page_no += 1
        if page_no > 50:  # 安全限制
            break
        time.sleep(0.5)

    df = pd.DataFrame(all_videos)
    if not df.empty:
        df = df.drop_duplicates(subset=["video_id"], keep="first")
        df = finalize_scores(df)

    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(OUTPUT_DIR, f"task3_discover_video_{today}.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n   ✓ 需求3完成: {path} ({len(df)} 条)")
    preview(df)
    return df


# =============================================================================
# 需求4: 商品榜新品发现
# =============================================================================
def task4_new_product(page):
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
            input_params = json.dumps({
                "pageNo": page_no,
                "pageSize": 24,
                "rankType": 1,
                "bizDate": biz_date,
                "region": "US",
                "categoryId": "0",
                "orderType": "1",
                "sellerType": ""
            })

            result = page.evaluate(f"""
                async () => {{
                    const params = encodeURIComponent(JSON.stringify({input_params}));
                    const resp = await fetch('/api/trpc/ranking.goods.rankingData?input=' + params);
                    return await resp.json();
                }}
            """)

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
    history_file = os.path.join(HISTORY_DIR, "product_history.json")
    history_ids = set()
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            history_ids = set(json.load(f))
    print(f"   历史记录: {len(history_ids)} 条")

    new_df = df[~df["item_id"].isin(history_ids)].copy() if not df.empty else pd.DataFrame()
    print(f"   新商品: {len(new_df)} 条 (从 {len(df)} 条中)")

    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(OUTPUT_DIR, f"task4_new_product_{today}.csv")
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
    print("=" * 60)
    print("TabCut 自动选品工具")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
        )
        page = context.new_page()

        try:
            login(page)

            # 需求1: 视频榜日榜
            df1 = task1_video_rank(page)

            # 需求2: 新素材发现（基于需求1数据）
            df2 = task2_new_material(page, task1_df=df1)

            # 需求3: 发现视频
            df3 = task3_discover_video(page)

            # 需求4: 商品榜新品
            df4 = task4_new_product(page)

            # 汇总
            print("\n" + "=" * 60)
            print("全部完成!")
            print("=" * 60)
            print(f"   需求1 视频榜日榜: {len(df1)} 条")
            print(f"   需求2 新素材发现: {len(df2)} 条")
            print(f"   需求3 发现视频:   {len(df3)} 条")
            print(f"   需求4 新品发现:   {len(df4)} 条")
            print(f"\n   文件保存在: {OUTPUT_DIR}")

        except Exception as e:
            print(f"\n错误: {e}")
            import traceback
            traceback.print_exc()
            page.screenshot(path=os.path.join(OUTPUT_DIR, "error_screenshot.png"))

        finally:
            time.sleep(5)
            browser.close()


if __name__ == "__main__":
    main()
