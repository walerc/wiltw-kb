#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_forecast.py — CFSv2 未来降水预报，聚合到棕榈产区

数据源：NOAA CFSv2（NOMADS）
  daily prate（time_grib）：未来 45 天，6 小时步长降水率 → 聚合到日
  monthly flxf（monthly_grib）：前 2 个月月度平均降水

用法：
  cd ~/WILTW_KB/elnino && /usr/bin/python3 fetch_forecast.py

输出：data/forecast_regions.json —— 各产区未来 45 天日度 + 2 个月月度降水(mm)
依赖：cfgrib + eccodes（已 pip 安装）
"""
import json, os, sys, urllib.request, datetime, argparse, calendar
import numpy as np
import cfgrib

BASE = os.path.dirname(os.path.abspath(__file__))
NOMADS = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/cfs/prod"
CACHE = os.path.join(BASE, "data", "cfs_cache")
os.makedirs(CACHE, exist_ok=True)


def load_palm_regions():
    d = json.load(open(os.path.join(BASE, "data", "production_regions.json"), encoding="utf-8"))
    return [r for r in d["regions"] if r["commodity"] == "棕榈油"]


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


def read_monthly_prate(grib_path):
    ds = cfgrib.open_datasets(grib_path, backend_kwargs={"filter_by_keys": {"shortName": "prate"}})
    d = ds[0]
    return d["prate"].values, d["latitude"].values, d["longitude"].values


def main():
    run = find_latest_run()
    regions = load_palm_regions()
    print(f"CFSv2 预报初始日期: {run}")

    # === 1. daily prate（未来 45 天）===
    daily_url = f"{NOMADS}/cfs.{run}/00/time_grib_01/prate.01.{run}00.daily.grb2"
    daily_path = os.path.join(CACHE, f"prate_daily_{run}.grb2")
    print("下载 daily prate（未来45天）...")
    download(daily_url, daily_path)
    pr, lat, lon, vt = read_daily_prate(daily_path)
    print(f"  daily PRATE shape: {pr.shape}, 时间 {vt[0]} ~ {vt[-1]}")

    # 6小时时次 → 日降水：每个时次 PRATE(kg/m2/s) × 21600s = mm/6h，4个时次求和 = mm/日
    # 先按日期分组
    dates = [np.datetime64(v).astype('datetime64[D]') for v in vt]
    uniq_dates = sorted(set(dates))
    daily_mm = {}  # {date_str: prate[lat,lon] 日降水 mm}
    # 逐日聚合
    for ud in uniq_dates:
        idx = [i for i, dd in enumerate(dates) if dd == ud]
        day_pr = pr[idx].sum(axis=0) * 21600  # 6h时次求和 × 21600s
        daily_mm[np.datetime_as_string(ud, unit='D')] = day_pr

    # === 2. monthly flxf（前 2 个月）===
    monthly = {}
    today = datetime.date.today()
    for offset in [0, 1]:  # 当前月 + 下月
        y = today.year + (today.month + offset - 1) // 12
        m = (today.month + offset - 1) % 12 + 1
        ym = f"{y}{m:02d}"
        murl = f"{NOMADS}/cfs.{run}/00/monthly_grib_01/flxf.01.{run}00.{ym}.avrg.grib.grb2"
        mpath = os.path.join(CACHE, f"flxf_{ym}.grb2")
        try:
            download(murl, mpath)
            mpr, mlat, mlon = read_monthly_prate(mpath)
            secs = calendar.monthrange(y, m)[1] * 86400
            monthly[f"{y}-{m:02d}"] = mpr * secs  # mm/月
            print(f"  monthly {y}-{m:02d}: 已加载")
        except Exception as e:
            print(f"  monthly {y}-{m:02d}: 失败 {e}")

    # === 3. 聚合到产区 ===
    result = {
        "generated": today.strftime("%Y-%m-%d"),
        "source": "NOAA CFSv2 (daily 45d + monthly 2mo, member 1)",
        "run_date": run,
        "regions": [{"id": r["id"], "name": r["name_zh"], "country": r["country"]} for r in regions],
        "daily": [],   # [{date, per_region}]
        "monthly": [], # [{ym, per_region}]
    }
    for ds_str in sorted(daily_mm):
        per = {r["id"]: round(region_mean(daily_mm[ds_str], lat, lon, r), 1) for r in regions}
        result["daily"].append({"date": ds_str, "per_region": per})
    for ym in sorted(monthly):
        per = {r["id"]: round(region_mean(monthly[ym], lat, lon, r), 1) for r in regions}
        result["monthly"].append({"ym": ym, "per_region": per})

    out = os.path.join(BASE, "data", "forecast_regions.json")
    json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n已保存 {out}")
    # 摘要
    print("=== 未来月度降水预报（核心产区均值 mm/月）===")
    for m in result["monthly"]:
        core = [v for k, v in m["per_region"].items() if v is not None and k.startswith("palm")]
        if core:
            print(f"  {m['ym']}: {round(sum(core)/len(core), 1)} mm")


if __name__ == "__main__":
    main()
