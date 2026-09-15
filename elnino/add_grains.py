#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
厄尔尼诺研究 — 豆粕/豆油/玉米 接入
读 grains_price.json(CBOT日度) + corn_prod.json(玉米年度产量)：
  1. 价格：日度→月度(月末收盘)→9事件×5窗口收益率→写入 price
  2. 玉米产量：对数去趋势(前10年滚动)→作物年度窗口(pre/post1/post2/post3)→写入 production
  3. 豆粕/豆油无独立产量(大豆压榨副产品)，归因时复用大豆产量(US/BR)——由 add_attribution.py 的 PRICE_TO_PROD 处理
用法: python3 add_grains.py
"""
import json, os, math

BASE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE, "data", "elnino_data.json")
GRAINS_PATH = os.path.join(BASE, "data", "grains_price.json")
CORN_PATH = os.path.join(BASE, "data", "corn_prod.json")

PRICE_CODES = {"M": "豆粕(CBOT)", "Y": "豆油(CBOT)", "C": "玉米(CBOT)"}
PRICE_NAMES = {"M": "豆粕", "Y": "豆油", "C": "玉米"}
CORN_CODES = {"CUS": "玉米产量(美国)", "CCN": "玉米产量(中国)", "CBR": "玉米产量(巴西)"}


def month_add(ym, n):
    """YYYY-MM 加减 n 月"""
    y, m = int(ym[:4]), int(ym[5:7])
    total = y * 12 + (m - 1) + n
    ny, nm = total // 12, total % 12 + 1
    return f"{ny:04d}-{nm:02d}"


def ret(monthly, m0, m1):
    a, b = monthly.get(m0), monthly.get(m1)
    if a is None or b is None or a == 0:
        return None
    return round((b / a - 1) * 100, 1)


def calc_windows(monthly, e):
    """从月度价格序列算 5 窗口收益率（skill 口径：close(m_end)/close(m_start-1)-1）"""
    peak = e["peak"]
    return {
        "pre": ret(monthly, month_add(e["start"], -1), month_add(peak, -1)),
        "peak_w": ret(monthly, month_add(peak, -2), month_add(peak, 1)),
        "post0_6": ret(monthly, month_add(peak, -1), month_add(peak, 6)),
        "post6_12": ret(monthly, month_add(peak, 5), month_add(peak, 12)),
        "post12_24": ret(monthly, month_add(peak, 11), month_add(peak, 24)),
    }


def daily_to_monthly(rows):
    """日度 [[date,val],...] → 月度 {YYYY-MM: 月末收盘}"""
    m = {}
    for d, v in rows:
        m[d[:7]] = v  # 末次覆盖=月末
    return m


def rolling_detrend(pdict, window=10, min_years=5):
    """前 window 年滚动对数线性回归，返回 {year: 超趋势偏离%}"""
    years = sorted(int(y) for y in pdict.keys())
    dev = {}
    for y in years:
        prev = [yy for yy in range(y - window, y) if yy in years]
        if len(prev) < min_years:
            dev[y] = None
            continue
        lns = [math.log(pdict[str(yy)]) for yy in prev]
        n = len(prev)
        tm = sum(prev) / n
        lm = sum(lns) / n
        b = sum((prev[i] - tm) * (lns[i] - lm) for i in range(n)) / sum((prev[i] - tm) ** 2 for i in range(n))
        a = lm - b * tm
        trend = math.exp(a + b * y)
        dev[y] = round((pdict[str(y)] - trend) / trend * 100, 1)
    return dev


def baseline_dev(pdict, window=5):
    """前5年基线偏离，返回 {year: 偏离%}"""
    years = sorted(int(y) for y in pdict.keys())
    dev = {}
    for y in years:
        prev = [yy for yy in range(y - window, y) if yy in years]
        if len(prev) < window:
            dev[y] = None
            continue
        base = sum(pdict[str(yy)] for yy in prev) / len(prev)
        dev[y] = round((pdict[str(y)] - base) / base * 100, 1) if base else None
    return dev


def window_map(peak_ym):
    """作物年度窗口映射：峰值年 Y，pre→Y, post1→Y+1, post2→Y+2, post3→Y+3"""
    Y = int(peak_ym[:4])
    return {"pre": Y, "post1": Y + 1, "post2": Y + 2, "post3": Y + 3}


def main():
    grains = json.load(open(GRAINS_PATH))
    corn = json.load(open(CORN_PATH))
    d = json.load(open(JSON_PATH))
    events = d["events"]

    # ===== 1. 价格口径 =====
    print("=== 价格口径（CBOT 日度→月度→5窗口）===", flush=True)
    for code, cname in PRICE_CODES.items():
        monthly = daily_to_monthly(grains[code])
        for e in events:
            w = calc_windows(monthly, e)
            d["price"]["results"].append({
                "event": e["id"], "grade": e["grade"], "peak": e["peak"],
                "commodity": code, "name": PRICE_NAMES[code],
                **w,
            })
        # 聚合均值
        rows = [r for r in d["price"]["results"] if r["commodity"] == code]
        agg = {"name": cname}
        for win in ["pre", "peak_w", "post0_6", "post6_12", "post12_24"]:
            vals = [r[win] for r in rows if r[win] is not None]
            agg[win] = round(sum(vals) / len(vals), 1) if vals else None
        d["price"]["agg_by_commodity"][code] = agg
        print(f"  {code} {cname}: 均值 pre={agg['pre']} peak_w={agg['peak_w']} post0_6={agg['post0_6']} post6_12={agg['post6_12']} post12_24={agg['post12_24']}", flush=True)

    d["price"]["commodities"].update(PRICE_CODES)

    # ===== 2. 玉米产量口径 =====
    print("\n=== 玉米产量（去趋势）===", flush=True)
    # corn_prod.json 是 [[date, val], ...]，年度，转 {year: val}
    corn_series = {}
    for code in CORN_CODES:
        rows = corn.get(code, [])
        s = {}
        for dd, v in rows:
            s[str(int(dd[:4]))] = v
        corn_series[code] = s
        print(f"  {code} {CORN_CODES[code]}: {len(s)}年", flush=True)

    detrended = {c: rolling_detrend(corn_series[c]) for c in CORN_CODES}
    baseline = {c: baseline_dev(corn_series[c]) for c in CORN_CODES}

    def build_results(dev_map, gran):
        results, agg = [], {}
        for code in CORN_CODES:
            dev = dev_map[code]
            agg[code] = {"name": CORN_CODES[code], "pre": [], "post1": [], "post2": [], "post3": []}
            for e in events:
                wm = window_map(e["peak"])
                row = {"commodity": code, "name": CORN_CODES[code], "gran": gran,
                       "event": e["id"], "grade": e["grade"], "peak": e["peak"],
                       "pre": dev.get(wm["pre"]), "post1": dev.get(wm["post1"]),
                       "post2": dev.get(wm["post2"]), "post3": dev.get(wm["post3"])}
                results.append(row)
                for w in ["pre", "post1", "post2", "post3"]:
                    if row[w] is not None:
                        agg[code][w].append(row[w])
        for code in agg:
            for w in ["pre", "post1", "post2", "post3"]:
                vals = agg[code][w]
                agg[code][w] = round(sum(vals) / len(vals), 1) if vals else None
        return results, agg

    det_results, det_agg = build_results(detrended, "年度(去趋势)")
    bl_results, bl_agg = build_results(baseline, "年度")

    prod = d["production"]
    for code, name in CORN_CODES.items():
        prod["commodities"][code] = name
    for key, results, agg in [("detrended", det_results, det_agg), ("baseline", bl_results, bl_agg)]:
        prod[key]["results"] = [r for r in prod[key]["results"] if r["commodity"] not in CORN_CODES]
        prod[key]["results"].extend(results)
        for code in CORN_CODES:
            prod[key]["agg_by_commodity"][code] = agg[code]

    # 打印玉米产量去趋势 post1 摘要
    print(f"\n  {'事件':<8}{'美玉米':>9}{'中玉米':>9}{'巴玉米':>9}", flush=True)
    for e in events:
        wm = window_map(e["peak"])
        row = {c: detrended[c].get(wm["post1"]) for c in CORN_CODES}
        def g(x): return "—" if x is None else f"{x:+.1f}"
        print(f"  {e['id']:<8}{g(row['CUS']):>9}{g(row['CCN']):>9}{g(row['CBR']):>9}", flush=True)

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"\n已写入 price(豆粕/豆油/玉米) + production(玉米产量) 到 {JSON_PATH}", flush=True)


if __name__ == "__main__":
    main()
