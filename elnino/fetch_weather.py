#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_weather.py — 农产品主产区周度降水跟踪（NOAA CPC Unified Gauge 日度降水）

数据源：NOAA CPC Unified Gauge-Based Analysis of Daily Precipitation
  实时(RT)版: https://ftp.cpc.ncep.noaa.gov/precip/CPC_UNI_PRCP/GAUGE_GLB/RT/{年}/PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.{YYYYMMDD}.RT
  最终(V1.0)版: 1979-2005 (完整站点，历史基线用，路径 .../GAUGE_GLB/V1.0/{年}/)
  二进制: little_endian float32, 720x360 格点(0.5°), 2 变量
          变量1=rain(0.1mm/day, undef=-999.0), 变量2=gnum(站点数)
  经纬度: lon[i]=0.25+i*0.5 (i=0..719); lat[j]=-89.75+j*0.5 (j=0..359, j=0是南纬!)

关键坑(2026-09 踩过)：
  - ydef linear -89.75 → j=0 在南纬-89.75，lat_to_j 用 (lat+89.75)/0.5，勿倒序
  - 南美(巴西)站点延迟3-6天：最新1-2天仅5格点，6天前已135格点 → 用 --lag 5 滞后窗口
  - 美国站点实时完整(89-176格点)；阿根廷圣塔菲/科尔多瓦本身稀疏(7-13格点)
  - 文件 EXPECT_SIZE=2073600 字节，下载须校验完整性+重试

输出：data/weather_regions.json  —  各产区 近N日累计降水 / 去年同期 / 距平(mm+%) / 旱涝分级

基准：去年同期起步(用户要求)。后续补2006-2025历史后升级 SPI/分位数距平。

用法：
  cd ~/WILTW_KB/elnino
  /usr/bin/python3 fetch_weather.py                     # 近7日, 滞后5天(默认)
  /usr/bin/python3 fetch_weather.py --days 30           # 近30日
  /usr/bin/python3 fetch_weather.py --commodity 大豆    # 只算某品种
  /usr/bin/python3 fetch_weather.py --dry-run           # 只解析本地缓存不下载
