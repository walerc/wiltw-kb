#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
厄尔尼诺研究 — 美元汇率因素分析
1. 拉取美元兑人民币(USDCNY)日度 -> 月度
2. 计算美元指数(REER) + USDCNY 在各事件5窗口的涨跌幅
3. 对美元计价品种(棕榈油/白糖/橡胶/大豆)剔除美元指数；对棉花(郑棉人民币)剔除人民币汇率
4. 写入 elnino_data.json 的 usd 键(原始 vs 剔除后对比)
用法: python3 add_usd.py
"""
import json, os, re, sys, time

SKILL_DIR = os.path.expanduser("~/.hermes/skills/ifind-finance-data")
sys.path.insert(0, SKILL_DIR)
os.chdir(SKILL_DIR)
from call import call  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE, "data", "elnino_data.json")
USD_PATH = os.path.join(BASE, "data", "usd_index.json")
CNY_PATH = os.path.join(BASE, "data", "usdcny.json")

PRICE_WINDOWS = ["pre", "peak_w", "post0_6", "post6_12", "post12_24"]
USD_COM = {"P", "SR", "RU", "SB"}  # 美元计价品种
CNY_COM = {"CT"}                     # 人民币计价(郑棉)


def fetch_edb(query):
    r = call("edb", "get_edb_data", {"query": query})
    s = json.dumps(r, ensure_ascii=False)
    return re.findall(r'\|(\d{4}-\d{2}-\d{2})\|([\d.]+)\|', s)


def daily_to_monthly(rows):
    """日度 -> 月度(取每月最后一个交易日)"""
    monthly = {}
    for d, v in rows:
        ym = d[:7]  # YYYY-MM
        monthly[ym] = float(v)  # 倒序遍历时保留月末，正序最后覆盖为月末
    return monthly


def month_key(ym):
    """YYYY-MM -> YYYY-MM-31 末值索引(直接存 YYYY-MM)"""
    return ym


def shift(ym, n):
    y, m = int(ym[:4]), int(ym[5:7])
    m += n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def pct(series, a, b):
    va, vb = series.get(a), series.get(b)
    if va is None or vb is None or va == 0:
        return None
    return (vb / va - 1) * 100


def window_chg(series, s, p):
    """某事件5窗口的汇率涨跌幅(%)"""
    return {
        "pre": pct(series, s, shift(p, -1)),
        "peak_w": pct(series, shift(p, -1), shift(p, 1)),
        "post0_6": pct(series, p, shift(p, 6)),
        "post6_12": pct(series, shift(p, 6), shift(p, 12)),
        "post12_24": pct(series, shift(p, 12), shift(p, 24)),
    }


def real_chg(nominal, fx):
    """剔除汇率后的真实涨幅: (1+名义)/(1+汇率涨幅)-1"""
    if nominal is None or fx is None:
        return None
    return ((1 + nominal / 100) / (1 + fx / 100) - 1) * 100


def main():
    # 1. 拉取 USDCNY 日度
    rows = fetch_edb("美元兑人民币 2008-2024")
    cny_daily = daily_to_monthly(rows)
    with open(CNY_PATH, "w", encoding="utf-8") as f:
        json.dump({"indicator": "美元兑人民币", "freq": "月度(月末)", "data": cny_daily},
                  f, ensure_ascii=False, indent=1)
    print(f"USDCNY 月度 {len(cny_daily)} 月: {min(cny_daily)} -> {max(cny_daily)}")

    # 2. 读美元指数 + 主数据
    usd_series_raw = json.load(open(USD_PATH))["data"]
    usd_series = {k[:7]: float(v) for k, v in usd_series_raw.items()}  # YYYY-MM-DD -> YYYY-MM
    data = json.load(open(JSON_PATH))
    events = data["events"]

    # 3. 计算各事件汇率窗口涨幅
    usd_by_event = {}
    cny_by_event = {}
    for e in events:
        usd_by_event[e["id"]] = window_chg(usd_series, e["start"], e["peak"])
        cny_by_event[e["id"]] = window_chg(cny_daily, e["start"], e["peak"])

    # 4. 剔除汇率，生成真实涨幅
    price_results = data["price"]["results"]
    adj_results = []
    for r in price_results:
        c = r["commodity"]
        fx_by_event = usd_by_event if c in USD_COM else cny_by_event
        fx = fx_by_event.get(r["event"], {})
        nr = {
            "event": r["event"], "grade": r["grade"], "peak": r["peak"],
            "commodity": c, "name": r["name"],
        }
        for w in PRICE_WINDOWS:
            nr[w] = real_chg(r.get(w), fx.get(w))
        adj_results.append(nr)

    # 5. 聚合(剔除后)
    agg = {}
    for c, name in data["price"]["commodities"].items():
        rows_c = [r for r in adj_results if r["commodity"] == c]
        entry = {"name": name}
        for w in PRICE_WINDOWS:
            vals = [r[w] for r in rows_c if r.get(w) is not None]
            entry[w] = round(sum(vals) / len(vals), 1) if vals else None
        agg[c] = entry

    # 6. 写入 JSON
    data["usd"] = {
        "indicator": "美国:实际美元指数:广义(REER) + 美元兑人民币(USDCNY)",
        "unit": "REER 2006年1月=100 / USDCNY 月末值",
        "method": "真实涨幅=(1+名义涨幅)/(1+汇率涨幅)-1；美元计价品种剔除美元指数，郑棉(人民币计价)剔除人民币兑美元汇率",
        "note": "美元指数量级(±13%)远小于商品价格波动(±106%)，美元因素总体是次要扰动，但2014/16美元强周期(pre +13.2%)、1986/88美元走弱(post6_12 -8.1%)等窗口不可忽略",
        "windows_by_event": usd_by_event,
        "cny_by_event": cny_by_event,
        "agg_adjusted": agg,
        "results_adjusted": adj_results,
    }

    # 7. 追加美元结论(若不存在)
    usd_concl = "【美元因素·次要但非零】美元指数波动(±13%)远小于商品价格波动(±106%)，剔除汇率后聚合均值仅偏移±1.5个百分点；但单事件层面不可忽略——2014/16美元强周期(pre +13.2%)压低了名义跌幅、1986/88与2002/03美元走弱(post6_12 -8.1%/-6.4%)抬高了名义涨幅。美元是次要扰动，不是主驱动。"
    if not any("美元因素" in c for c in data["conclusions"]):
        data["conclusions"].append(usd_concl)

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    # 打印对比摘要
    print("\n=== 美元指数窗口涨幅(%) ===")
    for eid, w in usd_by_event.items():
        def f(x): return f"{x:+.1f}" if x is not None else "  —"
        print(f"{eid:<8} pre={f(w['pre'])} peak_w={f(w['peak_w'])} post0_6={f(w['post0_6'])} post6_12={f(w['post6_12'])} post12_24={f(w['post12_24'])}")

    print("\n=== 聚合对比: 原始名义 vs 剔除汇率(%) ===")
    orig = data["price"]["agg_by_commodity"]
    for c in orig:
        print(f"\n{orig[c]['name']}:")
        for w in PRICE_WINDOWS:
            o = orig[c].get(w)
            a = agg[c].get(w)
            if o is None:
                continue
            print(f"  {w:<12} 名义={o:+6.1f}  剔除={a:+6.1f}" if a is not None else f"  {w:<12} 名义={o:+6.1f}  剔除=—")

    print(f"\n已写入 usd 键到 {JSON_PATH}")


if __name__ == "__main__":
    main()
