#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_fire.py — 棕榈产区山火火点检测（NASA FIRMS VIIRS 实时火点）

数据源：NASA FIRMS（Fire Information for Resource Management System）
  VIIRS_SNPP_NRT：375m 分辨率实时火点，滞后约 3 小时，可回溯 5 天（NRT 上限）
  MODIS_NRT：1km 分辨率，Terra 退役后 Aqua 仍在

用法：
  cd ~/WILTW_KB/elnino && FIRMS_MAP_KEY=xxxx /usr/bin/python3 fetch_fire.py [--days 5]

MAP_KEY 获取：https://firms.modaps.eosdis.nasa.gov/api/map_key/ （免费，需 NASA Earthdata 账号）

输出：data/fire_regions.json —— 各棕榈产区近 N 天火点数 + 总火辐射功率(FRP)
"""
import json, os, sys, csv, io, urllib.request, datetime, argparse

BASE = os.path.dirname(os.path.abspath(__file__))


def _load_key():
    k = os.environ.get("FIRMS_MAP_KEY", "")
    if k:
        return k
    kf = os.path.expanduser("~/.hermes/firms_key.txt")
    if os.path.exists(kf):
        try:
            return open(kf).read().strip()
        except Exception:
            pass
    return ""


FIRMS_KEY = _load_key()
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/{bbox}/{days}"

# 覆盖全部 9 个棕榈产区的大框（west,south,east,north）
# 印尼苏门答腊(西97.5~东106) + 加里曼丹(西108.5~东119) + 马来半岛(西99.6~东104.3) + 沙巴(西109.5~东119.3)
ALL_BBOX = "97.5,-4.7,119.3,7.4"


def load_palm_regions():
    d = json.load(open(os.path.join(BASE, "data", "production_regions.json"), encoding="utf-8"))
    return [r for r in d["regions"] if r["commodity"] == "棕榈油"]


def fetch_firepoints(days=7):
    if not FIRMS_KEY:
        print("❌ 未设置 FIRMS_MAP_KEY，请先注册 https://firms.modaps.eosdis.nasa.gov/api/map_key/", file=sys.stderr)
        sys.exit(1)
    url = FIRMS_URL.format(key=FIRMS_KEY, bbox=ALL_BBOX, days=days)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        raw = r.read().decode()
    if "Invalid MAP_KEY" in raw or "fail" in raw.lower()[:200]:
        print(f"❌ FIRMS API 返回错误: {raw[:200]}", file=sys.stderr)
        sys.exit(1)
    rows = list(csv.DictReader(io.StringIO(raw)))
    return rows


def in_bbox(lat, lon, r):
    return r["south"] <= lat <= r["north"] and r["west"] <= lon <= r["east"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5, help="回溯天数(1-5, NRT上限)")
    args = ap.parse_args()
    days = max(1, min(args.days, 5))

    print(f"拉取 FIRMS VIIRS 近 {days} 天火点（覆盖棕榈产区大框）...")
    points = fetch_firepoints(days)
    print(f"  大框内共 {len(points)} 个火点")

    regions = load_palm_regions()
    result = {
        "generated": datetime.date.today().strftime("%Y-%m-%d"),
        "days": days,
        "source": "NASA FIRMS VIIRS_SNPP_NRT (375m)",
        "total_firepoints": len(points),
        "regions": [],
    }
    for r in regions:
        pts = [p for p in points if in_bbox(float(p["latitude"]), float(p["longitude"]), r)]
        frp_vals = [float(p["frp"]) for p in pts if p.get("frp")]
        # VIIRS confidence: h=high, n=nominal, l=low（高置信只统计 h）
        high = sum(1 for p in pts if p.get("confidence") in ("h", "H"))
        result["regions"].append({
            "id": r["id"], "name": r["name_zh"], "country": r["country"],
            "fire_count": len(pts),
            "high_conf": high,
            "total_frp": round(sum(frp_vals), 1),
            "peat_note": r.get("note", ""),
        })

    out = os.path.join(BASE, "data", "fire_regions.json")
    json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已保存 {out}\n")
    print("=== 各产区近 %d 天火点 ===" % days)
    for r in result["regions"]:
        flag = " 🔥🔥🔥" if r["fire_count"] >= 30 else (" 🔥" if r["fire_count"] >= 10 else "")
        print(f"  {r['name']}: {r['fire_count']} 火点 (高置信{r['high_conf']}) FRP={r['total_frp']}{flag}")


if __name__ == "__main__":
    main()
