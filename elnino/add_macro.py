#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
厄尔尼诺研究 — 宏观周期叠加分析（含宏观轨迹 / 转向检测）
读 macro_series.json(PMI+原油) + elnino_data.json，计算每次事件的：
  1. 四阶段宏观状态（启动期 / 峰值 / 峰值后0-6 / 峰值后6-12）
  2. 宏观轨迹（全程顺风 / 顺风转逆风 / 逆风转顺风 / 全程逆风 / 分化）
     —— 轨迹 = 启动期状态 → 峰值后6-12月状态（这才是真正的"峰之后"环境）
  3. 顺风/逆风静态标签（保留，作一阶近似）
  4. 按轨迹分组聚合农产品表现
写入 elnino_data.json 的 macro 键。
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


def avg(series, a, b):
    keys = sorted([k for k in series if a <= k <= b])
    if not keys:
        return None
    return sum(series[k] for k in keys) / len(keys)


def phase_state(pmi_val, oil_chg):
    """阶段宏观状态：油极端波动(±20%)直接定方向，否则 PMI 主导(>50扩张)。
    返回 '顺' / '逆' + 备注。"""
    if oil_chg is not None and oil_chg <= -20:
        return "逆", "油价崩盘"
    if oil_chg is not None and oil_chg >= 20:
        return "顺", "油价暴涨"
    if pmi_val is None:
        return None, None
    if pmi_val >= 50:
        return "顺", "PMI扩张" if (oil_chg is None or oil_chg >= 0) else "PMI扩张+油跌"
    return "逆", "PMI收缩" if (oil_chg is None or oil_chg < 0) else "PMI收缩+油涨"


def classify(pmi_peak, oil_pre):
    """静态标签（保留，一阶近似）：顺风=油涨+PMI扩张，逆风=油跌+PMI收缩。"""
    if oil_pre is None or pmi_peak is None:
        return "未知"
    oil_up = oil_pre > 0
    pmi_exp = pmi_peak >= 50
    if oil_up and pmi_exp:
        return "顺风"
    if (not oil_up) and (not pmi_exp):
        return "逆风"
    return "混合"


def trajectory(a, b):
    """两阶段状态合成轨迹标签。a=启动期状态, b=峰值后6-12月状态。"""
    if a == "顺" and b == "顺":
        return "全程顺风"
    if a == "逆" and b == "逆":
        return "全程逆风"
    if a == "顺" and b == "逆":
        return "顺风转逆风"
    if a == "逆" and b == "顺":
        return "逆风转顺风"
    return "分化"


