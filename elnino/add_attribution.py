#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
厄尔尼诺研究 — 供给冲击 vs 宏观/供需 归因拆解
把价格走势拆成「供给冲击(产量去趋势偏离)」和「宏观/供需环境」两部分，
逐品种×事件做三维对照（供给信号 × 宏观信号 × 价格方向），判定驱动来源，
并生成每个品种在厄尔尼诺事件中需着重关注的点。
写入 elnino_data.json 的 attribution 键。
用法: python3 add_attribution.py
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE, "data", "elnino_data.json")

# 价格品种 → 对应产量产区（去趋势口径）
PRICE_TO_PROD = {
    "P": ["MY", "ID"],   # 棕榈油 ← 马来+印尼
    "RU": ["TH"],        # 橡胶 ← 泰国
    "SB": ["US", "BR"],  # 大豆 ← 美+巴西
    "SR": [],            # 白糖 ← 无产量数据（缺口）
    "CT": ["CTUS", "CTCN", "CTBR"],  # 棉花 ← 美/中/巴西
}

PROD_NAMES = {
    "MY": "马来棕榈油", "ID": "印尼棕榈油", "TH": "泰国橡胶",
    "US": "美豆", "BR": "巴西豆", "CTUS": "美棉", "CTCN": "中国棉", "CTBR": "巴西棉",
}

THRESH = 5.0  # 供给冲击判定阈值（去趋势偏离 ±5%）


def sign_dir(v, thresh=0.0):
    """返回 +1利多 / -1利空 / 0中性（供给：减产=利多）"""
    if v is None:
        return 0
    if v <= -thresh:
        return 1   # 减产 = 供给利多
    if v >= thresh:
        return -1  # 增产 = 供给利空
    return 0


def macro_dir(traj):
    """宏观方向：顺=+1 逆=-1 其他=0"""
    if traj in ("全程顺风", "逆风转顺风"):
        return 1
    if traj in ("全程逆风", "顺风转逆风"):
        return -1
    return 0


def price_dir(v):
    if v is None:
        return 0
    if v > 0:
        return 1
    if v < 0:
        return -1
    return 0


def attribute(s, m, p):
    """三信号归因。s=供给方向(+1利多/-1利空/0中性) m=宏观方向 p=价格方向。
    语义：供给宏观同向→共振/双重压制；反向→看价格跟谁；单信号→主导/背离。"""
    if s == 0 and m == 0:
        return "信号中性", "neither"
    # 供给宏观同向
    if s == m and s != 0:
        if p == s:
            return "供给+宏观共振", "resonance"
        if p == -s:
            return "双重压制（价格反走）", "both_against"
        return "驱动待兑现", "pending"
    # 供给宏观反向
    if s != 0 and m != 0 and s != m:
        if p == s:
            return "供给压过宏观", "supply_win"
        if p == m:
            return "宏观压过供给", "macro_win"
        return "多空交织", "mixed"
    # 只有单一信号
    if s != 0:
        if p == s:
            return "供给主导", "supply"
        if p == -s:
            return "供给背离（价格反走）", "supply_div"
        return "信号中性", "neither"
    if m != 0:
        if p == m:
            return "宏观主导", "macro"
        if p == -m:
            return "宏观背离（价格反走）", "macro_div"
        return "信号中性", "neither"
    return "信号中性", "neither"


