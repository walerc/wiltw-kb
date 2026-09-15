#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
厄尔尼诺研究 — 白糖产量数据接入
读 sugar_prod.json(印度/泰国/巴西糖产量,年度千吨)，对数去趋势(前10年滚动)，
按作物年度窗口(pre/post1/post2/post3)算偏离，写入 elnino_data.json：
  1. production.commodities 加 IN/TH/BR
  2. production.detrended.results + agg_by_commodity 加白糖产量
  3. attribution 里 SR 的 prod_sources 设为 IN/TH/BR
用法: python3 add_sugar.py
"""
import json, os, math

BASE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE, "data", "elnino_data.json")
SUGAR_PATH = os.path.join(BASE, "data", "sugar_prod.json")

# 白糖产量品种 → 名称。⚠️ 用 SIN/STH/SBR 独立键，避免与橡胶 TH、大豆 BR 冲突
SUGAR_CODES = {"SIN": "糖产量(印度)", "STH": "糖产量(泰国)", "SBR": "糖产量(巴西)"}
# 数据源键 → 输出键（sugar_prod.json 里是 IN/TH/BR）
SRC_KEY = {"SIN": "IN", "STH": "TH", "SBR": "BR"}


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
    sugar = json.load(open(SUGAR_PATH))
    d = json.load(open(JSON_PATH))
    events = d["events"]

    # 1. 各产区去趋势 + 基线偏离
    detrended = {}
    baseline = {}
    for code, name in SUGAR_CODES.items():
        series = sugar["data"][SRC_KEY[code]]["series"]
        detrended[code] = rolling_detrend(series)
        baseline[code] = baseline_dev(series)
        years = sorted(detrended[code].keys())
        n_valid = sum(1 for y in years if detrended[code][y] is not None)
        print(f"{code} ({name}): {len(years)}年, 去趋势有效 {n_valid}年", flush=True)

    # 2. 按事件窗口算偏离（双口径）
    def build_results(dev_map, gran):
        results = []
        agg = {}
        for code, name in SUGAR_CODES.items():
            dev = dev_map[code]
            agg[code] = {"name": name, "pre": [], "post1": [], "post2": [], "post3": []}
            for e in events:
                wm = window_map(e["peak"])
                row = {
                    "commodity": code, "name": name, "gran": gran,
                    "event": e["id"], "grade": e["grade"], "peak": e["peak"],
                    "pre": dev.get(wm["pre"]),
                    "post1": dev.get(wm["post1"]),
                    "post2": dev.get(wm["post2"]),
                    "post3": dev.get(wm["post3"]),
                }
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

    # 3. 写入 production（双口径）
    prod = d["production"]
    for code, name in SUGAR_CODES.items():
        prod["commodities"][code] = name
    # 去重 + 追加
    for key, results, agg in [("detrended", det_results, det_agg), ("baseline", bl_results, bl_agg)]:
        prod[key]["results"] = [r for r in prod[key]["results"] if r["commodity"] not in SUGAR_CODES]
        prod[key]["results"].extend(results)
        for code in SUGAR_CODES:
            prod[key]["agg_by_commodity"][code] = agg[code]

    # 4. 更新 attribution 的 SR prod_sources
    if "attribution" in d and "SR" in d["attribution"].get("commodities", {}):
        d["attribution"]["commodities"]["SR"]["prod_sources"] = [SUGAR_CODES[c] for c in SUGAR_CODES]
        d["attribution"]["commodities"]["SR"]["has_prod_data"] = True

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)

    # 打印事件窗口偏离摘要（去趋势 post1）
    print(f"\n{'事件':<8}{'印度糖':>9}{'泰国糖':>9}{'巴西糖':>9}", flush=True)
    for e in events:
        wm = window_map(e["peak"])
        row = {c: detrended[c].get(wm["post1"]) for c in SUGAR_CODES}
        def g(x): return "—" if x is None else f"{x:+.1f}"
        print(f"{e['id']:<8}{g(row['SIN']):>9}{g(row['STH']):>9}{g(row['SBR']):>9}", flush=True)
    print(f"\n已写入白糖产量到 production(双口径) + attribution", flush=True)


if __name__ == "__main__":
    main()
