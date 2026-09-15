#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉取豆粕/豆油/玉米 CBOT 价格 + 玉米产量，存缓存 JSON。
- 价格：CBOT 豆粕(美元/短吨)/豆油(美分/磅)/玉米(美分/蒲式耳)，日度，1973起，分6段查询
- 产量：美国玉米(百万蒲式耳)/中国玉米(万吨)/巴西玉米(吨)，年度
输出：data/grains_price.json + data/corn_prod.json
用法: python3 fetch_grains.py
"""
import json, os, re, urllib.request, time

BASE = os.path.dirname(os.path.abspath(__file__))
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


# 价格指标（CBOT，日度，1973起）
PRICES = {
    "M":  "期货结算价(连续):CBOT豆粕",   # 美元/短吨
    "Y":  "期货结算价(连续):CBOT豆油",   # 美分/磅
    "C":  "期货结算价(连续):CBOT玉米",   # 美分/蒲式耳
}
# 玉米产量指标（年度）
PRODS = {
    "CUS": "美国:玉米:产量",    # 百万蒲式耳
    "CCN": "全国:玉米产量",     # 万吨
    "CBR": "玉米:产量:巴西",    # 吨
}
# 价格分段（日度数据量大，按10年一段）
PRICE_SEGS = [(1973, 1980), (1980, 1990), (1990, 2000), (2000, 2010), (2010, 2020), (2020, 2026)]


def main():
    # 1. 价格（分6段查询）
    prices = {}
    for code, name in PRICES.items():
        all_rows = []
        for y1, y2 in PRICE_SEGS:
            q = f"{name} {y1}年1月到{y2}年12月"
            datas = query_edb(q)
            if datas and isinstance(datas, list) and datas[0].get("data", {}).get("data"):
                rows = datas[0]["data"]["data"]
                all_rows.extend(rows)
                print(f"  {code} {y1}-{y2}: {len(rows)}点", flush=True)
            else:
                print(f"  {code} {y1}-{y2}: EMPTY", flush=True)
            time.sleep(0.5)
        # 去重（段间重叠）+ 排序
        seen = {}
        for d, v in all_rows:
            seen[d] = v
        prices[code] = sorted(seen.items(), key=lambda x: x[0])
        print(f"  {code} 合计: {len(prices[code])}点", flush=True)

    # 2. 玉米产量（年度，单次查询）
    prods = {}
    for code, name in PRODS.items():
        datas = query_edb(f"{name} 1960年1月到2026年1月")
        if datas and isinstance(datas, list) and datas[0].get("data", {}).get("data"):
            rows = datas[0]["data"]["data"]
            prods[code] = sorted(rows, key=lambda x: x[0])
            print(f"  {code} ({name}): {len(rows)}点", flush=True)
        else:
            prods[code] = []
            print(f"  {code} ({name}): EMPTY", flush=True)
        time.sleep(0.5)

    json.dump(prices, open(os.path.join(BASE, "data", "grains_price.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(prods, open(os.path.join(BASE, "data", "corn_prod.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已存 data/grains_price.json + data/corn_prod.json")


if __name__ == "__main__":
    main()
