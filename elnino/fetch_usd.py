#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉取美联储实际美元指数:广义(REER, 月度) 1982-2024，保存为 usd_index.json。
用于厄尔尼诺价格分析中剔除美元汇率波动。
用法: python3 fetch_usd.py
"""
import json, os, re, sys, time

SKILL_DIR = os.path.expanduser("~/.hermes/skills/ifind-finance-data")
sys.path.insert(0, SKILL_DIR)
os.chdir(SKILL_DIR)  # call.py 依赖同目录 mcp_config.json
from call import call  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "usd_index.json")

SEGMENTS = ["1982-1989", "1990-1997", "1998-2005", "2006-2013", "2014-2021", "2022-2024"]


def fetch(query):
    r = call("edb", "get_edb_data", {"query": query})
    s = json.dumps(r, ensure_ascii=False)
    return re.findall(r'\|(\d{4}-\d{2}-\d{2})\|([\d.]+)\|', s)


def main():
    seen = {}
    for seg in SEGMENTS:
        rows = fetch(f"美国:实际美元指数:广义 {seg}")
        n_before = len(seen)
        for d, v in rows:
            seen[d] = float(v)
        print(f"  {seg}: 新增 {len(seen)-n_before} 月")
        time.sleep(1.5)  # 免费用户限流

    dates = sorted(seen.keys())
    series = {d: seen[d] for d in dates}
    print(f"共 {len(series)} 个月度数据: {dates[0]} -> {dates[-1]}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"indicator": "美国:实际美元指数:广义", "unit": "2006年1月=100",
                   "freq": "月度", "data": series}, f, ensure_ascii=False, indent=1)
    print(f"已保存 {OUT}")


if __name__ == "__main__":
    main()
