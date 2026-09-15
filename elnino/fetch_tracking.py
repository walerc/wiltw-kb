#!/usr/bin/env python3
"""
fetch_tracking.py — 拉取当前厄尔尼诺 + 宏观 + 5品种最新数据，生成跟踪页 tracking.json

数据源：iFinD EDB（南方涛动指数SOI / ISM PMI / 布伦特原油 / IMF商品价格 / CBOT大豆 / 郑棉）
输出：data/tracking.json（前端「🛰️ 实时跟踪」tab 读取）

运行：cd ~/WILTW_KB/elnino && /usr/bin/python3 fetch_tracking.py
更新频率建议：每月1次（月度数据），或厄尔尼诺关键节点（CPC发布月度诊断）时手动跑
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


def month_range(n=20):
    """返回 (起始年月, 结束年月) 字符串，如 ('2025年1月','2026年8月')，覆盖最近 n 个月"""
    now = datetime.date.today()
    total = now.year * 12 + (now.month - 1)
    s_total = total - (n - 1)
    sy, sm = s_total // 12, s_total % 12 + 1
    return f"{sy}年{sm}月", f"{now.year}年{now.month}月"


def fetch_series():
    start, end = month_range(20)
    monthly = {
        "soi": f"南方涛动指数 {start}到{end}",
        "pmi": f"美国:ISM:制造业PMI {start}到{end}",
        "oil": f"商品价格:布伦特原油:当月值 {start}到{end}",
        "palm": f"商品价格:棕榈油:当月值 {start}到{end}",
        "rubber": f"商品价格:天然橡胶(RSS3):当月值 {start}到{end}",
        "sugar": f"商品价格:全球糖:当月值 {start}到{end}",
        "cotton": f"商品价格:棉花:当月值 {start}到{end}",
    }
    series = {}
    for k, q in monthly.items():
        datas = query_edb(q)
        if datas and isinstance(datas, list) and datas[0].get("data", {}).get("data"):
            series[k] = datas[0]["data"]["data"]
        else:
            series[k] = None
        print(f"  {k}: {len(series[k]) if series[k] else 'EMPTY'} 点")

    # 大豆 CBOT 日度 → 取月末
    ds = query_edb(f"期货结算价(连续):CBOT大豆 {start}到{end}")
    soy = {}
    if ds and isinstance(ds, list):
        for d, v in ds[0]["data"]["data"]:
            soy[d[:7]] = v
    series["soybean"] = [[k + "-28", v] for k, v in sorted(soy.items())]
    print(f"  soybean: {len(series['soybean'])} 点(月末)")

    # 棉花若是日度 → 取月末
    if series["cotton"] and len(series["cotton"]) > 40:
        cm = {}
        for d, v in series["cotton"]:
            cm[d[:7]] = v
        series["cotton"] = sorted([[k + "-28", v] for k, v in cm.items()])

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
    "P":  {"name": "棕榈油", "emoji": "🌴", "unit": "美元/吨", "hist_main": 36.6, "hist_window": "峰值后6-12月",
           "signal": "供给冲击滞后(8-18月生理滞后)，主升浪尚未启动", "view": "首选·布局"},
    "RU": {"name": "橡胶", "emoji": "🌳", "unit": "美分/千克", "hist_main": 21.2, "hist_window": "峰值后0-6月",
           "signal": "最早反应已基本兑现，追高空间有限", "view": "次选·先行信号"},
    "SR": {"name": "白糖", "emoji": "🍬", "unit": "美元/千克", "hist_main": 6.5, "hist_window": "各窗口温和",
           "signal": "8月跳升，糖周期主导需谨慎", "view": "谨慎·观察糖周期"},
    "SB": {"name": "大豆", "emoji": "🫘", "unit": "美分/蒲式耳", "hist_main": 6.9, "hist_window": "峰值后6-12月",
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
        "主升浪post6_12 +36.6%，当前启动期仅-2.5%，空间最大",
    ],
    "timing": [
        "现在(启动期)：不追高、不做空，轻仓试探或观望",
        "峰值确认后(2026底-2027初)：逢回调建仓棕榈油",
        "2027上半年(post0_6→post6_12)：供给兑现+宏观若顺风→棕榈油主升浪兑现",
    ],
    "risks": [
        "油价地缘溢价消退(US-Iran谈判可致单日-5%)→宏观顺风转弱",
        "PMI边际走弱(8月新订单56.7→53.7大幅放缓)",
        "预期透支(橡胶已提前涨+27.6%，接近历史主升浪均值)",
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
    """(b-a)/a*100，返回保留1位小数；a<=0 返回 None"""
    if a is None or b is None or a == 0:
        return None
    return round((b - a) / a * 100, 1)


def get_val(series, ym_prefix):
    """取某个年月(前缀)的值，如 get_val(series,'2026-01')"""
    for d, v in series:
        if d[:7] == ym_prefix:
            return v
    return None


def get_month_end(series, ym):
    """取某月的月末值（日度数据），如 get_month_end(series,'2026-08')"""
    vals = [v for d, v in series if d[:7] == ym]
    return vals[-1] if vals else None


def build_tracking(series):
    s = {k: sorted(v, key=lambda x: x[0]) for k, v in series.items() if v}

    # 事件状态
    soi = s.get("soi", [])
    soi_latest = soi[-1][1] if soi else None
    soi_neg = [v for _, v in soi if v is not None and v < 0]
    soi_peak_neg = min(soi_neg) if soi_neg else None

    # 宏观
    pmi = s.get("pmi", [])
    oil = s.get("oil", [])
    pmi_latest = pmi[-1][1] if pmi else None
    oil_latest = oil[-1][1] if oil else None
    oil_peak = max([v for _, v in oil if v is not None]) if oil else None

    # 最新完整月（月度指标的最后一个月，作为统一口径锚点）
    latest_ym = soi[-1][0][:7] if soi else None

    # 品种涨幅
    commodities = {}
    code_map = {"P": "palm", "RU": "rubber", "SR": "sugar", "SB": "soybean", "CT": "cotton"}
    daily_keys = {"soybean", "cotton"}  # 日度品种需取月末，避免取到未来/非完整月数据
    for code, skey in code_map.items():
        meta = COMMODITY_META[code]
        series_data = s.get(skey, [])
        if skey in daily_keys and latest_ym:
            latest = get_month_end(series_data, latest_ym)
        else:
            latest = series_data[-1][1] if series_data else None
        v_jan = get_val(series_data, "2026-01")   # 年初
        v_apr = get_val(series_data, "2026-04")   # 启动期(SOI转负)
        v_ago = get_val(series_data, "2025-08")   # 同比
        ytd = pct(v_jan, latest)
        phase = pct(v_apr, latest)
        yoy = pct(v_ago, latest)
        # 进度 = 启动期涨幅 / 历史主升浪均值
        progress = None
        if phase is not None and meta["hist_main"]:
            progress = round(max(phase, 0) / meta["hist_main"] * 100)
        commodities[code] = {
            "name": meta["name"], "emoji": meta["emoji"], "unit": meta["unit"],
            "latest": latest, "ytd": ytd, "phase": phase, "yoy": yoy,
            "hist_main": meta["hist_main"], "hist_window": meta["hist_window"],
            "progress": progress, "signal": meta["signal"], "view": meta["view"],
        }

    tracking = {
        "generated": datetime.date.today().strftime("%Y-%m-%d"),
        "event": dict(EVENT, soi_latest=soi_latest, soi_peak_neg=soi_peak_neg,
                       soi_series=[[d[:7], v] for d, v in soi]),
        "macro": {
            "pmi_latest": pmi_latest,
            "pmi_trend": "2025下半年收缩(48)→2026转扩张(52-55)，7月55.6近四年高点，8月回落54.6",
            "pmi_direction": "逆风转顺风（复苏转向）",
            "oil_latest": oil_latest, "oil_peak": oil_peak,
            "oil_trend": "2025底62→2026-04峰值120.4(+94%)→回落83→反弹90.9",
            "oil_direction": "暴涨后回落（地缘溢价消退中）",
            "trajectory": "逆风转顺风",
            "risk": "油价地缘溢价脆弱(US-Iran谈判可致单日-5%)，PMI边际走弱(新订单56.7→53.7)",
        },
        "commodities": commodities,
        "strategy": STRATEGY,
        "analog_table": ANALOG_TABLE,
    }
    return tracking


def main():
    print("拉取 iFinD EDB 数据…")
    series = fetch_series()
    # 存原始序列
    raw_out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tracking_series.json")
    json.dump(series, open(raw_out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已存 {raw_out}")

    print("计算涨幅 + 生成 tracking.json…")
    tracking = build_tracking(series)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tracking.json")
    json.dump(tracking, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已存 {out}")
    print("\n=== 摘要 ===")
    print(f"SOI: {tracking['event']['soi_latest']} (峰值负值 {tracking['event']['soi_peak_neg']})")
    print(f"PMI: {tracking['macro']['pmi_latest']}  原油: {tracking['macro']['oil_latest']}")
    for code, c in tracking["commodities"].items():
        print(f"{c['emoji']} {c['name']}: 最新{c['latest']} 年初至今{c['ytd']}% 启动期{c['phase']}% 进度{c['progress']}%")


if __name__ == "__main__":
    main()
