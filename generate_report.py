#!/usr/bin/env python3
"""
生成 HTML 报告页面，展示4个需求的数据
功能: 商品名中文翻译、图片展示、列排序、7天过滤、搜索
"""

import argparse
import os
import json
from datetime import datetime

import pandas as pd
from deep_translator import GoogleTranslator

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

REGIONS = {"US": "美国", "GB": "英国"}


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


def batch_translate(texts, max_chars=4500):
    """批量翻译英文商品名为中文，返回 {英文: 中文} 字典"""
    translator = GoogleTranslator(source="en", target="zh-CN")
    result = {}
    unique_texts = list(set(t for t in texts if t and str(t) != "nan"))

    print(f"   翻译 {len(unique_texts)} 个商品名...")

    # 动态分批: 确保每批拼接后不超过 max_chars
    batch = []
    batch_len = 0
    batch_no = 0

    def flush(batch):
        nonlocal batch_no
        if not batch:
            return
        joined = "\n".join(t[:80] for t in batch)
        try:
            translated = translator.translate(joined)
            parts = translated.split("\n")
            for orig, trans in zip(batch, parts):
                result[orig] = trans.strip()
        except Exception as e:
            print(f"   翻译出错(batch {batch_no}): {e}")
            # 逐条翻译兜底
            for t in batch:
                try:
                    result[t] = translator.translate(t[:80])
                except Exception:
                    result[t] = ""
        batch_no += 1

    for t in unique_texts:
        piece = t[:80]
        if batch_len + len(piece) + 1 > max_chars:
            flush(batch)
            batch = []
            batch_len = 0
        batch.append(t)
        batch_len += len(piece) + 1  # +1 for newline

    flush(batch)
    print(f"   翻译完成: {len(result)}/{len(unique_texts)}")
    return result


def img_html(url, size=52):
    """生成图片HTML"""
    url = str(url) if url and str(url) != "nan" else ""
    if not url:
        return f'<div class="img-placeholder" style="width:{size}px;height:{size}px;">无图</div>'
    return f'<img src="{url}" loading="lazy" class="thumb" style="width:{size}px;height:{size}px;" onerror="this.style.display=\'none\'" onclick="showImg(this.src)">'


