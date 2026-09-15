#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉取白糖产量数据（印度/泰国/巴西，年度），存 sugar_prod.json。
用于厄尔尼诺归因拆解中补齐白糖供给数据。"""
import sys, os, json, re, time
sys.path.insert(0, os.path.expanduser("~/.hermes/skills/ifind-finance-data"))
os.chdir(os.path.expanduser("~/.hermes/skills/ifind-finance-data"))
from call import call

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sugar_prod.json")

# 指标名 → 输出键。单位统一为千吨（中国:食糖:产量 是千吨，全国:食糖产量 是万吨需×10）
INDICATORS = {
    "IN": "糖:产量:印度",
    "TH": "糖:产量:泰国",
    "BR": "糖:产量:巴西",
    "CN": "中国:食糖:产量",
}

SEGMENTS = ["1960-1969", "1970-1979", "1980-1989", "1990-1999",
            "2000-2009", "2010-2019", "2020-2024"]


def fetch(query):
    r = call("edb", "get_edb_data", {"query": query})
    s = json.dumps(r, ensure_ascii=False)
    return re.findall(r'\|(\d{4}-\d{2}-\d{2})\|([\d.]+)\|', s)


def fetch_series(indicator):
    seen = {}
    for seg in SEGMENTS:
        rows = fetch(f"{indicator} {seg}")
        for d, v in rows:
            y = d[:4]
            seen[y] = float(v)
        time.sleep(1.0)
    return seen


def main():
    out = {"note": "", "unit": "千吨", "data": {}}
    for key, ind in INDICATORS.items():
        series = fetch_series(ind)
        dates = sorted(series.keys())
        print(f"{key} ({ind}): {len(series)} 年 ({dates[0]}->{dates[-1]})", flush=True)
        out["data"][key] = {"indicator": ind, "series": series}
    out["note"] = "白糖产量（年度，千吨）：印度IN/泰国TH/巴西BR为全球三大产糖国(巴西第一、印度第二、泰国第三)。中国CN补充。数据源 iFinD EDB。"
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"已保存 {OUT}", flush=True)


if __name__ == "__main__":
    main()