"""
import json, os, sys, argparse, datetime, urllib.request
import concurrent.futures

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
REGIONS_PATH = os.path.join(BASE, "data", "production_regions.json")
OUT_PATH = os.path.join(BASE, "data", "weather_regions.json")
CACHE_DIR = os.path.join(BASE, "data", "cpc_cache")

CPC_URL = "https://ftp.cpc.ncep.noaa.gov/precip/CPC_UNI_PRCP/GAUGE_GLB/RT/{year}/PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.{ymd}.RT"

NCOLS, NROWS = 720, 360
UNDEF = -999.0
SCALE = 0.1  # 0.1mm/day -> mm/day
EXPECT_SIZE = NCOLS * NROWS * 2 * 4  # 2073600 bytes


# ---------- 网格索引 ----------
def lon_to_i(lon):
    """经度 -> 列索引。西经转 0-360。"""
    lon = lon % 360.0
    i = int(round((lon - 0.25) / 0.5))
    return max(0, min(NCOLS - 1, i))


def lat_to_j(lat):
    """纬度 -> 行索引。ydef=linear -89.75 0.5：j=0 是南纬-89.75，j=359 是北纬89.75。"""
    j = int(round((lat + 89.75) / 0.5))
    return max(0, min(NROWS - 1, j))


# ---------- 下载 ----------
def download_date(d, cache_dir=CACHE_DIR, retries=3):
    """下载某日降水文件到本地缓存（校验完整性+重试），返回缓存路径。"""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"prcp_{d.strftime('%Y%m%d')}.bin")
    if os.path.exists(path) and os.path.getsize(path) == EXPECT_SIZE:
        return path  # 已缓存且完整
    url = CPC_URL.format(year=d.year, ymd=d.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                data = r.read()
            if len(data) == EXPECT_SIZE:
                with open(path, "wb") as f:
                    f.write(data)
                return path
            print(f"  [retry {attempt+1}] {d} size={len(data)} != {EXPECT_SIZE}",
                  file=sys.stderr)
        except Exception as e:
            print(f"  [retry {attempt+1}] {d} {e}", file=sys.stderr)
    raise RuntimeError(f"{d} 下载失败(重试{retries}次)")


def download_many(dates, cache_dir=CACHE_DIR, max_workers=4):
    """并发下载缺失的文件（每个文件独立校验完整性+重试）。"""
    todo = []
    for d in dates:
        path = os.path.join(cache_dir, f"prcp_{d.strftime('%Y%m%d')}.bin")
        if not (os.path.exists(path) and os.path.getsize(path) == EXPECT_SIZE):
            todo.append(d)
    if not todo:
        return
    print(f"  并发下载 {len(todo)} 个文件 (max_workers={max_workers}) ...", file=sys.stderr)
    ok = fail = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(download_date, d, cache_dir, 3): d for d in todo}
        for fut in concurrent.futures.as_completed(futs):
            d = futs[fut]
            try:
                fut.result()
                ok += 1
            except Exception as e:
                fail += 1
                print(f"  ✗ {d}: {e}", file=sys.stderr)
    print(f"  并发下载完成: {ok} 成功, {fail} 失败", file=sys.stderr)


# ---------- 解析 ----------
def parse_cpc(path):
    """解析二进制 -> (rain[360,720] mm/day, gnum[360,720])。"""
    raw = np.fromfile(path, dtype="<f4")
    n = NCOLS * NROWS
    if raw.size < 2 * n:
        raise RuntimeError(f"{path} 文件不完整 size={raw.size}")
    rain = raw[:n].reshape(NROWS, NCOLS)
    gnum = raw[n:2 * n].reshape(NROWS, NCOLS)
    rain = np.where(rain == UNDEF, np.nan, rain) * SCALE
    return rain, gnum


# ---------- 裁剪 ----------
def clip_region(rain, region):
    """裁剪产区，返回 (平均降水mm/day, 有效格点数, 总格点数)。"""
    i0, i1 = lon_to_i(region["west"]), lon_to_i(region["east"])
    j0, j1 = lat_to_j(region["north"]), lat_to_j(region["south"])
    j_lo, j_hi = sorted([j0, j1])
    sub = rain[j_lo:j_hi + 1, i0:i1 + 1]
    valid = sub[~np.isnan(sub)]
    total = sub.size
    if valid.size == 0:
        return np.nan, 0, total
    return float(np.nanmean(valid)), int(valid.size), total


def load_regions():
    with open(REGIONS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["regions"]


# ---------- 旱涝信号 ----------
def drought_flood_signals(daily_mean_series, daily_max_series):
    """从日度序列提取旱涝信号（去年同期对比阶段起步版）。
    daily_mean_series: 升序 [(date_str, 产区平均mm/day)] 今年近N天
    daily_max_series:  升序 [(date_str, 产区单日最大格点mm/day)]
    """
    heavy_rain_days = sum(1 for _, v in daily_mean_series if v and v > 30)
    heavy_rain_grid_days = sum(1 for _, v in daily_max_series if v and v > 80)
    max_dry = cur = 0
    for _, v in daily_mean_series:
        if v is None or v < 1.0:
            cur += 1
            max_dry = max(max_dry, cur)
        else:
            cur = 0
    return {
        "heavy_rain_days": heavy_rain_days,
        "heavy_rain_grid_days": heavy_rain_grid_days,
        "max_dry_streak": max_dry,
    }


# ---------- 旱涝分级 ----------
def classify(anomaly_pct, heavy_rain_days, max_dry_streak):
    """近N日旱涝分级（去年同期对比起步版）。返回 (中文标签, level)。"""
    if heavy_rain_days >= 2:
        return "洪涝", "flood"
    if max_dry_streak >= 5 and (anomaly_pct is None or anomaly_pct <= -30):
        return "干旱", "drought"
    if anomaly_pct is not None:
        if anomaly_pct <= -50:
            return "偏干", "dry"
        if anomaly_pct >= 100:
            return "偏湿", "wet"
    return "正常", "normal"


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="累计窗口N天(默认7，周度)")
    ap.add_argument("--lag", type=int, default=5, help="最新可用日期滞后天数(默认5，南美站点数据完整)")
    ap.add_argument("--commodity", default=None, help="只算某品种(如 大豆)")
    ap.add_argument("--dry-run", action="store_true", help="只解析本地缓存不下载")
    ap.add_argument("--no-save", action="store_true", help="不写输出文件(调试)")
    args = ap.parse_args()

    today = datetime.date.today()
    regions = load_regions()
    if args.commodity:
        regions = [r for r in regions if r["commodity"] == args.commodity]

    # 滞后窗口：最新可用日期 = today - lag（南美站点约延迟3-6天，滞后5天基本完整）
    latest = today - datetime.timedelta(days=args.lag)
    dates_this = [latest - datetime.timedelta(days=k) for k in range(args.days)]
    dates_this.sort()  # 升序，便于算连续无雨
    dates_last = [d.replace(year=d.year - 1) for d in dates_this]

    os.makedirs(CACHE_DIR, exist_ok=True)

    def load_series(dates):
        out = {}
        for d in dates:
            try:
                path = CACHE_DIR + f"/prcp_{d.strftime('%Y%m%d')}.bin"
                if not os.path.exists(path) or os.path.getsize(path) != EXPECT_SIZE:
                    continue
                rain, gnum = parse_cpc(path)
                out[d.strftime("%Y-%m-%d")] = (rain, gnum)
            except Exception as e:
                print(f"  [warn] {d} 失败: {e}", file=sys.stderr)
        return out

    print(f"窗口: {dates_this[0]} ~ {dates_this[-1]} (滞后{args.lag}天) + 去年同期 ...")
    if not args.dry_run:
        download_many(dates_this + dates_last)
    series_this = load_series(dates_this)
    series_last = load_series(dates_last)

    result = {"meta": {
        "data_source": "NOAA CPC Unified Gauge (0.5deg daily)",
        "baseline": "去年同期",
        "unit": "mm",
        "days": args.days,
        "updated": today.strftime("%Y-%m-%d"),
        "window_start": dates_this[0].strftime("%Y-%m-%d"),
        "window_end": dates_this[-1].strftime("%Y-%m-%d"),
        "lag_days": args.lag,
        "this_days": len(series_this),
        "last_days": len(series_last),
    }, "regions": []}

    for r in regions:
        acc_this = acc_last = 0.0
        cnt_this = cnt_last = 0
        daily_mean = []   # 今年日度产区平均
        daily_max = []    # 今年日度产区单格点最大
        grid_total = valid_grid = 0
        for ds, (rain, gnum) in series_this.items():
            m, v, t = clip_region(rain, r)
            grid_total, valid_grid = t, v
            daily_mean.append((ds, m))
            i0, i1 = lon_to_i(r["west"]), lon_to_i(r["east"])
            j0, j1 = lat_to_j(r["north"]), lat_to_j(r["south"])
            j_lo, j_hi = sorted([j0, j1])
            sub = rain[j_lo:j_hi + 1, i0:i1 + 1]
            mx = float(np.nanmax(sub)) if np.any(~np.isnan(sub)) else None
            daily_max.append((ds, mx))
            if m == m:  # not nan
                acc_this += m; cnt_this += 1
        for ds, (rain, gnum) in series_last.items():
            m, v, t = clip_region(rain, r)
            if m == m:
                acc_last += m; cnt_last += 1

        daily_mean.sort()
        daily_max.sort()
        signals = drought_flood_signals(daily_mean, daily_max)

        # 距平：绝对差值 + 百分比(仅去年≥1mm时算，避免小分母爆炸)
        anomaly_mm = round(acc_this - acc_last, 1)
        pct = None
        if acc_last >= 1.0:
            pct = round((acc_this - acc_last) / acc_last * 100, 1)
        condition, level = classify(pct, signals["heavy_rain_days"], signals["max_dry_streak"])

        result["regions"].append({
            "id": r["id"], "commodity": r["commodity"], "country": r["country"],
            "state": r["state"], "name_zh": r["name_zh"], "rank": r["rank"],
            "center_lon": round((r["west"] + r["east"]) / 2, 2),
            "center_lat": round((r["north"] + r["south"]) / 2, 2),
            "days": args.days,
            "precip_this": round(acc_this, 1),
            "precip_last": round(acc_last, 1),
            "anomaly_mm": anomaly_mm,
            "anomaly_pct": pct,
            "condition": condition,
            "level": level,
            "valid_grid": valid_grid, "grid_total": grid_total,
            "heavy_rain_days": signals["heavy_rain_days"],
            "heavy_rain_grid_days": signals["heavy_rain_grid_days"],
            "max_dry_streak": signals["max_dry_streak"],
            "note": r.get("note", ""),
        })

    if not args.no_save:
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"已写入 {OUT_PATH}")

    # 打印汇总
    print("\n产区              | 品种 | 今年累计 | 去年同期 | 距平mm | 距平%  | 旱涝 | 暴雨天 | 最长无雨")
    for r in result["regions"]:
        p = f"{r['anomaly_pct']:+.1f}" if r["anomaly_pct"] is not None else "n/a"
        print(f"{r['name_zh']:<16} | {r['commodity']:<4} | {r['precip_this']:>6.1f} | {r['precip_last']:>7.1f} | {r['anomaly_mm']:>+6.1f} | {p:>6} | {r['condition']:<4} | {r['heavy_rain_days']:>5} | {r['max_dry_streak']:>5}")


if __name__ == "__main__":
    main()
