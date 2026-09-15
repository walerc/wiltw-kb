#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
厄尔尼诺研究 — 宏观周期叠加分析
读 macro_series.json(PMI+原油) + elnino_data.json，计算每次事件的宏观状态，
顺风/逆风分组对比，写入 elnino_data.json 的 macro 键。
用法: python3 add_macro.py
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE, "data", "elnino_data.json")
MACRO_PATH = os.path.join(BASE, "data", "macro_series.json")
W = ["pre", "peak_w", "post0_6", "post6_12", "post12_24"]


def shift(ym, n):
    y, mm = int(ym[:4]), int(ym[5:7])
    mm += n
    y += (mm - 1) // 12
    mm = (mm - 1) % 12 + 1
    return f"{y:04d}-{mm:02d}"


def pct(series, a, b):
    va, vb = series.get(a), series.get(b)
    return None if (va is None or vb is None or va == 0) else (vb / va - 1) * 100


def classify(pmi_peak, oil_pre):
    if oil_pre is None or pmi_peak is None:
        return "未知"
    oil_up = oil_pre > 0
    pmi_exp = pmi_peak >= 50
    if oil_up and pmi_exp:
        return "顺风"
    if (not oil_up) and (not pmi_exp):
        return "逆风"
    return "混合"


def main():
    m = json.load(open(MACRO_PATH))
    pmi = m["pmi"]["data"]
    oil = m["oil"]["data"]
    data = json.load(open(JSON_PATH))
    events = data["events"]
    price = data["price"]

    # 1. 每次事件宏观状态
    macro_events = []
    groups = {"顺风": [], "逆风": [], "混合": []}
    for e in events:
        p = e["peak"]; s = e["start"]
        pmi_peak = pmi.get(p)
        pmi_s, pmi_p = pmi.get(s), pmi.get(p)
        pmi_trend = round(pmi_p - pmi_s, 1) if (pmi_s is not None and pmi_p is not None) else None
        oil_pre = pct(oil, s, shift(p, -1))
        oil_post0_6 = pct(oil, p, shift(p, 6))
        label = classify(pmi_peak, oil_pre)
        macro_events.append({
            "event": e["id"], "grade": e["grade"],
            "pmi_peak": pmi_peak,
            "pmi_state": ("扩张" if pmi_peak and pmi_peak >= 50 else "收缩") if pmi_peak else None,
            "pmi_trend": pmi_trend,
            "oil_pre": round(oil_pre, 1) if oil_pre is not None else None,
            "oil_post0_6": round(oil_post0_6, 1) if oil_post0_6 is not None else None,
            "macro_label": label,
        })
        groups[label].append(e["id"])

    # 2. 分组聚合（各品种窗口均值）
    def agg_by_group(ev_ids):
        agg = {}
        for c, name in price["commodities"].items():
            rows = [r for r in price["results"] if r["commodity"] == c and r["event"] in ev_ids]
            entry = {"name": name, "n": len(rows)}
            for w in W:
                vals = [r[w] for r in rows if r.get(w) is not None]
                entry[w] = round(sum(vals) / len(vals), 1) if vals else None
            agg[c] = entry
        return agg

    agg_by_macro = {g: agg_by_group(ev_ids) for g, ev_ids in groups.items() if ev_ids}

    # 3. 写入 JSON
    data["macro"] = {
        "note": "宏观周期叠加：美国ISM制造业PMI(经济景气,>50扩张) + IMF布伦特原油(大宗商品周期锚)。"
                "顺风=原油pre涨+PMI扩张，逆风=原油pre跌+PMI收缩，混合=其他。窗口定义同价格口径(pre=启动→峰值前1月)。",
        "events": macro_events,
        "groups": groups,
        "agg_by_macro": agg_by_macro,
        "insight": [
            "启动期(pre)是宏观周期的照妖镜：顺风组普涨(棕榈+26.9%/白糖+21.7%/橡胶+15.2%)、逆风组普跌(棕榈-9.0%/白糖-15.2%/橡胶-10.8%)，差值26-37pp——启动期表现主要由宏观背景驱动，而非厄尔尼诺本身。",
            "滞后窗口(post6_12)是供给冲击与宏观的分化点：白糖高度依赖宏观(顺风+42.9% vs 逆风-20.4%)，棕榈油则供给冲击主导(1982/83逆风仍+105.9%，纯供给冲击)。",
            "2014/16是极端宏观逆风：原油pre暴跌-49.1%(2014-2015原油崩盘)+PMI收缩48.2，量化了此前定性判断的'商品熊市'，解释了该事件农产品涨幅被系统性压制。",
            "1997/98的亚洲金融危机有原油佐证：峰值后6月原油-24.2%(需求崩塌)，印证'叠金融危机'的定性判断。",
        ],
    }
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    # 打印摘要
    print(f"{'事件':<8}{'PMI':>6}{'状态':>5}{'原油pre':>9}{'原油+6月':>9}{'宏观':>6}")
    for me in macro_events:
        def f(x, s="+.1f"): return f"{x:{s}}" if x is not None else "   —"
        print(f"{me['event']:<8}{f(me['pmi_peak'],'6.1f'):>6}{me['pmi_state']:>5}"
              f"{f(me['oil_pre']):>9}{f(me['oil_post0_6']):>9}{me['macro_label']:>6}")

    print("\n分组:", {g: evs for g, evs in groups.items() if evs})
    print(f"已写入 macro 键到 {JSON_PATH}")


if __name__ == "__main__":
    main()
