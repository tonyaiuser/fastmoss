#!/usr/bin/env python3
"""获取 TabCut US 地区的商品分类列表"""
import os, time, json
from playwright.sync_api import sync_playwright

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "tabcut_explore")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1920, "height": 1080}, locale="en-US")

    # 登录
    page.goto("https://www.tabcut.com/workbench?loginType=signIn")
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    page.locator('input[name="email"]').fill("zhy0804@ycimedia.com")
    page.locator('input[type="password"]').fill("9RMapT4QDKspVvp")
    page.evaluate("""() => { document.querySelectorAll('button').forEach(b => { if(b.textContent.trim() === 'Log in') b.click(); }); }""")
    time.sleep(5)
    print("登录完成")

    # 获取US分类
    result = page.evaluate("""
        async () => {
            const resp = await fetch('/api/common/goodsTypeList?region=US');
            return await resp.json();
        }
    """)
    with open(os.path.join(OUTPUT_DIR, "us_categories.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n=== US 地区商品分类 ===")
    for cat in result.get("result", []):
        name = cat.get("categoryName", "")
        cid = cat.get("categoryId", "")
        cn_name = cat.get("tkLv2Categories", [{}])[0].get("categoryNameCn", "") if cat.get("tkLv2Categories") else ""
        print(f"  ID={cid:3d} {name:30s}")

    # 测试视频榜 API 参数
    print("\n=== 测试视频榜 API ===")
    # rankDay=1 日榜, sort=10 按播放量
    result = page.evaluate("""
        async () => {
            const resp = await fetch('/api/ranking/videos?region=US&regionId=1&rankDay=1&itemCategoryId=0&sort=10&pageNo=1&pageSize=24');
            return await resp.json();
        }
    """)
    print(f"total: {result.get('result', {}).get('total')}")
    data = result.get("result", {}).get("data", [])
    if data:
        v = data[0]
        print(f"第一条 keys: {list(v.keys())}")
        print(f"  playCount={v.get('playCount')} rank={v.get('rank')} createTime={v.get('createTime')}")
        items = v.get("itemList", [])
        if items:
            print(f"  商品: {items[0].get('itemName', '')[:50]}")
            print(f"  商品分类字段: itemCategoryId 在视频数据中? {'itemCategoryId' in str(v)}")

    # 检查视频数据中是否有分类信息
    print(f"\n视频数据完整字段: {list(data[0].keys()) if data else 'empty'}")

    # 测试发现视频 API
    print("\n=== 测试发现视频 API ===")
    result2 = page.evaluate("""
        async () => {
            const resp = await fetch('/api/analysis/video-search/videoListV2', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    pageNo: 1,
                    pageSize: 20,
                    region: 'US',
                    sortField: 'video_sold_count',
                    videoCreateTimeBegin: '2026-03-19 00:00:00',
                    videoCreateTimeEnd: '2026-03-22 23:59:59',
                    itemVideoFlag: 1
                })
            });
            return await resp.json();
        }
    """)
    print(f"total: {result2.get('result', {}).get('total')}")
    d2 = result2.get("result", {}).get("data", [])
    if d2:
        print(f"第一条 keys: {list(d2[0].keys())}")

    browser.close()