def main():
    m = json.load(open(MACRO_PATH))
    pmi = m["pmi"]["data"]
    oil = m["oil"]["data"]
    data = json.load(open(JSON_PATH))
    events = data["events"]
    price = data["price"]

    macro_events = []
    groups = {"顺风": [], "逆风": [], "混合": []}
    traj_groups = {}

    for e in events:
        p = e["peak"]; s = e["start"]
        pre_end = shift(p, -1)
        post6 = shift(p, 6)
        post12 = shift(p, 12)

        # ---- 四阶段宏观量 ----
        pmi_start = avg(pmi, s, pre_end)           # 启动期PMI均值
        pmi_peak = pmi.get(p)                       # 峰值PMI
        pmi_post06 = avg(pmi, p, post6)             # 峰值后0-6月PMI均值
        pmi_post612 = avg(pmi, shift(p, 7), post12) # 峰值后7-12月PMI均值
        oil_start = pct(oil, s, pre_end)            # 启动期油价
        oil_peak = pct(oil, pre_end, p)             # 峰值冲刺期油价
        oil_post06 = pct(oil, p, post6)             # 峰值后0-6月油价
        oil_post612 = pct(oil, post6, post12)       # 峰值后6-12月油价

        # ---- 静态标签（保留）----
        pmi_s, pmi_p = pmi.get(s), pmi.get(p)
        pmi_trend = round(pmi_p - pmi_s, 1) if (pmi_s is not None and pmi_p is not None) else None
        label = classify(pmi_peak, oil_start)

        # ---- 轨迹：启动期 → 峰值后6-12月 ----
        st, st_note = phase_state(pmi_start, oil_start)
        pt, pt_note = phase_state(pmi_post612, oil_post612)
        traj = trajectory(st, pt) if (st and pt) else "未知"

        # PMI / 原油 独立转向（启动期 → 峰值后6-12月）
        pmi_cross = None
        if pmi_start is not None and pmi_post612 is not None:
            if pmi_start < 50 <= pmi_post612:
                pmi_cross = "复苏转向"
            elif pmi_start >= 50 > pmi_post612:
                pmi_cross = "衰退转向"
            elif pmi_start >= 50 and pmi_post612 >= 50:
                pmi_cross = "持续扩张"
            else:
                pmi_cross = "持续收缩"
        oil_cross = None
        if oil_start is not None and oil_post612 is not None:
            if oil_start < 0 <= oil_post612:
                oil_cross = "由跌转涨"
            elif oil_start >= 0 > oil_post612:
                oil_cross = "由涨转跌"
            elif oil_start >= 0 and oil_post612 >= 0:
                oil_cross = "持续上涨"
            else:
                oil_cross = "持续下跌"

        def r(x): return round(x, 1) if x is not None else None

        macro_events.append({
            "event": e["id"], "grade": e["grade"],
            "pmi_peak": pmi_peak,
            "pmi_state": ("扩张" if pmi_peak and pmi_peak >= 50 else "收缩") if pmi_peak else None,
            "pmi_trend": pmi_trend,
            "oil_pre": r(oil_start),
            "oil_post0_6": r(oil_post06),
            "macro_label": label,
            # 轨迹字段
            "phase": {
                "start": {"pmi": r(pmi_start), "oil": r(oil_start), "state": st, "note": st_note},
                "peak": {"pmi": r(pmi_peak), "oil": r(oil_peak)},
                "post0_6": {"pmi": r(pmi_post06), "oil": r(oil_post06)},
                "post6_12": {"pmi": r(pmi_post612), "oil": r(oil_post612), "state": pt, "note": pt_note},
            },
            "trajectory": traj,
            "pmi_cross": pmi_cross,
            "oil_cross": oil_cross,
        })
        groups[label].append(e["id"])
        traj_groups.setdefault(traj, []).append(e["id"])

    # ---- 聚合 ----
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
    agg_by_traj = {t: agg_by_group(ev_ids) for t, ev_ids in traj_groups.items() if ev_ids}

    # ---- 写入 ----
    data["macro"] = {
        "note": "宏观周期叠加：美国ISM制造业PMI(经济景气,>50扩张) + IMF布伦特原油(大宗商品周期锚)。"
                "两套口径：①静态标签(顺风/逆风/混合,只看启动期) ②宏观轨迹(启动期→峰值后6-12月,检测转向)。"
                "轨迹规则：阶段状态由PMI主导、油价极端波动(±20%)直接定方向。峰值后环境取peak+6→peak+12(滞后窗口)。",
        "events": macro_events,
        "groups": groups,
        "trajectory_groups": traj_groups,
        "agg_by_macro": agg_by_macro,
        "agg_by_trajectory": agg_by_traj,
        "insight": [
            "启动期(pre)是宏观周期的照妖镜：顺风组普涨(棕榈+26.9%/白糖+21.7%/橡胶+15.2%)、逆风组普跌(棕榈-9.0%/白糖-15.2%/橡胶-10.8%)，差值26-37pp——启动期表现主要由宏观背景驱动，而非厄尔尼诺本身。",
            "滞后窗口(post6_12)是供给冲击与宏观的分化点：白糖高度依赖宏观(顺风+42.9% vs 逆风-20.4%)，棕榈油则供给冲击主导(1982/83逆风仍+105.9%，纯供给冲击)。",
            "宏观轨迹(启动期→峰值后)揭示静态标签看不见的转向：1997/98是唯一'顺风转逆风'——启动期PMI扩张(55.6)+油价涨(+13.7%)，但亚洲金融危机爆发后PMI衰退转向(49.1跌破荣枯线)+原油由涨转跌(-24.3%)，需求崩塌直接解释了它post12_24棕榈-45.7%/白糖-22.2%的全面崩盘——这正是静态'顺风'标签完全掩盖的。",
            "2018/19同样是'顺风转逆风'(2019贸易战：PMI 59.5→49.1衰退转向)，但幅度温和(弱厄尔尼诺)，农产品仅小幅回吐。",
            "反向的'逆风转顺风'是V型复苏/商品反弹信号：1982/83(PMI 38.7→64.3复苏转向)和2014/16(原油-49.1%→+11.5%由跌转涨)，两者post0_6都普涨(棕榈+14.2%/+18.3%)——宏观在峰值后转好，供给冲击得以兑现为涨幅。",
            "2014/16是极端宏观逆风：原油pre暴跌-49.1%(2014-2015原油崩盘)+PMI收缩48.2，量化了此前定性判断的'商品熊市'，解释了该事件农产品涨幅被系统性压制。",
            "1997/98的亚洲金融危机有原油佐证：峰值后6月原油-24.2%(需求崩塌)，印证'叠金融危机'的定性判断。",
        ],
    }
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    # ---- 打印摘要 ----
    print(f"{'事件':<8} {'静态':<5} {'启动':<5} {'峰后':<5} {'轨迹':<10} {'PMI转向':<10} {'原油转向':<8}")
    print("-" * 70)
    for me in macro_events:
        ph = me["phase"]
        st = ph["start"]["state"] or "—"
        pt = ph["post6_12"]["state"] or "—"
        print(f"{me['event']:<8} {me['macro_label']:<5} {st:<5} {pt:<5} {me['trajectory']:<10} "
              f"{(me['pmi_cross'] or '—'):<10} {(me['oil_cross'] or '—'):<8}")
    print("\n轨迹分组:", {t: evs for t, evs in traj_groups.items() if evs})
    print(f"已写入 macro 键到 {JSON_PATH}")


if __name__ == "__main__":
    main()
