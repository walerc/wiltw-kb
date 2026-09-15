#!/usr/bin/env python3
"""
fetch_tracking.py — 拉取当前厄尔尼诺 + 宏观 + 5品种最新数据，生成跟踪页 tracking.json

【周度版 2026-09】
- 品种价格(棕榈油/橡胶/白糖/豆一/棉花) + 布伦特原油：国内期货活跃合约日度数据 → 取最新交易日收盘（周度更新）
- SOI / ISM PMI：月度（数据源本身月度发布，无法周度）
- 涨幅口径：ytd=2026-01月末 · phase(启动期)=2026-04月末(SOI转负) · yoy=2025-08月末

数据源：iFinD EDB
输出：data/tracking.json（前端「🛰️ 实时跟踪」tab 读取）

运行：cd ~/WILTW_KB/elnino && /usr/bin/python3 fetch_tracking.py
更新频率：建议每周1次（cron 每周一早上，拉上周五收盘）
"""
import json, os, re, urllib.request, datetime

# ---- iFinD token / url ----
DEFAULT_TOKEN = "eyJhbGciOiJSU0EtT0FFUC0yNTYiLCJlbmMiOiJBMjU2R0NNIn0.XfFURXlgV6AMNQUchdjI7iVMxQF8nnHuKZnkRRmPh0Oc_siFrsK6TxFJzkEcGrxyzn9IZ4-d1Iz82N6gK0iWWe2eMU9EEj2Rrfkzd5plj0tPICC9aqBIAMKkn7CG266g1nkJ9ZpmITyEVOhTo9Pf12HAaLqbzBk5M27WWtPz-Ox5aFwXeoJnUmiDhCWDTqDbVtktHB0rsSrWqM9vPZim2VCMyS7TnIxNbAFYBzZH9rVUcGGg6UGbZtTJ4nJLKqXOS8SX9EP7A0Kz6eGeo64BdLZ6OV_gJutjIihgr5t9q6D7gOLClVtsthjBP_RX_vJ6BYrlrXpZpDRD70FwRod-Nw.5j2BOOrFWzbbxvyv.AivRYcb6hoONYxLKeCY0uAq5Rs4stywEemEBLbXIqjkG-P0UeEm7NWRyEIlp6Cyhe678ElTlBPpjvRGW9S8GoLsWFdU2IcCY-ZcA9UjXzmiw5fulnuEnX83bf5w0rDLTM0gCimaDulVg_Oz1e_53R3tht58zN3BUBOd4Bz-9ggbk4qt9AbpPMYvoX076v1CSFETgvVZqUStPUYlxVRQE32XVkxg5suRRbsWkPng8G0_ncZKkB0GSB6ag2AR7EFKIlXAe-ASvS8iDNw1IJ4NAr_0ina5h94ohybLneWwWunJGzETNCoPKdpAwt7dg7WW-VqDPbe2sahxcsPOgH49BHE_XcwG3nGJKbI3KXLYDyuV9C-LC8nCb_BUXVAY-8hwvG9e8e1Kp0LKqaSe6QvKq_QuuOK64xQ.F9pEIDvWlIZ5l1cvKiRZcQ"

def load_token():
    cfg = os.path.expanduser("~/.hermes/config.yaml")
    try:
        txt = open(cfg, encoding="utf-8").read()
        m = re.search(r"Authorization:\s*Bearer\s+(\S+)", txt)
        if m:
            return m.group(1)
    except Exception:
        pass
    return DEFAULT_TOKEN

TOKEN = load_token()
EDB_URL = "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-edb-mcp"

# ---- 日度指标（周度更新）----
DAILY = {
    "palm": "期货收盘价(活跃):棕榈油",
    "rubber": "期货收盘价(活跃):天然橡胶",
    "sugar": "期货收盘价(活跃):白糖",
    "soybean": "期货收盘价(活跃):黄大豆1号",
    "cotton": "期货收盘价(活跃):棉花",
    "oil": "期货收盘价(活跃):布伦特原油:ICE",
}
# ---- 月度指标（发布频率限制，月度更新）----
MONTHLY = {
    "soi": "南方涛动指数",
    "pmi": "美国:ISM:制造业PMI",
}


def query_edb(q, timeout=120):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "get_edb_data", "arguments": {"query": q}}}).encode()
    req = urllib.request.Request(EDB_URL, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode())
    content = resp.get("result", {}).get("content", [])
    if not content:
        return None
    text = content[0].get("text", "")
    inner = json.loads(text)

    def find_datas(o, d=0):
        if d > 6 or not isinstance(o, dict):
            return None
        if o.get("datas") is not None:
            return o["datas"]
        if isinstance(o.get("data"), dict):
            return find_datas(o["data"], d + 1)
        if isinstance(o.get("data"), str):
            try:
                sub = json.loads(o["data"])
                if isinstance(sub, dict):
                    return find_datas(sub, d + 1)
            except Exception:
                pass
        return None

    return find_datas(inner)


def month_str(y, m):
    return f"{y}年{m}月"