def generate_html(region="US"):
    region = (region or "US").upper()
    region_name = REGIONS.get(region, region)
    today = datetime.now().strftime("%Y-%m-%d")

    df1 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task1_video_rank_{region}_{today}.csv"))
    df2 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task2_new_material_{region}_{today}.csv"))
    df3 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task3_discover_video_{region}_{today}.csv"))
    df4 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task4_new_product_{region}_{today}.csv"))
    diagnostics_path = os.path.join(OUTPUT_DIR, f"diagnostics_{region}_{today}.json")

    if df1.empty:
        for f in sorted(os.listdir(OUTPUT_DIR), reverse=True):
            if f.startswith(f"task1_video_rank_{region}_") and f.endswith(".csv"):
                df1 = pd.read_csv(os.path.join(OUTPUT_DIR, f))
                today = f.replace(f"task1_video_rank_{region}_", "").replace(".csv", "")
                df2 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task2_new_material_{region}_{today}.csv"))
                df3 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task3_discover_video_{region}_{today}.csv"))
                df4 = read_csv_safe(os.path.join(OUTPUT_DIR, f"task4_new_product_{region}_{today}.csv"))
                diagnostics_path = os.path.join(OUTPUT_DIR, f"diagnostics_{region}_{today}.json")
                break

    diag_entries = []
    if os.path.exists(diagnostics_path):
        try:
            with open(diagnostics_path, "r", encoding="utf-8") as f:
                diag_entries = (json.load(f) or {}).get("entries", [])
        except Exception:
            diag_entries = []

    # 收集所有需要翻译的商品名
    print("正在翻译商品名...")
    all_item_names = []
    for df in [df1, df2, df3, df4]:
        if not df.empty and "item_name" in df.columns:
            all_item_names.extend(df["item_name"].dropna().tolist())

    trans_map = batch_translate(all_item_names)

    def get_cn(name):
        name = str(name) if name and str(name) != "nan" else ""
        return trans_map.get(name, "")

    def video_rows(df, is_discover=False):
        if df.empty:
            return '<tr><td colspan="10" class="empty">暂无数据</td></tr>'
        rows = []
        for i, (_, r) in enumerate(df.iterrows(), 1):
            score = r.get("total_score", 0)
            sc = "hi" if score >= 60 else "mid" if score >= 40 else "lo"
            views = r.get("views", 0)
            likes = r.get("likes", 0)
            ct = str(r.get("create_time", ""))[:16]
            # 判断是否最近2天
            try:
                ct_parsed = ct.replace("T", " ")
                from datetime import datetime as _dt
                ct_dt = _dt.strptime(ct_parsed[:16], "%Y-%m-%d %H:%M")
                is_fresh = (_dt.now() - ct_dt).total_seconds() < 2 * 86400
            except Exception:
                is_fresh = False
            fresh_cls = " fresh" if is_fresh else ""
            creator = r.get("creator_name", "")
            desc = str(r.get("video_desc", ""))[:60]
            item = str(r.get("item_name", ""))[:60]
            item_cn = get_cn(r.get("item_name", ""))
            vurl = r.get("video_url", "")
            vurl_str = str(vurl) if vurl and str(vurl) != "nan" else ""
            vc = str(r.get("video_cover", ""))
            ic = str(r.get("item_cover", ""))
            vc = "" if vc in ("", "nan") else vc
            ic = "" if ic in ("", "nan") else ic
            # fallback: video_cover 为空时用 item_cover 代替
            if not vc:
                vc = ic

            # 标签: 爆发中 / 高互动
            tags_html = ""
            velocity_score = r.get("velocity_score", 0)
            engagement_score = r.get("engagement_score", 0)
            if velocity_score >= 70:
                tags_html += '<span class="tag-burst">爆发中</span> '
            if engagement_score >= 70:
                tags_html += '<span class="tag-engage">高互动</span> '

            extra = ""
            if is_discover:
                cat = r.get("item_category_l1", "") or ""
                sold = r.get("video_sold_count", 0)
                extra = f'<span class="tag">分类:{cat}</span> <span class="tag">带货:{fmt_number(sold)}</span>'

            link_html = f'<a href="{vurl_str}" target="_blank" rel="noopener">打开</a>' if vurl_str else ''

            rows.append(f'''<tr data-time="{ct}" data-views="{views}" data-score="{score}">
<td class="center">{i}</td>
<td class="center"><span class="score {sc}">{score:.0f}</span> {tags_html}</td>
<td>{img_html(vc, 48)}</td>
<td>{img_html(ic, 48)}</td>
<td class="cell-item">
  <div class="item-cn">{item_cn}</div>
  <div class="item-en">{item}</div>
  {extra}
</td>
<td class="right num">{fmt_number(views)}</td>
<td class="right">{fmt_number(likes)}</td>
<td class="nowrap{fresh_cls}">{ct}</td>
<td class="center">{link_html}</td>
<td class="cell-main">
  <div class="creator">{creator}</div>
  <div class="desc">{desc}</div>
</td>
</tr>''')
        return "\n".join(rows)

    def product_rows(df):
        if df.empty:
            return '<tr><td colspan="10" class="empty">暂无数据</td></tr>'
        rows = []
        for i, (_, r) in enumerate(df.iterrows(), 1):
            name = str(r.get("item_name", ""))[:60]
            name_cn = get_cn(r.get("item_name", ""))
            cat = r.get("category", "")
            price = r.get("price", "")
            sold_p = r.get("sold_period", 0)
            sold_t = r.get("sold_total", 0)
            gmv = r.get("gmv_period", 0)
            seller = r.get("seller_name", "")
            comm = r.get("commission_rate", 0)
            ic = r.get("item_cover", "")
            try:
                comm_s = f"{float(comm)*100:.0f}%"
            except (ValueError, TypeError):
                comm_s = str(comm)

            rows.append(f'''<tr data-sold="{sold_p}">
<td class="center">{r.get('rank', i)}</td>
<td>{img_html(ic, 52)}</td>
<td class="cell-item">
  <div class="item-cn">{name_cn}</div>
  <div class="item-en">{name}</div>
  <div class="cat">{cat}</div>
</td>
<td class="right">${price}</td>
<td class="right num">{fmt_number(sold_p)}</td>
<td class="right">{fmt_number(sold_t)}</td>
<td class="right">${fmt_number(gmv)}</td>
<td>{seller}</td>
<td class="center">{comm_s}</td>
</tr>''')
        return "\n".join(rows)

    def decision_rows(df):
        if df.empty:
            return '<tr><td colspan="10" class="empty">暂无数据</td></tr>'
        rows = []
        for i, (_, r) in enumerate(df.iterrows(), 1):
            score = float(r.get("decision_score", 0) or 0)
            sc = "hi" if score >= 70 else "mid" if score >= 45 else "lo"
            sample_url = str(r.get("sample_video_url", ""))
            link_html = f'<a href="{sample_url}" target="_blank" rel="noopener">样本</a>' if sample_url and sample_url != "nan" else ""
            rows.append(f'''<tr>
<td class="center">{i}</td>
<td class="center"><span class="score {sc}">{score:.0f}</span></td>
<td>{img_html(r.get("sample_video_cover", "") or r.get("item_cover", ""), 48)}</td>
<td>{img_html(r.get("item_cover", ""), 48)}</td>
<td class="cell-item">
  <div class="item-cn">{get_cn(r.get("item_name", ""))}</div>
  <div class="item-en">{str(r.get("item_name", ""))[:60]}</div>
  <div class="cat">{r.get("item_category_l1", "")}</div>
</td>
<td class="right num">{fmt_number(r.get("videos", 0))}</td>
<td class="right">{fmt_number(r.get("creators", 0))}</td>
<td class="right">{fmt_number(r.get("sum_views", 0))}</td>
<td class="center">{link_html}</td>
<td class="cell-main">
  <div class="creator">{r.get("sample_creator_name", "")}</div>
  <div class="desc">{str(r.get("sample_video_desc", ""))[:60]}</div>
</td>
</tr>''')
        return "\n".join(rows)

    diag_html = "".join(
        f'<div class="diag {e.get("level", "info")}"><b>{e.get("task", "-")}</b> · {e.get("message", "")}</div>'
        for e in diag_entries[:8]
    ) or '<div class="diag info">本次没有诊断告警</div>'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>巴巴塔自动选品系统 - {region_name} - {today}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;color:#1f2937;font-size:13px}}
