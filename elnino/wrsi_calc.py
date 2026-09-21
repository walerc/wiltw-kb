#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wrsi_calc.py — 作物需水满足率 WRSI（FAO-56 土壤水分平衡法）

回答"天气+土壤 → 作物实际旱涝"：
  对每个产区每个生长季，做日步长土壤水分平衡：
    TAW   = AWC(mm/m) × 根深(m)                    ← 土壤可用持水量
    ETc   = Kc(day) × ET0(day)                      ← 作物需水
    Ks    = 水分胁迫系数(FAO-56 表22，p 比例)        ← 土壤水分限制
    ETa   = Ks × ETc                                ← 实际蒸散
    SW_t  = SW_{t-1} + P_eff - ETa (0≤SW≤TAW)       ← 根区土壤水
    WRSI  = 100 × ΣETa / ΣETc                       ← 需水满足率

  涝指标 = 生长季内土壤水分达到饱和(SW=TAW)的天数占比。

输出:
  data/wrsi_regions.json   当前生长季快照(39产区)
  data/wrsi_series.json    历史各生长季 WRSI 序列(折线图)

用法: cd ~/WILTW_KB/elnino && /usr/bin/python3 wrsi_calc.py
"""
import os, sys, csv, json, math, datetime, calendar
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
PRECIP_PATH = os.path.join(BASE, "data", "weather_history.csv")      # 日度降水 (CPC 2006-2026)
PET_PM_PATH = os.path.join(BASE, "data", "pet_history.csv")          # 月度 ET0 (CRU PM 1901-2025)
TEMP_2026_PATH = os.path.join(BASE, "data", "temp_daily_2026.csv")   # 2026 日度温度
CAL_PATH = os.path.join(BASE, "data", "hargreaves_calibration.json")
REGIONS_PATH = os.path.join(BASE, "data", "production_regions.json")
KC_PATH = os.path.join(BASE, "data", "crop_kc.json")
CALENDAR_PATH = os.path.join(BASE, "data", "crop_calendar.json")
SOIL_AWC_PATH = os.path.join(BASE, "data", "soil_awc.json")          # {rid: awc_mm_per_m}
OUT_PATH = os.path.join(BASE, "data", "wrsi_regions.json")
SERIES_OUT_PATH = os.path.join(BASE, "data", "wrsi_series.json")

# ---------- 参考蒸散 ET0 ----------
def extraterrestrial_radiation(lat, doy):
    phi = math.radians(lat)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    delta = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    Gsc = 0.0820
    Ra = (24 * 60 / math.pi) * Gsc * dr * (ws * math.sin(phi) * math.sin(delta)
                                            + math.cos(phi) * math.cos(delta) * math.sin(ws))
    return max(Ra, 0.0)

def hargreaves_pet_daily(tmax, tmin, lat, doy):
    tmean = (tmax + tmin) / 2.0
    Ra = extraterrestrial_radiation(lat, doy)
    return 0.0023 * Ra * (tmean + 17.8) * math.sqrt(max(tmax - tmin, 0.0))

def load_daily_et0(regions):
    """构造 {rid: {date(str): ET0_mm/day}}。历史 CRU PM 月度摊平，2026 Hargreaves×校正。"""
    # ① 历史月度 PM PET
    pm_monthly = defaultdict(dict)
    with open(PET_PM_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rid = row.get("region_id")
            if not rid:
                continue
            try:
                v = float(row["pet_mm"])
            except (ValueError, TypeError):
                continue
            pm_monthly[rid][(int(row["year"]), int(row["month"]))] = v

    cal = {}
    if os.path.exists(CAL_PATH):
        cal = json.load(open(CAL_PATH, encoding="utf-8")).get("regions", {})

    daily_et0 = defaultdict(dict)
    for rid in regions:
        lat = (regions[rid]["north"] + regions[rid]["south"]) / 2
        for (y, m), pet_mm in pm_monthly.get(rid, {}).items():
            if y < 2006:
                continue
            dim = calendar.monthrange(y, m)[1]
            daily_val = pet_mm / dim
            for d in range(1, dim + 1):
                daily_et0[rid][f"{y:04d}-{m:02d}-{d:02d}"] = daily_val

    temp_2026 = defaultdict(dict)
    with open(TEMP_2026_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rid = row.get("region_id")
            if not rid:
                continue
            try:
                tmax = float(row["tmax"]); tmin = float(row["tmin"])
            except (ValueError, TypeError):
                continue
            temp_2026[rid][row["date"]] = (tmax, tmin)

    for rid in regions:
        lat = (regions[rid]["north"] + regions[rid]["south"]) / 2
        ratio_rid = cal.get(rid, {})
        for date, (tmax, tmin) in temp_2026.get(rid, {}).items():
            y, m, d = (int(x) for x in date.split("-"))
            doy = datetime.date(y, m, d).timetuple().tm_yday
            pet_day = hargreaves_pet_daily(tmax, tmin, lat, doy)
            ratio = ratio_rid.get(str(m))
            if ratio:
                pet_day *= ratio
            daily_et0[rid][date] = pet_day
    return daily_et0

def load_daily_precip():
    daily = defaultdict(dict)
    with open(PRECIP_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rid = row.get("region_id")
            if not rid:
                continue
            try:
                v = float(row["precip_mm"])
            except (ValueError, TypeError):
                continue
            daily[rid][row["date"]] = v
    return daily

# ---------- Kc 曲线 ----------
def kc_curve(crop_params, cycle_days):
    """返回 list[kc per day]，长度 cycle_days。一年生按四阶段线性插值，多年生恒定。"""
    if crop_params.get("type") == "perennial":
        return [crop_params["kc_constant"]] * cycle_days
    kc_ini = crop_params["kc_ini"]
    kc_mid = crop_params["kc_mid"]
    kc_end = crop_params["kc_end"]
    frac = crop_params["stage_frac"]
    n = cycle_days
    # 阶段边界（天数）
    b0 = 0
    b1 = int(round(n * frac[0]))
    b2 = int(round(n * (frac[0] + frac[1])))
    b3 = int(round(n * (frac[0] + frac[1] + frac[2])))
    b4 = n
    kc = []
    for d in range(n):
        if d < b1:
            v = kc_ini
        elif d < b2:
            # 发育期：线性 kc_ini -> kc_mid
            v = kc_ini + (kc_mid - kc_ini) * (d - b1) / max(b2 - b1, 1)
        elif d < b3:
            v = kc_mid
        else:
            # 末期：线性 kc_mid -> kc_end
            v = kc_mid + (kc_end - kc_mid) * (d - b3) / max(b4 - b3, 1)
        kc.append(v)
    return kc

# ---------- 生长季生成 ----------
def season_dates(planting_month, planting_day, cycle_days, year):
    """返回 (start_date, end_date) 该种植年的生长季。"""
    start = datetime.date(year, planting_month, planting_day)
    end = start + datetime.timedelta(days=cycle_days - 1)
    return start, end

# ---------- 土壤水分平衡 ----------
def water_balance(daily_p, daily_et0, kc_curve, taw, p, start, end):
    """日步长土壤水分平衡，返回 (wsi, p_etc_ratio, sum_p, sum_etc, sum_eta, n_days)。

    wsi = 100×ΣETa/ΣETc（旱指标）；p_etc_ratio = ΣP/ΣETc（降水过剩度，涝参考）。
    数据不足返回 None。
    """
    raw = p * taw  # 易利用水
    sw = 0.5 * taw  # 初始土壤水 = 50% 田间持水量
    sum_etc = 0.0
    sum_eta = 0.0
    sum_p = 0.0
    n_days = 0
    d = start
    idx = 0
    while d <= end and idx < len(kc_curve):
        ds = d.isoformat()
        p_val = daily_p.get(ds, 0.0)
        et0_val = daily_et0.get(ds)
        kc = kc_curve[idx]
        if et0_val is None:
            et0_val = 0.0
        etc = kc * et0_val
        # 水分胁迫系数 Ks
        dr = taw - sw
        if dr <= raw:
            ks = 1.0
        elif dr < taw:
            ks = (taw - dr) / (taw - raw)
        else:
            ks = 0.0
        eta = ks * etc
        # 有效降水（简单法：直接入渗，超出 TAW 部分为径流）
        sw = sw + p_val - eta
        if sw > taw:
            sw = taw
        if sw < 0.0:
            sw = 0.0
        sum_p += p_val
        sum_etc += etc
        sum_eta += eta
        n_days += 1
        d += datetime.timedelta(days=1)
        idx += 1
    if n_days == 0 or sum_etc <= 0:
        return None
    wsi = 100.0 * sum_eta / sum_etc
    p_etc_ratio = sum_p / sum_etc
    return wsi, p_etc_ratio, sum_p, sum_etc, sum_eta, n_days

def wrsi_level(wsi, p_etc_ratio):
    """WRSI 分级（FAO 标准）+ 降水过剩判断。"""
    if wsi is None:
        return "数据不足", "na", False
    # 先判涝（降水显著过剩且无水分胁迫）
    if wsi >= 95 and p_etc_ratio >= 2.0:
        return "水分过剩", "waterlog", True
    if wsi >= 100:
        return "水分充足", "surplus", False
    if wsi >= 80:
        return "正常", "normal", False
    if wsi >= 60:
        return "轻度亏缺", "mild_drought", False
    if wsi >= 40:
        return "中度亏缺", "drought", False
    return "严重亏缺", "severe_drought", False

# ---------- 多年生作物：滚动窗口 WRSI ----------
def perennial_rolling(daily_p, daily_et0, kc_constant, taw, p, start, end, window_days=90):
    """多年生作物(棕榈/橡胶)：连续日步长土壤水分平衡 + 滚动 window_days 天 WRSI。

    多年生无固定生长季，用"滚动窗口"评估当前旱涝，捕捉拉尼娜↔厄尔尼诺的年内转变
    (年初湿润 vs 现在干旱，年度累计会掩盖)。返回 (latest_wsi, latest_p_etc,
    latest_date, monthly_labels, monthly_wsi, monthly_petc) 或 None。
    """
    from collections import deque
    raw = p * taw
    sw = 0.5 * taw
    etc_q = deque(); eta_q = deque(); p_q = deque()
    sum_etc = 0.0; sum_eta = 0.0; sum_p = 0.0
    rolling_wsi = {}; rolling_petc = {}
    d = start
    while d <= end:
        ds = d.isoformat()
        p_val = daily_p.get(ds, 0.0)
        et0_val = daily_et0.get(ds, 0.0)
        etc = kc_constant * et0_val
        dr = taw - sw
        if dr <= raw:
            ks = 1.0
        elif dr < taw:
            ks = (taw - dr) / (taw - raw)
        else:
            ks = 0.0
        eta = ks * etc
        sw = sw + p_val - eta
        if sw > taw:
            sw = taw
        if sw < 0.0:
            sw = 0.0
        etc_q.append(etc); eta_q.append(eta); p_q.append(p_val)
        sum_etc += etc; sum_eta += eta; sum_p += p_val
        if len(etc_q) > window_days:
            sum_etc -= etc_q.popleft()
            sum_eta -= eta_q.popleft()
            sum_p -= p_q.popleft()
        if len(etc_q) == window_days and sum_etc > 0:
            rolling_wsi[ds] = 100.0 * sum_eta / sum_etc
            rolling_petc[ds] = sum_p / sum_etc
        d += datetime.timedelta(days=1)
    if not rolling_wsi:
        return None
    latest_date = max(rolling_wsi.keys())
    latest_wsi = rolling_wsi[latest_date]
    latest_petc = rolling_petc[latest_date]
    # 月度序列（取每月最后一天的滚动值）
    monthly = {}
    for ds in sorted(rolling_wsi.keys()):
        y, m, _ = (int(x) for x in ds.split("-"))
        monthly[f"{y:04d}-{m:02d}"] = (rolling_wsi[ds], rolling_petc[ds])
    monthly_labels = sorted(monthly.keys())
    monthly_wsi = [round(monthly[l][0], 1) for l in monthly_labels]
    monthly_petc = [round(monthly[l][1], 2) for l in monthly_labels]
    return latest_wsi, latest_petc, latest_date, monthly_labels, monthly_wsi, monthly_petc


def main():
    regions = {r["id"]: r for r in json.load(
        open(REGIONS_PATH, encoding="utf-8"))["regions"]}
    kc_data = json.load(open(KC_PATH, encoding="utf-8"))["crops"]
    calendar = json.load(open(CALENDAR_PATH, encoding="utf-8"))["regions"]
    soil_awc_raw = json.load(open(SOIL_AWC_PATH, encoding="utf-8"))["regions"]

    print("加载日度降水 + ET0 ...")
    precip_daily = load_daily_precip()
    et0_daily = load_daily_et0(regions)

    # 数据日期范围
    all_dates = set()
    for rid in precip_daily:
        all_dates |= set(precip_daily[rid].keys())
    min_date = min(all_dates)
    max_date = max(all_dates)
    today = datetime.date.fromisoformat(max_date)

    result = {"meta": {
        "indicator": "WRSI(作物需水满足率, FAO-56 土壤水分平衡)",
        "data_source": "CPC降水 + CRU PM PET(历史) + CPC温度Hargreaves(2026) + HWSD土壤AWC",
        "formula": "WRSI=100×ΣETa/ΣETc; ETc=Kc×ET0; ETa=Ks×ETc; TAW=AWC×根深",
        "soil_source": "HWSD v2.0 AWC(mm/m)",
        "initial_sw": "0.5×TAW(统一初始条件，保证年份间可比)",
        "note": "涝参考=降水过剩度P/ETc≥2.0且无水分胁迫；灌溉区WRSI偏保守(未计入灌溉补充)。",
        "data_range": f"{min_date} ~ {max_date}",
        "updated": today.strftime("%Y-%m-%d"),
    }, "regions": []}

    series_result = {"meta": {
        "indicator": "WRSI(生长季)",
        "seasons": [],
        "updated": today.strftime("%Y-%m-%d"),
    }, "series": {}}

    # 收集所有生长季标签（种植年 2006..2026）
    year_start = 2006
    year_end = today.year
    season_labels = [str(y) for y in range(year_start, year_end + 1)]
    series_result["meta"]["seasons"] = season_labels

    for rid, r in regions.items():
        if rid not in precip_daily or rid not in et0_daily:
            continue
        if rid not in calendar:
            print(f"  ⚠️ {rid} 缺物候日历，跳过")
            continue
        if rid not in soil_awc_raw:
            print(f"  ⚠️ {rid} 缺土壤AWC，跳过")
            continue
        cal = calendar[rid]
        crop = cal["crop"]
        if crop not in kc_data:
            print(f"  ⚠️ {rid} 未知作物 {crop}，跳过")
            continue
        cp = kc_data[crop]
        awc = soil_awc_raw[rid]["awc_mm_per_m"]
        taw = awc * cp["root_depth_m"]  # mm/m × m = mm
        p = cp["p"]
        is_perennial = cp.get("type") == "perennial"
        global_share = r.get("global_share")
        rank = r.get("rank")

        if is_perennial:
            # 多年生(棕榈/橡胶)：滚动 90 天窗口，捕捉拉尼娜↔厄尔尼诺年内转变
            pr = perennial_rolling(
                precip_daily[rid], et0_daily[rid], cp["kc_constant"],
                taw, p,
                datetime.date.fromisoformat(min_date), today)
            if pr is None:
                continue
            cur_wsi, cur_p_etc, latest_date, monthly_labels, monthly_wsi, monthly_petc = pr
            cond, lv, _ = wrsi_level(cur_wsi, cur_p_etc)
            out = {
                "id": rid, "commodity": r["commodity"], "country": r["country"],
                "state": r["state"], "name_zh": r["name_zh"],
                "global_share": global_share, "rank": rank,
                "center_lon": round((r["west"] + r["east"]) / 2, 2),
                "center_lat": round((r["north"] + r["south"]) / 2, 2),
                "crop": crop,
                "season": f"最近90天(截至{latest_date})",
                "season_ongoing": True,
                "season_days": 90,
                "early_season": False,
                "irrigated": bool(cal.get("irrigated", False)),
                "awc_mm_per_m": round(awc, 1),
                "taw_mm": round(taw, 0),
                "wsi": round(cur_wsi, 1),
                "p_etc_ratio": round(cur_p_etc, 2),
                "condition": cond,
                "level": lv,
                "n_seasons": len(monthly_labels),
                "perennial": True,
            }
            result["regions"].append(out)
            series_result["series"][rid] = {
                "type": "perennial",
                "labels": monthly_labels,
                "wsi": monthly_wsi,
                "p_etc_ratio": monthly_petc,
            }
            continue

        # 一年生：生长季累计
        cycle = cal["cycle_days"]
        kc = kc_curve(cp, cycle)

        # 逐年计算 WRSI
        yearly = {}  # year -> (wsi, p_etc_ratio)
        for y in range(year_start, year_end + 1):
            start, end = season_dates(cal["planting_month"], cal["planting_day"], cycle, y)
            if end < datetime.date.fromisoformat(min_date):
                continue
            if start > today:
                continue
            # 裁剪到数据范围内
            s = max(start, datetime.date.fromisoformat(min_date))
            e = min(end, today)
            if e < s:
                continue
            # 用全生长季的 kc_curve，但从 s 开始对应 idx
            offset = (s - start).days
            sub_kc = kc[offset:offset + (e - s).days + 1]
            wb = water_balance(precip_daily[rid], et0_daily[rid], sub_kc, taw, p, s, e)
            if wb is None:
                continue
            wsi, p_etc_ratio, _, _, _, _ = wb
            yearly[y] = (wsi, p_etc_ratio)

        if not yearly:
            continue

        # 当前生长季 = 最新的种植年
        cur_year = max(yearly.keys())
        cur_wsi, cur_p_etc = yearly[cur_year]
        cur_start, cur_end = season_dates(cal["planting_month"], cal["planting_day"], cycle, cur_year)
        is_ongoing = cur_end > today
        # 生长季已进行天数
        season_days = (today - cur_start).days + 1 if cur_start <= today else 0
        if season_days < 0:
            season_days = 0
        early_season = is_ongoing and season_days < 30
        irrigated = bool(cal.get("irrigated", False))

        cond, lv, _ = wrsi_level(cur_wsi, cur_p_etc)
        if early_season:
            cond = "生长季初期"
            lv = "early_season"
        out = {
            "id": rid, "commodity": r["commodity"], "country": r["country"],
            "state": r["state"], "name_zh": r["name_zh"],
            "global_share": global_share, "rank": rank,
            "center_lon": round((r["west"] + r["east"]) / 2, 2),
            "center_lat": round((r["north"] + r["south"]) / 2, 2),
            "crop": crop,
            "season": f"{cur_year}({cur_start.month:02d}-{cur_start.day:02d}~{cur_end.month:02d}-{cur_end.day:02d})",
            "season_ongoing": is_ongoing,
            "season_days": season_days,
            "early_season": early_season,
            "irrigated": irrigated,
            "awc_mm_per_m": round(awc, 1),
            "taw_mm": round(taw, 0),
            "wsi": round(cur_wsi, 1),
            "p_etc_ratio": round(cur_p_etc, 2),
            "condition": cond,
            "level": lv,
            "n_seasons": len(yearly),
            "perennial": False,
        }
        result["regions"].append(out)

        # 时间序列（对齐 season_labels）
        series_result["series"][rid] = {
            "type": "annual",
            "labels": season_labels,
            "wsi": [round(yearly[y][0], 1) if y in yearly else None for y in range(year_start, year_end + 1)],
            "p_etc_ratio": [round(yearly[y][1], 2) if y in yearly else None for y in range(year_start, year_end + 1)],
        }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(SERIES_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(series_result, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n已写入 {OUT_PATH}（{len(result['regions'])} 产区）")
    print(f"已写入 {SERIES_OUT_PATH}（生长季 {len(season_labels)} 年）")

    print(f"\n产区              | 品种 | AWC | WRSI | P/ETc | 天数 | 墒情")
    for r in result["regions"]:
        irr = "🚰" if r.get("irrigated") else "  "
        print(f"{r['name_zh']:<16} | {r['commodity']:<4} | {r['awc_mm_per_m']:>4.0f} | "
              f"{r['wsi']:>5.1f} | {r['p_etc_ratio']:>5.2f} | {r['season_days']:>4d} | "
              f"{irr}{r['condition']}{'⏳' if r['season_ongoing'] else ''}")

if __name__ == "__main__":
    main()