def month_range(n=20):
    """返回 (起始年月, 结束年月)，覆盖最近 n 个月"""
    now = datetime.date.today()
    total = now.year * 12 + (now.month - 1)
    s_total = total - (n - 1)
    sy, sm = s_total // 12, s_total % 12 + 1
    return month_str(sy, sm), month_str(now.year, now.month)


def fetch_series():
    now = datetime.date.today()
    # 日度：拉最近 ~15 个月（覆盖 yoy 锚点 2025-08）
    d_total = now.year * 12 + (now.month - 1) - 14
    d_start_y, d_start_m = d_total // 12, d_total % 12 + 1
    d_start, d_end = month_str(d_start_y, d_start_m), month_str(now.year, now.month)
    # 月度：拉最近 20 个月
    m_start, m_end = month_range(20)

    series = {}
    for k, name in DAILY.items():
        datas = query_edb(f"{name} {d_start}到{d_end}")
        if datas and isinstance(datas, list) and datas[0].get("data", {}).get("data"):
            series[k] = datas[0]["data"]["data"]
        else:
            series[k] = None
        print(f"  [日度] {k}: {len(series[k]) if series[k] else 'EMPTY'} 点")
    for k, name in MONTHLY.items():
        datas = query_edb(f"{name} {m_start}到{m_end}")
        if datas and isinstance(datas, list) and datas[0].get("data", {}).get("data"):
            series[k] = datas[0]["data"]["data"]
        else:
            series[k] = None
        print(f"  [月度] {k}: {len(series[k]) if series[k] else 'EMPTY'} 点")
    return series


# ============ 静态框架结论（基于 el-nino-event-study 六层框架，定性判断） ============

EVENT = {
    "name": "2026/27 超强厄尔尼诺",
    "status": "正在形成（启动期）",
    "phase": "启动期（pre）→ 峰值前",
    "nino34": "+1.8°C",
    "nino3": "+2.5°C",
    "nino12": "+3.4°C",
    "peak_forecast": "2026年10-12月，CPC 75%概率超1950年以来所有事件（RONI≥+2.5°C）",
    "analog": "1982/83（超强东部型·纯供给冲击）+ 2009/10（顺风复苏）",
}

COMMODITY_META = {
    "P":  {"name": "棕榈油", "emoji": "🌴", "unit": "元/吨", "hist_main": 36.6, "hist_window": "峰值后6-12月",
           "signal": "供给冲击滞后(8-18月生理滞后)，主升浪尚未启动", "view": "首选·布局"},
    "RU": {"name": "橡胶", "emoji": "🌳", "unit": "元/吨", "hist_main": 21.2, "hist_window": "峰值后0-6月",
           "signal": "最早反应已基本兑现，追高空间有限", "view": "次选·先行信号"},
    "SR": {"name": "白糖", "emoji": "🍬", "unit": "元/吨", "hist_main": 6.5, "hist_window": "各窗口温和",
           "signal": "国内糖与全球糖脱节(进口配额)，未现启动，糖周期主导需谨慎", "view": "谨慎·观察糖周期"},
    "SB": {"name": "大豆", "emoji": "🫘", "unit": "元/吨", "hist_main": 6.9, "hist_window": "峰值后6-12月",
           "signal": "区域性对冲，全球合计效应弱", "view": "最弱·放弃"},
    "CT": {"name": "棉花", "emoji": "🧵", "unit": "元/吨", "hist_main": 15.9, "hist_window": "峰值后6-12月",
           "signal": "美棉方向取决于具体降水模式", "view": "方向不定·放弃"},
}

STRATEGY = {
    "conclusion": "主做棕榈油，橡胶作先行信号，白糖谨慎，大豆/棉花放弃",
    "why_palm": [
        "供给最确定：东南亚对厄尔尼诺最敏感，去趋势后几乎每次减产",
        "生理滞后8-18月：减产2027年才兑现，现在是布局窗口而非追高",
        "主导模式=供给+宏观共振，当前宏观顺风正好共振",
        "主升浪post6_12 +36.6%，当前启动期未启动，空间最大",
    ],
    "timing": [
        "现在(启动期)：不追高、不做空，轻仓试探或观望",
        "峰值确认后(2026底-2027初)：逢回调建仓棕榈油",
        "2027上半年(post0_6→post6_12)：供给兑现+宏观若顺风→棕榈油主升浪兑现",
    ],
    "risks": [
        "油价地缘溢价消退(US-Iran谈判可致单日-5%)→宏观顺风转弱",
        "PMI边际走弱(8月新订单56.7→53.7大幅放缓)",
        "预期透支(橡胶已提前涨，接近历史主升浪均值)",
        "历史最危险轨迹=顺风转逆风(1997/98金融危机样本，棕榈post12_24崩-45.7%)",
    ],
}