.header{{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:20px 28px}}
.header h1{{font-size:22px;margin-bottom:2px}}
.header .sub{{opacity:.85;font-size:13px}}
.tabs{{display:flex;background:#fff;border-bottom:2px solid #e5e7eb;position:sticky;top:0;z-index:100;box-shadow:0 2px 4px rgba(0,0,0,.05)}}
.tab{{padding:12px 20px;cursor:pointer;font-weight:500;font-size:13px;border-bottom:3px solid transparent;color:#6b7280;white-space:nowrap}}
.tab:hover{{color:#4f46e5;background:#f9fafb}}
.tab.active{{color:#4f46e5;border-bottom-color:#4f46e5}}
.badge{{background:#ef4444;color:#fff;border-radius:10px;padding:1px 7px;font-size:11px;margin-left:5px}}
.tc{{display:none;padding:16px 24px}}
.tc.active{{display:block}}
.stats{{display:flex;gap:12px;margin-bottom:14px;flex-wrap:wrap}}
.hero{{padding:16px 24px;background:#fff;border-bottom:1px solid #e5e7eb}}
.hero-grid{{display:grid;grid-template-columns:2fr 1fr;gap:14px}}
.panel{{background:#fff;border-radius:10px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.diag{{padding:8px 10px;border-radius:8px;margin-bottom:8px;font-size:12px}}
.diag.info{{background:#eff6ff;color:#1d4ed8}}
.diag.warning{{background:#fff7ed;color:#c2410c}}
.diag.error{{background:#fef2f2;color:#dc2626}}
.sc{{background:#fff;border-radius:10px;padding:12px 16px;flex:1;min-width:130px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.sc .lb{{color:#6b7280;font-size:11px;margin-bottom:2px}}
.sc .vl{{font-size:22px;font-weight:700}}
.toolbar{{margin-bottom:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
.toolbar input[type=text]{{padding:7px 14px;border:1px solid #d1d5db;border-radius:8px;font-size:13px;width:280px;outline:none}}
.toolbar input[type=text]:focus{{border-color:#4f46e5;box-shadow:0 0 0 3px rgba(79,70,229,.1)}}
.toolbar label{{font-size:12px;color:#6b7280;cursor:pointer;display:flex;align-items:center;gap:4px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);table-layout:auto}}
th{{background:#f9fafb;padding:8px 10px;text-align:left;font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em;font-weight:600;cursor:pointer;user-select:none;white-space:nowrap}}
th:hover{{background:#eef2ff;color:#4f46e5}}
th .si{{margin-left:3px;opacity:.3;font-size:9px}}
th.asc .si,th.desc .si{{opacity:1;color:#4f46e5}}
td{{padding:8px 10px;border-top:1px solid #f3f4f6;vertical-align:middle}}
tr:hover td{{background:#fafbff}}
.center{{text-align:center}}
.right{{text-align:right}}
.nowrap{{white-space:nowrap}}
.num{{font-weight:600;color:#ef4444}}
.empty{{text-align:center;padding:40px;color:#9ca3af}}
.score{{display:inline-block;font-weight:700;font-size:18px;min-width:32px;text-align:center}}
.hi{{color:#10b981}}.mid{{color:#f59e0b}}.lo{{color:#6b7280}}
.tag-burst{{display:inline-block;background:#fee2e2;color:#dc2626;font-size:10px;padding:1px 5px;border-radius:3px;font-weight:600;margin-top:2px}}
.tag-engage{{display:inline-block;background:#dbeafe;color:#2563eb;font-size:10px;padding:1px 5px;border-radius:3px;font-weight:600;margin-top:2px}}
.thumb{{object-fit:cover;border-radius:6px;cursor:pointer;display:block}}
.img-placeholder{{background:#f3f4f6;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#ccc;font-size:10px}}
.cell-main{{max-width:220px}}
.creator{{font-weight:500;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px}}
.desc{{color:#6b7280;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px;margin-top:1px}}
.cell-item{{max-width:240px}}
.item-cn{{font-weight:500;font-size:12px;color:#1e40af;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:230px}}
.item-en{{font-size:11px;color:#9ca3af;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:230px;margin-top:1px}}
.cat{{font-size:10px;color:#6b7280;margin-top:1px}}
.tag{{display:inline-block;background:#f3f4f6;color:#6b7280;font-size:10px;padding:1px 5px;border-radius:3px;margin-top:2px}}
a{{color:#3b82f6;text-decoration:none;font-size:12px}}
a:hover{{text-decoration:underline}}
.fresh{{color:#10b981;font-weight:600}}
.hidden-row{{display:none!important}}
.modal{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.75);z-index:9999;cursor:pointer;justify-content:center;align-items:center}}
.modal.show{{display:flex}}
.modal img{{max-width:90vw;max-height:90vh;border-radius:8px}}
@media(max-width:768px){{
.header{{padding:14px 16px}}
.header h1{{font-size:18px}}
.tabs{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.tab{{padding:10px 12px;font-size:12px}}
.tc{{padding:10px 12px}}
.stats{{gap:8px}}
.sc{{padding:10px 12px;min-width:80px}}
.sc .vl{{font-size:18px}}
.toolbar{{flex-direction:column;align-items:stretch}}
.toolbar input[type=text]{{width:100%}}
table{{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch}}
thead{{display:table;width:100%;table-layout:auto}}
tbody{{display:table;width:100%;table-layout:auto}}
td,th{{padding:6px 6px;font-size:11px}}
.thumb{{width:36px!important;height:36px!important}}
.img-placeholder{{width:36px!important;height:36px!important}}
.cell-main{{max-width:120px}}
.creator{{font-size:11px;max-width:110px}}
.desc{{display:none}}
.cell-item{{max-width:140px}}
.item-cn{{font-size:11px;max-width:130px}}
.item-en{{display:none}}
.score{{font-size:15px}}
}}
</style>
</head>
<body>
<div class="header">
<h1>巴巴塔自动选品系统</h1>
<div class="sub">数据日期: {today} | 生成: {datetime.now().strftime("%H:%M:%S")} | 地区: {region_name} ({region})</div>
</div>
<div class="hero">
  <div class="hero-grid">
    <div class="panel">
      <div style="font-size:16px;font-weight:700;margin-bottom:8px;">今日决策视图</div>
      <div style="color:#6b7280;line-height:1.8;">A 看高分爆热视频, B 看首次出现的新素材, C 看多视频聚合后的高潜商品, D 看商品榜新增商品。</div>
    </div>
    <div class="panel">
      <div style="font-size:16px;font-weight:700;margin-bottom:8px;">运行诊断</div>
      {diag_html}
    </div>
  </div>
</div>
<div class="tabs">
<div class="tab active" onclick="sw(0)">爆热视频 <span class="badge">{len(df1)}</span></div>
<div class="tab" onclick="sw(1)">新素材榜 <span class="badge">{len(df2)}</span></div>
<div class="tab" onclick="sw(2)">高潜商品 <span class="badge">{len(df3)}</span></div>
<div class="tab" onclick="sw(3)">商品榜新品 <span class="badge">{len(df4)}</span></div>
</div>
<div class="modal" id="modal" onclick="this.classList.remove('show')"><img id="modalImg"></div>

<!-- Tab 0: 视频榜 -->
<div class="tc active" id="t0">
<div class="stats">
<div class="sc"><div class="lb">总视频数</div><div class="vl">{len(df1)}</div></div>
<div class="sc"><div class="lb">最高播放</div><div class="vl">{fmt_number(df1['views'].max()) if not df1.empty else 0}</div></div>
<div class="sc"><div class="lb">平均播放</div><div class="vl">{fmt_number(df1['views'].mean()) if not df1.empty else 0}</div></div>
<div class="sc"><div class="lb">最高评分</div><div class="vl">{(f"{df1['total_score'].max():.0f}" if not df1.empty and 'total_score' in df1.columns else "0")}</div></div>
</div>
<div class="toolbar">
<input type="text" placeholder="搜索达人、商品..." oninput="ft(this,'tb0')">
<label><input type="checkbox" checked onchange="f7(this,'tb0')"> 隐藏7天前</label>
</div>
<table id="tb0"><thead><tr>
<th data-c="0" data-t="n" style="width:32px"># <span class="si">&#9650;&#9660;</span></th>
<th data-c="1" data-t="n" style="width:44px">评分 <span class="si">&#9650;&#9660;</span></th>
<th style="width:56px">视频</th>
<th style="width:56px">商品</th>
<th data-c="4" data-t="s">商品名 <span class="si">&#9650;&#9660;</span></th>
<th data-c="5" data-t="n" style="text-align:right">播放量 <span class="si">&#9650;&#9660;</span></th>
<th data-c="6" data-t="n" style="text-align:right">点赞 <span class="si">&#9650;&#9660;</span></th>
<th data-c="7" data-t="s">发布时间 <span class="si">&#9650;&#9660;</span></th>
<th style="width:36px">链接</th>
<th data-c="9" data-t="s">达人 / 描述 <span class="si">&#9650;&#9660;</span></th>
</tr></thead><tbody>
{video_rows(df1)}
</tbody></table></div>

<!-- Tab 1: 新素材 -->
<div class="tc" id="t1">
<div class="stats">
<div class="sc"><div class="lb">新素材数</div><div class="vl">{len(df2)}</div></div>
<div class="sc"><div class="lb">说明</div><div class="vl" style="font-size:13px">历史从未出现过的视频素材</div></div>
</div>
<div class="toolbar">
<input type="text" placeholder="搜索达人、商品..." oninput="ft(this,'tb1')">
<label><input type="checkbox" checked onchange="f7(this,'tb1')"> 隐藏7天前</label>
</div>
<table id="tb1"><thead><tr>
<th data-c="0" data-t="n" style="width:32px"># <span class="si">&#9650;&#9660;</span></th>
<th data-c="1" data-t="n" style="width:44px">评分 <span class="si">&#9650;&#9660;</span></th>
<th style="width:56px">视频</th>
<th style="width:56px">商品</th>
<th data-c="4" data-t="s">商品名 <span class="si">&#9650;&#9660;</span></th>
<th data-c="5" data-t="n" style="text-align:right">播放量 <span class="si">&#9650;&#9660;</span></th>
<th data-c="6" data-t="n" style="text-align:right">点赞 <span class="si">&#9650;&#9660;</span></th>
<th data-c="7" data-t="s">发布时间 <span class="si">&#9650;&#9660;</span></th>
<th style="width:36px">链接</th>
<th data-c="9" data-t="s">达人 / 描述 <span class="si">&#9650;&#9660;</span></th>
</tr></thead><tbody>
{video_rows(df2)}
</tbody></table></div>

<!-- Tab 2: 高潜商品 -->
<div class="tc" id="t2">
<div class="stats">
<div class="sc"><div class="lb">候选商品数</div><div class="vl">{len(df3)}</div></div>
<div class="sc"><div class="lb">筛选逻辑</div><div class="vl" style="font-size:13px">近3天视频聚合 | 去除与前两栏重合</div></div>
<div class="sc"><div class="lb">最高决策分</div><div class="vl">{(f"{df3['decision_score'].max():.0f}" if not df3.empty and 'decision_score' in df3.columns else '0')}</div></div>
</div>
<div class="toolbar">
<input type="text" placeholder="搜索商品、达人..." oninput="ft(this,'tb2')">
</div>
<table id="tb2"><thead><tr>
<th data-c="0" data-t="n" style="width:32px"># <span class="si">&#9650;&#9660;</span></th>
<th data-c="1" data-t="n" style="width:44px">决策分 <span class="si">&#9650;&#9660;</span></th>
<th style="width:56px">样本视频</th>
<th style="width:56px">商品</th>
<th data-c="4" data-t="s">商品名 <span class="si">&#9650;&#9660;</span></th>
<th data-c="5" data-t="n" style="text-align:right">视频数 <span class="si">&#9650;&#9660;</span></th>
<th data-c="6" data-t="n" style="text-align:right">达人数 <span class="si">&#9650;&#9660;</span></th>
<th data-c="7" data-t="n" style="text-align:right">累计播放 <span class="si">&#9650;&#9660;</span></th>
<th style="width:36px">链接</th>
<th data-c="9" data-t="s">样本说明 <span class="si">&#9650;&#9660;</span></th>
</tr></thead><tbody>
{decision_rows(df3)}
</tbody></table></div>

<!-- Tab 3: 商品榜 -->
<div class="tc" id="t3">
<div class="stats">
<div class="sc"><div class="lb">新商品数</div><div class="vl">{len(df4)}</div></div>
<div class="sc"><div class="lb">说明</div><div class="vl" style="font-size:13px">历史从未出现过的商品</div></div>
</div>
<div class="toolbar">
<input type="text" placeholder="搜索商品、店铺..." oninput="ft(this,'tb3')">
</div>
<table id="tb3"><thead><tr>
<th data-c="0" data-t="n" style="width:36px">排名 <span class="si">&#9650;&#9660;</span></th>
<th style="width:60px">图片</th>
<th data-c="2" data-t="s">商品名 / 分类 <span class="si">&#9650;&#9660;</span></th>
<th data-c="3" data-t="n" style="text-align:right">价格 <span class="si">&#9650;&#9660;</span></th>
<th data-c="4" data-t="n" style="text-align:right">日销量 <span class="si">&#9650;&#9660;</span></th>
<th data-c="5" data-t="n" style="text-align:right">总销量 <span class="si">&#9650;&#9660;</span></th>
<th data-c="6" data-t="n" style="text-align:right">日GMV <span class="si">&#9650;&#9660;</span></th>
<th data-c="7" data-t="s">店铺 <span class="si">&#9650;&#9660;</span></th>
<th data-c="8" data-t="n" style="text-align:center">佣金 <span class="si">&#9650;&#9660;</span></th>
</tr></thead><tbody>
{product_rows(df4)}
</tbody></table></div>

<script>
function sw(i){{document.querySelectorAll('.tab').forEach((t,j)=>t.classList.toggle('active',j===i));document.querySelectorAll('.tc').forEach((c,j)=>c.classList.toggle('active',j===i))}}
function ft(inp,tid){{const q=inp.value.toLowerCase();document.getElementById(tid).querySelectorAll('tbody tr').forEach(r=>{{if(!r.classList.contains('h7'))r.style.display=r.textContent.toLowerCase().includes(q)?'':'none'}})}}
function f7(cb,tid){{const now=Date.now(),lim=7*864e5;document.getElementById(tid).querySelectorAll('tbody tr').forEach(r=>{{const t=r.dataset.time;if(!t)return;const d=new Date(t.replace(' ','T'));if(now-d.getTime()>lim){{if(cb.checked){{r.classList.add('h7','hidden-row')}}else{{r.classList.remove('h7','hidden-row')}}}}}})}}
function showImg(s){{document.getElementById('modalImg').src=s;document.getElementById('modal').classList.add('show')}}
document.querySelectorAll('th[data-c]').forEach(th=>{{th.addEventListener('click',function(){{const tb=this.closest('table'),tbody=tb.querySelector('tbody'),rows=Array.from(tbody.querySelectorAll('tr')),c=+this.dataset.c,t=this.dataset.t,asc=this.classList.contains('asc');tb.querySelectorAll('th').forEach(h=>h.classList.remove('asc','desc'));this.classList.add(asc?'desc':'asc');const d=asc?-1:1;const pn=s=>{{s=s.replace(/[$,%]/g,'').trim();if(s.endsWith('M'))return parseFloat(s)*1e6;if(s.endsWith('K'))return parseFloat(s)*1e3;return parseFloat(s)||0}};rows.sort((a,b)=>{{const va=a.cells[c]?a.cells[c].textContent.trim():'',vb=b.cells[c]?b.cells[c].textContent.trim():'';return t==='n'?(pn(va)-pn(vb))*d:va.localeCompare(vb)*d}});rows.forEach(r=>tbody.appendChild(r))}})}});
document.addEventListener('DOMContentLoaded',()=>{{document.querySelectorAll('.toolbar input[type=checkbox]').forEach(cb=>{{if(cb.checked){{const tid=cb.closest('.tc').querySelector('table').id;f7(cb,tid)}}}})}});
</script>
</body>
</html>"""

    output_path = os.path.join(OUTPUT_DIR, f"report_{region}_{today}.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 同时输出到 docs/ 目录供 GitHub Pages 使用
    docs_dir = os.path.join(BASE_DIR, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    docs_path = os.path.join(docs_dir, f"report_{region}_{today}.html")
    with open(docs_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 生成 index.html：自动展示最新 US / GB 报告入口
    latest_us = ""
    latest_gb = ""
    for name in sorted(os.listdir(docs_dir), reverse=True):
        if not latest_us and name.startswith("report_US_") and name.endswith(".html"):
            latest_us = name
        if not latest_gb and name.startswith("report_GB_") and name.endswith(".html"):
            latest_gb = name
        if latest_us and latest_gb:
            break

    index_html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>巴巴塔自动选品系统</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;padding:32px;background:#f6f8fb;color:#1f2937;">
<h2 style="margin-bottom:8px;">巴巴塔自动选品系统</h2>
<div style="color:#6b7280;margin-bottom:20px;">最新双地区报告入口</div>
<ul style="line-height:2;">
  <li><a href="{latest_us or '#'}">美国站最新报告</a></li>
  <li><a href="{latest_gb or '#'}">英国站最新报告</a></li>
</ul>
</body></html>"""
    with open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    print(f"✓ 报告已生成: {output_path}")
    print(f"✓ Pages 报告: {docs_path}")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="US")
    args = parser.parse_args()
    path = generate_html(region=args.region)
    import subprocess
    subprocess.run(["open", path])
