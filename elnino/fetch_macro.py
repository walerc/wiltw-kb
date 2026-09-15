#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉取宏观周期数据：美国ISM制造业PMI + IMF原油价格（月度，1982-2024），保存为 macro_series.json。
用于厄尔尼诺分析中叠加宏观周期。
用法: python3 fetch_macro.py
"""
import json, os, re, sys, time

SKILL_DIR = os.path.expanduser("~/.hermes/skills/ifind-finance-data")
sys.path.insert(0, SKILL_DIR)
os.chdir(SKILL_DIR)
from call import call  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "macro_series.json")

SEGMENTS = ["1982-1989", "1990-1997", "1998-2005", "2006-2013", "2014-2021", "2022-2024"]


def fetch(query):
    r = call("edb", "get_edb_data", {"query": query})
    s = json.dumps(r, ensure_ascii=False)
    return re.findall(r'\|(\d{4}-\d{2}-\d{2})\|([\d.]+)\|', s)


def fetch_series(indicator):
    seen = {}
    for seg in SEGMENTS:
        rows = fetch(f"{indicator} {seg}")
        for d, v in rows:
            ym = d[:7]
            seen[ym] = float(v)
        time.sleep(1.5)
    return seen


def main():
    pmi = fetch_series("美国:ISM:制造业PMI")
    oil = fetch_series("商品价格:布伦特原油:当月值")
    pmi_dates = sorted(pmi.keys())
    oil_dates = sorted(oil.keys())
    print(f"PMI: {len(pmi)} 月 ({pmi_dates[0]} -> {pmi_dates[-1]})")
    print(f"原油: {len(oil)} 月 ({oil_dates[0]} -> {oil_dates[-1]})")

    out = {
        "pmi": {"indicator": "美国:ISM:制造业PMI", "freq": "月度", "data": pmi},
        "oil": {"indicator": "商品价格:原油:当月值", "unit": "美元/桶(IMF)", "freq": "月度", "data": oil},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"已保存 {OUT}")


if __name__ == "__main__":
    main()
