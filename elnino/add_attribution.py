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
    "SR": ["SIN", "STH", "SBR"],  # 白糖 ← 印度+泰国+巴西（全球三大产糖国）
    "CT": ["CTUS", "CTCN", "CTBR"],  # 棉花 ← 美/中/巴西
    "M": ["US", "BR"],   # 豆粕 ← 大豆(美+巴西，压榨副产品，供给看上游大豆)
    "Y": ["US", "BR"],   # 豆油 ← 大豆(美+巴西)
    "C": ["CUS", "CCN", "CBR"],  # 玉米 ← 美+中+巴西玉米
}

PROD_NAMES = {
    "MY": "马来棕榈油", "ID": "印尼棕榈油", "TH": "泰国橡胶",
    "US": "美豆", "BR": "巴西豆", "CTUS": "美棉", "CTCN": "中国棉", "CTBR": "巴西棉",
    "SIN": "印度糖", "STH": "泰国糖", "SBR": "巴西糖",
    "CUS": "美玉米", "CCN": "中玉米", "CBR": "巴玉米",
}

THRESH = 5.0  # 供给冲击判定阈值（去趋势偏离 ±5%）

# 品种主升浪窗口（生理滞后决定）：橡胶全年割胶对厄尔尼诺反应最早→post0_6；其余→post6_12
PRIMARY_WINDOW = {
    "RU": "post0_6",   # 橡胶主升浪在早期
    "P": "post6_12",   # 棕榈油8-18月生理滞后，主升浪在滞后窗口
    "SR": "post6_12",
    "SB": "post6_12",
    "CT": "post6_12",
    "M": "post6_12",   # 豆粕跟随上游大豆，默认滞后窗口
    "Y": "post6_12",
    "C": "post6_12",
}


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

            # 双窗口价格方向 + 归因
            p06 = r.get("post0_6")
            p612 = r.get("post6_12")
            p06_dir = price_dir(p06)
            p612_dir = price_dir(p612)
            att06, key06 = attribute(s_dir, m_dir, p06_dir)
            att612, key612 = attribute(s_dir, m_dir, p612_dir)

            # 主窗口归因（品种特定）
            primary_w = PRIMARY_WINDOW.get(c, "post6_12")
            if primary_w == "post0_6":
                att, att_key, p_dir, price_primary = att06, key06, p06_dir, p06
            else:
                att, att_key, p_dir, price_primary = att612, key612, p612_dir, p612

            events_out.append({
                "event": eid, "grade": r["grade"],
                "price_pre": r.get("pre"),
                "price_post06": p06,            # 峰值后0-6月涨幅
                "price_post612": p612,          # 峰值后6-12月涨幅
                "prod_shock": prod_shock,       # 供给冲击（post1去趋势偏离均值）
                "prod_sources": src_detail,     # 各产区明细
                "supply_dir": s_dir,
                "macro_traj": m_traj,
                "macro_dir": m_dir,
                # 双窗口归因
                "attribution_early": att06, "attribution_early_key": key06,
                "attribution_late": att612, "attribution_late_key": key612,
                # 主窗口（品种特定）
                "primary_window": primary_w,
                "price_dir": p_dir,
                "price_primary": price_primary,
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
                "【核心发现·糖周期主导】补上印度/泰国/巴西产量数据后，白糖归因模式=「双重压制」：多次减产+宏观顺风，价格仍反跌(1982/83印度糖-18.3%减产仍-34.8%、2002/03印度-35.3%大减产仍-18.8%)——证明白糖由**全球糖周期(库存/产能周期)**主导，单年产量扰动不是主驱动。",
                "【供给端】印度(季风敏感，6-9月弱季风=减产利好)+泰国(厄尔尼诺干旱)+巴西中南部(全球第一大产糖国，乙醇分流关键变量)。印度去趋势偏离波动最大(±35%)，是白糖供给冲击的核心来源。",
                "【库存/糖周期】糖价3-5年库存周期：全球库存消费比是比单年产量更重要的定价锚。1980s全球糖严重供过于求、2000s巴西糖产能大扩张，是两次'减产仍跌'的根因。",
                "【宏观】顺风能放大涨幅(2009/10顺风+77.1%)，但逆风时白糖跌幅远超其他品种——宏观是放大器，非主驱动。",
                "【关键事件】2009/10顺风+印度季风偏弱→+77.1%是唯一'供给+宏观'共振样本；其余事件糖周期主导。",
            ],
        },
        {
            "commodity": "RU", "name": "橡胶",
            "supply_driven": True,
            "points": [
                "【供给端】盯泰国(ANRPC全球产胶)割胶旺季(5-1月)，厄尔尼诺干旱影响次年产量；橡胶对厄尔尼诺反应最早(pre即反应)。",
                "【主升浪窗口·早期】橡胶是唯一主升浪在峰值后0-6月的品种(+21.2% vs 6-12月+11.8%)——全年割胶、无生理滞后，供给冲击当期兑现，勿套用棕榈油的滞后逻辑。",
                "【宏观】供给+宏观双敏感：启动期宏观驱动，早期窗口供给冲击兑现。2018/19用早期窗口归因是'供给压过宏观'(价格+34.0%涨)，用滞后窗口则误判'宏观压过供给'(价格-14.0%跌)——窗口选错会得出相反结论。",
                "【关键事件】2014/16逆风转顺风→post0_6 +17.3%(2016商品反弹)；1997/98顺风转逆风→post0_6 -7.1%。",
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
        {
            "commodity": "M", "name": "豆粕",
            "supply_driven": False,
            "points": [
                "【供给端】豆粕是大豆压榨副产品，无独立产量，供给看上游大豆(美豆+巴西豆，复用SB的产量偏离)。",
                "【核心结论·8品种最弱】豆粕对厄尔尼诺最不敏感：全程温和(post0_6 +2.8%、post6_12 +2.1%，0-12月累计仅+5%)——饲料需求由养殖周期/压榨利润主导，厄尔尼诺是次要扰动。",
                "【宏观】归因=宏观主导，跟随大豆的宏观敏感型；不构成厄尔尼诺交易标的。",
            ],
        },
        {
            "commodity": "Y", "name": "豆油",
            "supply_driven": True,
            "points": [
                "【油脂同族·棕榈油弱化版】豆油与棕榈油同属油脂，主升浪同样在峰值后6-12月(+17.8%)，但幅度弱于棕榈油(+36.6%)——因供给看大豆(区域性对冲)，不如棕榈油东南亚集中减产强烈。",
                "【替代关系】豆油与棕榈油互为替代(食用油)，棕榈油暴涨时豆油跟涨(1982/83豆油post6_12 +40.5%、2009/10 +53.5%)，可作为棕榈油行情的跟随/对冲品种。",
                "【供给端】无独立产量，复用大豆(美+巴西)产量偏离；归因主导=宏观，但供给+宏观共振在部分事件出现(1982/83)。",
            ],
        },
        {
            "commodity": "C", "name": "玉米",
            "supply_driven": False,
            "points": [
                "【核心结论·兑现最晚】玉米主升浪在峰值后12-24月(+9.8%)，是所有8品种里兑现最晚的(比棕榈油还晚)——美玉米带(中西部)与厄尔尼诺核心区(东南亚)不同，供给冲击传导最慢最弱。",
                "【供给端】美/中/巴西玉米产量去趋势：1986/88美玉米-34.1%、1991/92-27.4%、2014/16巴玉米-29.7%(大减产)，但价格反应弱——因全球玉米供需格局分散。",
                "【异常值】2009/10玉米post6_12 +75.2%是生物燃料政策异常值，非厄尔尼诺驱动，归因时需剔除。",
                "【宏观】归因=宏观主导，对厄尔尼诺不敏感，不构成厄尔尼诺交易标的。",
            ],
        },
    ]

    attribution["note"] = (
        "价格走势归因拆解：把每次事件×品种的价格对照「供给冲击(产量去趋势偏离post1)」和"
        "「宏观轨迹(顺风/逆风)」，判定驱动来源。供给信号=减产(去趋势<-5%)=利多/增产(>+5%)=利空；"
        "宏观信号=全程顺风·逆风转顺风=利多/全程逆风·顺风转逆风=利空。归因类型：供给+宏观共振/供给主导/"
        "宏观主导/供给压过宏观/宏观压过供给/双重压制/多空交织。⚠️双窗口归因：同时展示峰值后0-6月(早期)和6-12月(滞后)两窗口，"
        "主归因用品种特定主升浪窗口——橡胶全年割胶反应最早→post0_6，棕榈油8-18月生理滞后→post6_12，其余post6_12。"
        "8品种覆盖(含豆粕/豆油/玉米)；豆粕豆油无独立产量复用大豆(US/BR)，玉米用美/中/巴西玉米产量。"
    )

    d["attribution"] = attribution
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)

    # 打印摘要
    print(f"{'品种':<8}{'事件':<8}{'供给冲击':>9}{'宏观轨迹':<10}{'价格0-6':>8}{'归因(早)':<14}{'价格6-12':>9}{'归因(主)':<14}")
    print("-" * 90)
    for c, cinfo in attribution["commodities"].items():
        for e in cinfo["events"]:
            def g(x):
                return "—" if x is None else f"{x:+.1f}"
            mark = " *" if e["primary_window"] == "post0_6" else ""
            print(f"{c:<8}{e['event']:<8}{g(e['prod_shock']):>9}{e['macro_traj'] or '—':<10}"
                  f"{g(e['price_post06']):>8}{e['attribution_early']:<14}"
                  f"{g(e['price_post612']):>9}{e['attribution']:<14}{mark}")
        print("-" * 90)
    print("\n品种主导模式:", {c: v["dominant"] for c, v in attribution["commodities"].items()})
    print(f"已写入 attribution 键到 {JSON_PATH}")


if __name__ == "__main__":
    main()
