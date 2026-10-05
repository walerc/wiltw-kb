#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weather_series_calc.py — 短期降雨历史周度时间序列

从 weather_history.csv（日度降水，格点中位数口径）按 ISO 周聚合，
生成 data/weather_series.json，供前端短期降雨详情框画历史走势折线图。

口径与 fetch_weather.py 的快照 precip_this 一致：
  precip_this = 近7日累计降水 = 7 天「日度格点中位数」之和
故历史序列 = 每周 7 天 precip_mm 之和（median 口径）。

输出结构:
  {
    "meta": {"indicator", "unit", "weeks": [...], "updated"},
    "series": {
      rid: {
        "precip": [...],        # 每周累计降水(mm)
        "climate_mean": [...]   # 该ISO周序号的20年同期均值(mm)
      }
    }
  }

用法: cd ~/WILTW_KB/elnino && /usr/bin/python3 weather_series_calc.py
"""
import os, csv, json, datetime, sys
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
HIST_PATH = os.path.join(BASE, "data", "weather_history.csv")
OUT_PATH = os.path.join(BASE, "data", "weather_series.json")


def iso_week(date_str):
    dt = datetime.date.fromisoformat(date_str)
    iso = dt.isocalendar()
    return (iso[0], iso[1])


def main():
    if not os.path.exists(HIST_PATH):
        print(f"错误: {HIST_PATH} 不存在，先运行 fetch_weather_history.py", file=sys.stderr)
        return

    # 加载日度降水 {rid: {date_str: precip_mm}}
    daily = defaultdict(dict)
    with open(HIST_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rid = row.get("region_id")
            if not rid or not row.get("precip_mm"):
                continue
            try:
                v = float(row["precip_mm"])
            except (ValueError, TypeError):
                continue
            daily[rid][row["date"]] = v

    if not daily:
        print("错误: 无有效降水数据", file=sys.stderr)
        return

    # 全局完整周时间轴（所有产区共享）
    all_dates = set()
    for rid in daily:
        all_dates |= set(daily[rid].keys())
    min_date = min(all_dates)
    max_date = max(all_dates)

    def week_dates(yw, ww):
        d = datetime.date.fromisocalendar(yw, ww, 1)
        return [d + datetime.timedelta(days=i) for i in range(7)]

    def is_complete_week(yw, ww):
        return all(dt.isoformat() in all_dates for dt in week_dates(yw, ww))

    global_weeks = []
    cur = datetime.date.fromisoformat(min_date)
    cur = cur - datetime.timedelta(days=cur.isocalendar()[2] - 1)  # 回到周一
    end = datetime.date.fromisoformat(max_date)
    while cur <= end:
        iso = cur.isocalendar()
        key = (iso[0], iso[1])
        if is_complete_week(*key) and key not in global_weeks:
            global_weeks.append(key)
        cur += datetime.timedelta(days=7)

    today = datetime.date.today()

    # 追加「近7日」最新数据点（与卡片 precip_this 对齐，解决柱状图最新ISO周与卡片近7日窗口不一致）
    recent_label = None
    recent_by_rid = {}
    wr_path = os.path.join(BASE, "data", "weather_regions.json")
    if os.path.exists(wr_path):
        try:
            wr = json.load(open(wr_path, encoding="utf-8"))
            wm = wr.get("meta", {}) or {}
            ws = wm.get("window_start", "") or ""
            we = wm.get("window_end", "") or ""
            if ws and we:
                recent_label = f"近7日 {ws}~{we}"
            for r in wr.get("regions", []) or []:
                if r.get("precip_this") is not None:
                    recent_by_rid[r["id"]] = r["precip_this"]
        except Exception as e:
            print(f"⚠️ 读取 weather_regions.json 失败，跳过近7日点: {e}", file=sys.stderr)

    week_labels = [f"{yw}-W{ww:02d}" for yw, ww in global_weeks]
    if recent_label:
        week_labels.append(recent_label)

    result = {"meta": {
        "indicator": "周度累计降水（格点中位数口径）",
        "unit": "mm",
        "weeks": week_labels,
        "updated": today.strftime("%Y-%m-%d"),
        "note": "按ISO周聚合(仅完整周)；末尾追加「近7日」点与卡片 precip_this 窗口对齐(同口径)。",
    }, "series": {}}

    for rid in sorted(daily.keys()):
        dmap = daily[rid]
        # 周累计 = 该周7天 precip_mm 之和
        weekly_sum = defaultdict(lambda: [0.0, 0])
        for ds, v in dmap.items():
            key = iso_week(ds)
            weekly_sum[key][0] += v
            weekly_sum[key][1] += 1
        # 只保留完整周
        weekly = {}
        for key, (s, n) in weekly_sum.items():
            if is_complete_week(*key) and n >= 7:
                weekly[key] = s
        if not weekly:
            continue

        # 对齐全局周轴
        precip = []
        climate_mean = []
        # 该ISO周序号的20年同期均值（周内所有年份累加值求平均）
        by_weeknum = defaultdict(list)
        for (yw, ww), s in weekly.items():
            by_weeknum[ww].append(s)
        weeknum_mean = {ww: (sum(v) / len(v)) for ww, v in by_weeknum.items()}

        for (yw, ww) in global_weeks:
            v = weekly.get((yw, ww))
            precip.append(round(v, 1) if v is not None else None)
            cm = weeknum_mean.get(ww)
            climate_mean.append(round(cm, 1) if cm is not None else None)

        # 追加近7日点（与卡片窗口对齐；无同期均值，climate_mean 补 None）
        if recent_label and rid in recent_by_rid:
            precip.append(round(float(recent_by_rid[rid]), 1))
            climate_mean.append(None)

        result["series"][rid] = {"precip": precip, "climate_mean": climate_mean}

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    print(f"已写入 {OUT_PATH}（{len(global_weeks)} 周 × {len(result['series'])} 产区）")
    print(f"最新完整周: {global_weeks[-1] if global_weeks else '—'}")


if __name__ == "__main__":
    main()
