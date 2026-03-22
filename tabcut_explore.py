#!/usr/bin/env python3
"""
探索 TabCut (tabcut.com) 的 API 结构
登录 -> 导航到视频榜/发现视频/商品榜 -> 拦截 API 请求
"""

import json
import os
import time
from playwright.sync_api import sync_playwright

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "tabcut_explore")
os.makedirs(OUTPUT_DIR, exist_ok=True)

USERNAME = "zhy0804@ycimedia.com"
PASSWORD = "9RMapT4QDKspVvp"

api_responses = []


def capture_response(response):
    """拦截 API 响应"""
    url = response.url
    if "api" in url.lower() or "graphql" in url.lower():
        try:
            ct = response.headers.get("content-type", "")
            if "json" in ct and response.ok:
                data = response.json()
                api_responses.append({"url": url, "data": data})
        except Exception:
            pass


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
        )
        page = context.new_page()
        page.on("response", capture_response)

        # === Step 1: 登录 ===
        print("=" * 60)
        print("Step 1: 登录 TabCut")
        print("=" * 60)

        page.goto("https://www.tabcut.com/workbench?loginType=signIn")
        page.wait_for_load_state("networkidle")
        time.sleep(3)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "01_login_page.png"))

        # 查找所有输入框
        print("\n可见输入框:")
        inputs = page.locator("input:visible").all()
        for inp in inputs:
            try:
                itype = inp.get_attribute("type") or ""
                ph = inp.get_attribute("placeholder") or ""
                name = inp.get_attribute("name") or ""
                print(f"  type={itype} placeholder='{ph}' name='{name}'")
            except:
                pass

        # 查找登录相关按钮和链接
        print("\n可见按钮:")
        buttons = page.locator("button:visible").all()
        for btn in buttons:
            try:
                text = btn.inner_text().strip()[:50]
                print(f"  button: '{text}'")
            except:
                pass

        # 填写邮箱和密码
        try:
            # 邮箱
            email_input = page.locator('input[type="email"], input[placeholder*="email" i], input[placeholder*="邮箱"], input[name="email"], input[name="username"]').first
            if not email_input.is_visible(timeout=3000):
                email_input = page.locator('input[type="text"]:visible').first
            email_input.fill(USERNAME)
            print(f"\n✓ 填写邮箱: {USERNAME}")
        except Exception as e:
            print(f"\n⚠ 邮箱填写失败: {e}")

        try:
            pwd_input = page.locator('input[type="password"]').first
            pwd_input.fill(PASSWORD)
            print("✓ 填写密码")
        except Exception as e:
            print(f"⚠ 密码填写失败: {e}")

        time.sleep(0.5)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "02_login_filled.png"))

        # 点击登录按钮
        try:
            login_btn = page.locator('button:has-text("Sign In"), button:has-text("Log In"), button:has-text("登录"), button[type="submit"]').first
            login_btn.click()
            print("✓ 点击登录按钮")
        except Exception:
            # JS click fallback
            page.evaluate("""
                () => {
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        const text = btn.textContent.trim().toLowerCase();
                        if (text.includes('sign in') || text.includes('log in') || text.includes('登录')) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            print("✓ JS 点击登录按钮")

        page.wait_for_load_state("networkidle")
        time.sleep(5)
        page.screenshot(path=os.path.join(OUTPUT_DIR, "03_after_login.png"))
        print(f"登录后 URL: {page.url}")

        # === Step 2: 探索导航 ===
        print("\n" + "=" * 60)
        print("Step 2: 探索导航菜单")
        print("=" * 60)

        # 打印所有链接
        print("\n页面中的链接:")
        links = page.locator("a:visible").all()
        for link in links[:50]:
            try:
                href = link.get_attribute("href") or ""
                text = link.inner_text().strip()[:40]
                if text or href:
                    print(f"  [{text}] -> {href}")
            except:
                pass

        # === Step 3: 导航到视频榜 ===
        print("\n" + "=" * 60)
        print("Step 3: 视频榜页面")
        print("=" * 60)

        api_responses.clear()
        # 尝试多个可能的 URL
        video_urls = [
            "https://www.tabcut.com/workbench/video/top",
            "https://www.tabcut.com/workbench/top-videos",
            "https://www.tabcut.com/ranking/video",
            "https://www.tabcut.com/workbench/videos",
        ]

        # 先尝试点击导航菜单中的视频相关链接
        for text in ["Top videos", "视频榜", "Videos", "Top Videos"]:
            try:
                el = page.locator(f'a:has-text("{text}"), [class*="menu"] :has-text("{text}")').first
                if el.is_visible(timeout=2000):
                    el.click()
                    time.sleep(3)
                    page.wait_for_load_state("networkidle")
                    print(f"  ✓ 点击了: '{text}', 当前 URL: {page.url}")
                    page.screenshot(path=os.path.join(OUTPUT_DIR, "04_video_page.png"))
                    break
            except:
                continue

        # 如果没找到，尝试直接访问 URL
        if not any("video" in r.get("url", "").lower() for r in api_responses):
            for url in video_urls:
                try:
                    page.goto(url, timeout=10000)
                    page.wait_for_load_state("networkidle")
                    time.sleep(3)
                    if "404" not in page.title().lower() and "not found" not in page.title().lower():
                        print(f"  ✓ 访问了: {url}, 当前 URL: {page.url}")
                        page.screenshot(path=os.path.join(OUTPUT_DIR, "04_video_page.png"))
                        break
                except:
                    continue

        # 保存视频榜 API 响应
        save_api_responses("video_rank")

        # === Step 4: 发现视频 ===
        print("\n" + "=" * 60)
        print("Step 4: 发现视频页面")
        print("=" * 60)

        api_responses.clear()
        for text in ["All videos", "发现视频", "Discover", "Video Search"]:
            try:
                el = page.locator(f'a:has-text("{text}"), [class*="menu"] :has-text("{text}")').first
                if el.is_visible(timeout=2000):
                    el.click()
                    time.sleep(3)
                    page.wait_for_load_state("networkidle")
                    print(f"  ✓ 点击了: '{text}', 当前 URL: {page.url}")
                    page.screenshot(path=os.path.join(OUTPUT_DIR, "05_discover_video.png"))
                    break
            except:
                continue

        save_api_responses("discover_video")

        # === Step 5: 商品榜 ===
        print("\n" + "=" * 60)
        print("Step 5: 商品榜页面")
        print("=" * 60)

        api_responses.clear()
        for text in ["Top products", "商品榜", "Products", "Top Products"]:
            try:
                el = page.locator(f'a:has-text("{text}"), [class*="menu"] :has-text("{text}")').first
                if el.is_visible(timeout=2000):
                    el.click()
                    time.sleep(3)
                    page.wait_for_load_state("networkidle")
                    print(f"  ✓ 点击了: '{text}', 当前 URL: {page.url}")
                    page.screenshot(path=os.path.join(OUTPUT_DIR, "06_product_page.png"))
                    break
            except:
                continue

        save_api_responses("product_rank")

        # 最终截图和信息
        print("\n" + "=" * 60)
        print("探索完成!")
        print("=" * 60)

        time.sleep(5)
        browser.close()


def save_api_responses(prefix):
    """保存当前收集的 API 响应"""
    print(f"\n  捕获到 {len(api_responses)} 个 API 响应:")
    for i, resp in enumerate(api_responses):
        url = resp["url"]
        data = resp["data"]
        # 保存完整 JSON
        filepath = os.path.join(OUTPUT_DIR, f"{prefix}_api_{i}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(resp, f, ensure_ascii=False, indent=2)

        # 打印摘要
        print(f"  [{i}] {url[:120]}")
        if isinstance(data, dict):
            for k, v in list(data.items())[:5]:
                vtype = type(v).__name__
                vlen = len(v) if isinstance(v, (list, dict, str)) else ""
                print(f"      {k}: {vtype}({vlen})")
                if isinstance(v, dict):
                    for k2, v2 in list(v.items())[:3]:
                        print(f"        {k2}: {type(v2).__name__}")
                elif isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                    print(f"        [0] keys: {list(v[0].keys())[:10]}")


if __name__ == "__main__":
    main()
