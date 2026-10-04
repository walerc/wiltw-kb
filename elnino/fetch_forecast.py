#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_forecast.py — CFSv2 未来降水预报（周度/半月口径），聚合到棕榈产区

数据源：NOAA CFSv2（NOMADS）
  daily prate（time_grib）：未来 45 天，6 小时步长降水率 → 聚合到日

口径说明（避免长预报失真）：
  CFSv2 月度(monthly)预报只覆盖前2个月、且超半月后技巧大幅下降，
  故改为「周度 + 半月」三窗口，只取日度预报的前 15 天：
    未来1周   = 第 1-7  天累计降水(mm)
    未来第2周 = 第 8-14 天累计降水(mm)
    未来半月  = 第 1-15 天累计降水(mm)

用法：
  cd ~/WILTW_KB/elnino && /usr/bin/python3 fetch_forecast.py

输出：data/forecast_regions.json —— 各产区 w1/w2/hm 三窗口累计降水 + 偏干分级
依赖：cfgrib + eccodes（已 pip 安装）
"""
import json, os, sys, urllib.request, datetime, argparse
import numpy as np
import cfgrib

BASE = os.path.dirname(os.path.abspath(__file__))
NOMADS = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/cfs/prod"
CACHE = os.path.join(BASE, "data", "cfs_cache")
os.makedirs(CACHE, exist_ok=True)


def load_palm_regions():
    d = json.load(open(os.path.join(BASE, "data", "production_regions.json"), encoding="utf-8"))
    return [r for r in d["regions"] if r["commodity"] == "棕榈油"]


def fc_level(hm):
    """半月累计降水 → 偏干/正常/偏湿分级（热带产区口径）"""
    if hm is None:
        return "—", "na"
    if hm < 15:
        return "严重偏干", "extreme_drought"
    if hm < 30:
        return "偏干", "dry"
    if hm <= 60:
        return "正常", "normal"
    return "偏湿", "wet"


def find_latest_run():
    today = datetime.date.today()
    for i in range(10):
        d = today - datetime.timedelta(days=i)
        ymd = d.strftime("%Y%m%d")
        idx_url = f"{NOMADS}/cfs.{ymd}/00/time_grib_01/prate.01.{ymd}00.daily.grb2.idx"
        try:
            req = urllib.request.Request(idx_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    return ymd
        except Exception:
            continue
    return today.strftime("%Y%m%d")


def download(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=240) as r:
        open(path, "wb").write(r.read())


def region_mean(pr, lat, lon, region):
    lat_sel = (lat >= region["south"]) & (lat <= region["north"])
    lon_sel = (lon >= region["west"]) & (lon <= region["east"])
    if lat_sel.sum() == 0 or lon_sel.sum() == 0:
        return None
    sub = pr[np.ix_(lat_sel, lon_sel)]
    return float(np.nanmean(sub)) if sub.size else None


def read_daily_prate(grib_path):
    """读 daily prate，返回 (prate[step,lat,lon], lat, lon, valid_times[datetime])"""
    ds = cfgrib.open_datasets(grib_path, backend_kwargs={"filter_by_keys": {"shortName": "prate"}})
    d = ds[0]
    pr = d["prate"].values  # (step, lat, lon) kg/m2/s
    lat = d["latitude"].values
    lon = d["longitude"].values
    vt = d["valid_time"].values  # numpy datetime64
    return pr, lat, lon, vt


def sum_window(vals, start, end):
    """vals = [(date_str, mm_or_None), ...]，累加 [start, end) 区间内非 None 值"""
    s = 0.0
    n = 0
    for i in range(start, min(end, len(vals))):
        v = vals[i][1]
        if v is not None:
            s += v
            n += 1
    return round(s, 1) if n else None


def main():
    run = find_latest_run()
    regions = load_palm_regions()
    print(f"CFSv2 预报初始日期: {run}")

    # === daily prate（未来 45 天），只取前 15 天算周度/半月 ===
    daily_url = f"{NOMADS}/cfs.{run}/00/time_grib_01/prate.01.{run}00.daily.grb2"
    daily_path = os.path.join(CACHE, f"prate_daily_{run}.grb2")
    print("下载 daily prate（未来45天）...")
    download(daily_url, daily_path)
    pr, lat, lon, vt = read_daily_prate(daily_path)
    print(f"  daily PRATE shape: {pr.shape}, 时间 {vt[0]} ~ {vt[-1]}")

    # 6小时时次 → 日降水：每个时次 PRATE(kg/m2/s) × 21600s = mm/6h，4个时次求和 = mm/日
    dates = [np.datetime64(v).astype('datetime64[D]') for v in vt]
    uniq_dates = sorted(set(dates))
    daily_mm = {}  # {date_str: prate[lat,lon] 日降水 mm}
    for ud in uniq_dates:
        idx = [i for i, dd in enumerate(dates) if dd == ud]
        day_pr = pr[idx].sum(axis=0) * 21600  # 6h时次求和 × 21600s
        daily_mm[np.datetime_as_string(ud, unit='D')] = day_pr
    sorted_dates = sorted(daily_mm.keys())
    print(f"  日度数据 {len(sorted_dates)} 天：{sorted_dates[0]} ~ {sorted_dates[-1]}")

    # === 逐产区日序列 → 三窗口累计 ===
    region_daily = {r["id"]: [] for r in regions}
    for ds in sorted_dates:
        arr = daily_mm[ds]
        for r in regions:
            region_daily[r["id"]].append((ds, region_mean(arr, lat, lon, r)))

    result = {
        "generated": datetime.date.today().strftime("%Y-%m-%d"),
        "source": "NOAA CFSv2 (daily prate, member 1)",
        "run_date": run,
        "window_note": "周度/半月口径：未来1周(1-7天)/未来第2周(8-14天)/未来半月(1-15天)累计降水(mm)",
        "regions": [],
    }
    for r in regions:
        vals = region_daily[r["id"]]
        w1 = sum_window(vals, 0, 7)
        w2 = sum_window(vals, 7, 14)
        hm = sum_window(vals, 0, 15)
        cond, level = fc_level(hm)
        result["regions"].append({
            "id": r["id"],
            "commodity": r["commodity"],
            "country": r["country"],
            "state": r.get("state", ""),
            "name": r["name_zh"],
            "rank": r.get("rank", ""),
            "global_share": r.get("global_share"),
            "center_lon": round((r["west"] + r["east"]) / 2, 2),
            "center_lat": round((r["north"] + r["south"]) / 2, 2),
            "w1": w1,          # 未来1周累计 mm
            "w2": w2,          # 未来第2周累计 mm
            "hm": hm,          # 未来半月(15天)累计 mm
            "condition": cond,
            "level": level,
        })

    out = os.path.join(BASE, "data", "forecast_regions.json")
    json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n已保存 {out}")
    print("=== 未来降水预报（核心产区累计 mm）===")
    print(f"  {'产区':<14} {'未来1周':>8} {'未来2周':>8} {'未来半月':>8}  评级")
    for r in result["regions"]:
        f = lambda v: '—' if v is None else f"{v:.1f}"
        print(f"  {r['name']:<14} {f(r['w1']):>8} {f(r['w2']):>8} {f(r['hm']):>8}  {r['condition']}")


if __name__ == "__main__":
    main()