def main():
    d = json.load(open(JSON_PATH))
    price_results = d["price"]["results"]
    prod_det = d["production"]["detrended"]["results"]
    macro_events = {e["event"]: e for e in d["macro"]["events"]}
    price_codes = d["price"]["commodities"]

    # 产量去趋势 → {(commodity, event): post1, post2}
    prod_map = {}
    for r in prod_det:
        prod_map[(r["commodity"], r["event"])] = r

    attribution = {"commodities": {}}

    for c, cname in price_codes.items():
        rows = [r for r in price_results if r["commodity"] == c]
        srcs = PRICE_TO_PROD.get(c, [])
        events_out = []

        for r in rows:
            eid = r["event"]
            # 供给冲击 = 各产区 post1 去趋势偏离的均值（None 剔除）
            vals = [prod_map.get((s, eid), {}).get("post1") for s in srcs]
            vals = [v for v in vals if v is not None]
            prod_shock = round(sum(vals) / len(vals), 1) if vals else None
            # 同时记录各产区明细
            src_detail = {PROD_NAMES.get(s, s): prod_map.get((s, eid), {}).get("post1") for s in srcs}

            s_dir = sign_dir(prod_shock, THRESH) if prod_shock is not None else 0
            m_traj = macro_events.get(eid, {}).get("trajectory")
            m_dir = macro_dir(m_traj)
            # 价格主窗口 = post6_12（主升浪窗口）
            p_dir = price_dir(r.get("post6_12"))

            att, att_key = attribute(s_dir, m_dir, p_dir)

            events_out.append({
                "event": eid, "grade": r["grade"],
                "price_pre": r.get("pre"),
                "price_post612": r.get("post6_12"),
                "prod_shock": prod_shock,          # 供给冲击（post1去趋势偏离均值）
                "prod_sources": src_detail,         # 各产区明细
                "supply_dir": s_dir,
                "macro_traj": m_traj,
                "macro_dir": m_dir,
                "price_dir": p_dir,
                "attribution": att,
                "attribution_key": att_key,
            })

        # 该品种主导模式统计
        key_counts = {}
        for e in events_out:
            k = e["attribution_key"]
            key_counts[k] = key_counts.get(k, 0) + 1

        attribution["commodities"][c] = {
            "name": cname,
            "prod_sources": [PROD_NAMES.get(s, s) for s in srcs],
            "has_prod_data": bool(srcs),
            "events": events_out,
            "dominant": max(key_counts.items(), key=lambda x: x[1])[0] if key_counts else "neither",
        }

    # 品种关注要点（结合归因结果 + 既有结论）
    attribution["focus"] = [
        {
            "commodity": "P", "name": "棕榈油",
            "supply_driven": True,
            "points": [
                "【供给端·最核心】盯马来(MPOB月度库存/产量)+印尼(GAPKI)两大产区——厄尔尼诺减产有8-18月生理滞后，峰值后6-12月才是兑现窗口，勿在峰值当刻追。",
                "【供给强度】去趋势偏离才是真信号：马来+印尼长期扩产，前5年基线会掩盖减产，须用对数去趋势。",
                "【宏观】供给冲击主导，可穿越宏观逆风(1982/83逆风仍+105.9%)；但警惕顺风转逆风(1997/98金融危机)时需求崩塌吞噬涨幅。",
                "【关键事件】1982/83纯供给冲击是范式样本：马来-17.8%减产→棕榈+105.9%。",
            ],
        },
        {
            "commodity": "SR", "name": "白糖",
            "supply_driven": False,
            "points": [
                "【宏观·最核心】白糖是宏观敏感型品种：顺风组post6_12 +42.9% vs 逆风组-20.4%，做多白糖必须先看宏观顺风/逆风。",
                "【供给·数据缺口】⚠️ 当前无白糖产量数据(印度/泰国/巴西UNICA指标未接入)，供给归因暂缺——这是本板块最大盲区。",
                "【季节性】印度季风(6-9月)与巴西中南部榨季(4-11月)是供给关键变量，弱季风=减产利好。",
                "【关键事件】2009/10顺风+印度季风偏弱→+77.1%；1982/83逆风→-34.8%。",
            ],
        },
        {
            "commodity": "RU", "name": "橡胶",
            "supply_driven": True,
            "points": [
                "【供给端】盯泰国(ANRPC全球产胶)割胶旺季(5-1月)，厄尔尼诺干旱影响次年产量；橡胶对厄尔尼诺反应最早(pre即反应)。",
                "【宏观】供给+宏观双敏感：启动期宏观驱动，滞后窗口供给冲击兑现。",
                "【关键事件】2014/16逆风转顺风→post6_12 +49.7%(2016商品反弹)；1997/98顺风转逆风→-7.7%。",
            ],
        },
        {
            "commodity": "SB", "name": "大豆",
            "supply_driven": True,
            "points": [
                "【供给端】分半球看：美豆(北半球，峰值12月休耕→影响下一季)+巴西豆(南半球，峰值正值生长季→当季)。厄尔尼诺对巴西豆冲击更大(去趋势后1982/83巴西豆-34.3%)。",
                "【宏观】大豆相对最抗跌(区域性对冲：东南亚旱 vs 南美/美国增产)，全程对厄尔尼诺最不敏感。",
                "【关键事件】2014/16美豆增产+17.2%(中西部降水正常)→价格反而-15.2%(商品熊市压制)。",
            ],
        },
        {
            "commodity": "CT", "name": "棉花",
            "supply_driven": True,
            "points": [
                "【供给端】美棉对厄尔尼诺最敏感(1982/83 -44.8%、1997/98 -31.5%)，但方向不定取决于具体降水模式(2014/16反增产+29.3%)——德州半干旱区是关键。",
                "【数据限制】郑棉价格仅覆盖4事件(2009/10起)，归因样本脆弱；美/中/巴西棉产量可覆盖9事件。",
                "【产区分化】中国棉(新疆内陆灌溉)最抗跌，巴西棉波动大——同一次厄尔尼诺产区反应方向相反。",
            ],
        },
    ]

    attribution["note"] = (
        "价格走势归因拆解：把每次事件×品种的价格主升浪(post6_12)对照「供给冲击(产量去趋势偏离post1)」和"
        "「宏观轨迹(顺风/逆风)」，判定驱动来源。供给信号=减产(去趋势<-5%)=利多/增产(>+5%)=利空；"
        "宏观信号=全程顺风·逆风转顺风=利多/全程逆风·顺风转逆风=利空。归因类型：供给+宏观共振/供给主导/"
        "宏观主导/供给压过宏观/宏观压过供给/双重压制/多空交织。⚠️白糖无产量数据，供给归因暂缺。"
    )

    d["attribution"] = attribution
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)

    # 打印摘要
    print(f"{'品种':<8}{'事件':<8}{'供给冲击':>9}{'宏观轨迹':<10}{'价格后6-12':>9}{'归因':<16}")
    print("-" * 70)
    for c, cinfo in attribution["commodities"].items():
        for e in cinfo["events"]:
            def g(x):
                return "—" if x is None else f"{x:+.1f}"
            print(f"{c:<8}{e['event']:<8}{g(e['prod_shock']):>9}{e['macro_traj'] or '—':<10}"
                  f"{g(e['price_post612']):>9}{e['attribution']:<16}")
        print("-" * 70)
    print("\n品种主导模式:", {c: v["dominant"] for c, v in attribution["commodities"].items()})
    print(f"已写入 attribution 键到 {JSON_PATH}")


if __name__ == "__main__":
    main()
