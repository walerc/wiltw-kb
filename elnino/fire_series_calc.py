#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fire_series_calc.py — 从 fire_history.csv 生成火点历史序列（折线/柱状图数据）

输出：data/fire_series.json —— 各产区历史火点数序列 + 累计均值参考线

说明：FIRMS NRT 仅保留近 7 天，历史火点需每次运行 fetch_fire.py 时累积到 fire_history.csv。
     本脚本把累积记录转成前端图表可直接用的序列。
"""
import json, os, csv
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    hist_path = os.path.join(BASE, "data", "fire_history.csv")
    if not os.path.exists(hist_path):
        print("无 fire_history.csv，先运行 fetch_fire.py")
        return

    dates = []
    data = defaultdict(dict)  # {region_id: {date: fire_count}}
    with open(hist_path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            d = row["date"]
            rid = row["region_id"]
            try:
                v = int(row["fire_count"])
            except (ValueError, TypeError):
                continue
            data[rid][d] = v
            if d not in dates:
                dates.append(d)
    dates.sort()

    series = {}
    for rid, dd in data.items():
        fire = []
        mean = []
        cum = 0.0
        n = 0
        for d in dates:
            v = dd.get(d)
            if v is not None:
                fire.append(v)
                cum += v
                n += 1
                mean.append(round(cum / n, 1))
            else:
                fire.append(None)
                mean.append(round(cum / n, 1) if n else None)
        series[rid] = {"fire": fire, "mean": mean}

    result = {
        "meta": {
            "indicator": "近5天火点数（NASA FIRMS VIIRS 375m）",
            "unit": "火点数",
            "dates": dates,
            "note": "累积式历史：FIRMS NRT 仅保留近7天，每次运行 fetch_fire.py 累积一个数据点。mean=截至当日的累计均值。",
        },
        "series": series,
    }
    out = os.path.join(BASE, "data", "fire_series.json")
    json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已保存 {out}（{len(dates)} 天历史，{len(series)} 产区）")


if __name__ == "__main__":
    main()