ANALOG_TABLE = [
    {"id": "1982/83", "strength": "超强", "macro": "逆风转顺风", "result": "棕榈+106%、糖+77%暴涨",
     "match": "超强东部型+快速形成，最接近当前"},
    {"id": "2009/10", "strength": "中强", "macro": "全程顺风", "result": "棕榈滞后窗口+44.7%",
     "match": "顺风复苏，供给+宏观共振"},
    {"id": "1997/98", "strength": "超强", "macro": "顺风转逆风", "result": "金融危机→橡胶/大豆反跌",
     "match": "⚠️ 警惕样本：宏观转逆风则超强也反跌"},
    {"id": "2014/16", "strength": "超强", "macro": "商品熊市", "result": "涨幅被系统性压制",
     "match": "宏观压制样本：超强≠必然大涨"},
]


def pct(a, b):
    if a is None or b is None or a == 0:
        return None
    return round((b - a) / a * 100, 1)


def get_month_last(series, ym):
    """取某月最后一个交易日的值（日度数据），如 get_month_last(series,'2026-01')"""
    vals = [(d, v) for d, v in series if d[:7] == ym and v is not None]
    return vals[-1][1] if vals else None


def build_tracking(series):
    s = {k: sorted(v, key=lambda x: x[0]) for k, v in series.items() if v}

    # 事件状态（SOI 月度）
    soi = s.get("soi", [])
    soi_latest = soi[-1][1] if soi else None
    soi_neg = [v for _, v in soi if v is not None and v < 0]
    soi_peak_neg = min(soi_neg) if soi_neg else None

    # 宏观（PMI 月度 + 原油日度）
    pmi = s.get("pmi", [])
    oil = s.get("oil", [])
    pmi_latest = pmi[-1][1] if pmi else None
    oil_latest = oil[-1][1] if oil else None
    oil_latest_date = oil[-1][0] if oil else None
    oil_peak = max([v for _, v in oil if v is not None]) if oil else None

    # 品种涨幅（日度数据，锚点取月末收盘）
    commodities = {}
    code_map = {"P": "palm", "RU": "rubber", "SR": "sugar", "SB": "soybean", "CT": "cotton"}
    for code, skey in code_map.items():
        meta = COMMODITY_META[code]
        sd = s.get(skey, [])
        latest = sd[-1][1] if sd else None
        latest_date = sd[-1][0] if sd else None
        v_jan = get_month_last(sd, "2026-01")   # 年初
        v_apr = get_month_last(sd, "2026-04")   # 启动期(SOI转负)
        v_ago = get_month_last(sd, "2025-08")   # 同比
        ytd = pct(v_jan, latest)
        phase = pct(v_apr, latest)
        yoy = pct(v_ago, latest)
        progress = None
        if phase is not None and meta["hist_main"]:
            progress = round(max(phase, 0) / meta["hist_main"] * 100)
        commodities[code] = {
            "name": meta["name"], "emoji": meta["emoji"], "unit": meta["unit"],
            "latest": latest, "latest_date": latest_date,
            "ytd": ytd, "phase": phase, "yoy": yoy,
            "hist_main": meta["hist_main"], "hist_window": meta["hist_window"],
            "progress": progress, "signal": meta["signal"], "view": meta["view"],
        }

    tracking = {
        "generated": datetime.date.today().strftime("%Y-%m-%d"),
        "freq": "周度",
        "event": dict(EVENT, soi_latest=soi_latest, soi_peak_neg=soi_peak_neg,
                       soi_series=[[d[:7], v] for d, v in soi]),
        "macro": {
            "pmi_latest": pmi_latest,
            "pmi_trend": "2025下半年收缩(48)→2026转扩张(52-55)，7月55.6近四年高点，8月回落54.6",
            "pmi_direction": "逆风转顺风（复苏转向）",
            "oil_latest": oil_latest, "oil_latest_date": oil_latest_date, "oil_peak": oil_peak,
            "oil_trend": "2025底62→4月峰值120.4(+94%)→7月回落83→9月再涨109",
            "oil_direction": "9月再度走强(+17%)，中东地缘溢价重燃",
            "trajectory": "逆风转顺风",
            "risk": "油价120→83→109剧烈震荡，地缘驱动不确定性极高；PMI新订单56.7→53.7边际走弱",
        },
        "commodities": commodities,
        "strategy": STRATEGY,
        "analog_table": ANALOG_TABLE,
    }
    return tracking


def main():
    print("拉取 iFinD EDB 数据…")
    series = fetch_series()
    raw_out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tracking_series.json")
    json.dump(series, open(raw_out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已存 {raw_out}")

    print("计算涨幅 + 生成 tracking.json…")
    tracking = build_tracking(series)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tracking.json")
    json.dump(tracking, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已存 {out}")
    print("\n=== 摘要（周度口径）===")
    print(f"SOI: {tracking['event']['soi_latest']} (峰值负值 {tracking['event']['soi_peak_neg']})")
    print(f"PMI: {tracking['macro']['pmi_latest']}  原油: {tracking['macro']['oil_latest']} ({tracking['macro']['oil_latest_date']})")
    for code, c in tracking["commodities"].items():
        print(f"{c['emoji']} {c['name']}: 最新{c['latest']}({c['latest_date']}) 年初至今{c['ytd']}% 启动期{c['phase']}% 进度{c['progress']}%")


if __name__ == "__main__":
    main()
