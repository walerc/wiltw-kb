#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_fire.py — 全部农产品主产区山火火点检测（NASA FIRMS VIIRS 实时火点）

数据源：NASA FIRMS（Fire Information for Resource Management System）
  VIIRS_SNPP_NRT：375m 分辨率实时火点，滞后约 3 小时，可回溯 5 天（NRT 上限）

覆盖范围：全部 6 品种 39 产区（大豆/玉米/棉花/棕榈/橡胶/白糖），
  分 6 个大陆级框抓取（南美/北美/东南亚/南亚/中国新疆/中国东北），再按产区 bbox 归集。

火点语义（按品种）：
  棕榈/橡胶  → 泥炭土火灾（减产最致命传导）
  甘蔗       → 收获前焚烧（巴西/印度常见农事，非灾害）
  大豆/玉米/棉花 → 秸秆焚烧 / 野火（农事活动 / 局地火险）

用法：
  cd ~/WILTW_KB/elnino && FIRMS_MAP_KEY=xxxx /usr/bin/python3 fetch_fire.py [--days 5]

MAP_KEY 获取：https://firms.modaps.eosdis.nasa.gov/api/map_key/ （免费，需 NASA Earthdata 账号）

输出：data/fire_regions.json —— 各产区近 N 天火点数 + 总火辐射功率(FRP) + severity 分级
"""
import json, os, sys, csv, io, urllib.request, datetime, argparse, time

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

# 6 个大陆级抓取框（west,south,east,north），覆盖全部 39 个产区
FETCH_BBOXES = [
    ("南美",   "-66,-38,-43,-7"),          # 巴西+阿根廷(大豆/玉米/棉花/白糖)
    ("北美",   "-103.5,25.8,-87,46.5"),    # 美国(大豆/玉米/棉花)
    ("东南亚", "97.5,-4.7,119.3,18.5"),    # 印尼/马来/泰国(棕榈/橡胶)
    ("南亚",   "68.1,16,84.6,30.4"),       # 印度(棉花/甘蔗)
    ("中国新疆", "75,37,88,46.5"),         # 新疆(棉花)
    ("中国东北", "121.18,40.87,135.09,53.56"),  # 黑龙江/吉林(玉米)
]


def load_regions():
    d = json.load(open(os.path.join(BASE, "data", "production_regions.json"), encoding="utf-8"))
    return d["regions"]


def fire_level(count):
    """火点严重度分级（用于卡片/地图配色）"""
    if count >= 1000:
        return "严重", "fire_severe"
    if count >= 100:
        return "高", "fire_high"
    if count >= 10:
        return "中", "fire_mid"
    return "低", "fire_low"


def fetch_firepoints_bbox(bbox, days):
    """抓取单个 bbox 的近 N 天火点，返回 dict 列表"""
    url = FIRMS_URL.format(key=FIRMS_KEY, bbox=bbox, days=days)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        raw = r.read().decode()
    if "Invalid MAP_KEY" in raw or "fail" in raw.lower()[:200]:
        raise RuntimeError(f"FIRMS API 返回错误: {raw[:200]}")
    return list(csv.DictReader(io.StringIO(raw)))


def in_bbox(lat, lon, r):
    return r["south"] <= lat <= r["north"] and r["west"] <= lon <= r["east"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5, help="回溯天数(1-5, NRT上限)")
    args = ap.parse_args()
    days = max(1, min(args.days, 5))

    if not FIRMS_KEY:
        print("❌ 未设置 FIRMS_MAP_KEY，请先注册 https://firms.modaps.eosdis.nasa.gov/api/map_key/", file=sys.stderr)
        sys.exit(1)

    # === 逐框抓取 + 合并 ===
    all_points = []
    failed = []
    for name, bbox in FETCH_BBOXES:
        print(f"拉取 FIRMS 近 {days} 天火点 [{name}] bbox={bbox} ...", end=" ", flush=True)
        try:
            pts = fetch_firepoints_bbox(bbox, days)
            all_points.extend(pts)
            print(f"{len(pts)} 火点")
        except Exception as e:
            print(f"⚠️ 失败 {e}")
            failed.append(name)
        time.sleep(1.2)  # 避免 FIRMS 限流

    if failed:
        print(f"❌ 以下框抓取失败: {failed}，本次不生成数据（保留旧数据，避免不完整覆盖）", file=sys.stderr)
        sys.exit(1)

    print(f"合并后共 {len(all_points)} 个火点")

    regions = load_regions()
    result = {
        "generated": datetime.date.today().strftime("%Y-%m-%d"),
        "days": days,
        "source": "NASA FIRMS VIIRS_SNPP_NRT (375m)",
        "total_firepoints": len(all_points),
        "regions": [],
    }
    for r in regions:
        pts = [p for p in all_points if in_bbox(float(p["latitude"]), float(p["longitude"]), r)]
        frp_vals = [float(p["frp"]) for p in pts if p.get("frp")]
        # VIIRS confidence: h=high, n=nominal, l=low（高置信只统计 h）
        high = sum(1 for p in pts if p.get("confidence") in ("h", "H"))
        cond, level = fire_level(len(pts))
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
            "fire_count": len(pts),
            "high_conf": high,
            "total_frp": round(sum(frp_vals), 1),
            "note": r.get("note", ""),
            "condition": cond,
            "level": level,
        })

    out = os.path.join(BASE, "data", "fire_regions.json")
    json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已保存 {out}\n")

    # === 累积历史（供折线图 + 历史均值，FIRMS NRT 仅保留近7天，需自行累积）===
    hist_path = os.path.join(BASE, "data", "fire_history.csv")
    today = datetime.date.today().strftime("%Y-%m-%d")
    if os.path.exists(hist_path):
        lines = [l for l in open(hist_path, encoding="utf-8") if not l.startswith(today + ",")]
        with open(hist_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    else:
        with open(hist_path, "w", encoding="utf-8") as f:
            f.write("date,region_id,fire_count,high_conf,total_frp\n")
    with open(hist_path, "a", encoding="utf-8") as f:
        for r in result["regions"]:
            f.write(f"{today},{r['id']},{r['fire_count']},{r['high_conf']},{r['total_frp']}\n")
    print(f"已追加历史记录到 {hist_path}")

    print("=== 各产区近 %d 天火点（按火点数降序）===" % days)
    for r in sorted(result["regions"], key=lambda x: -x["fire_count"]):
        flag = " 🔥🔥🔥" if r["fire_count"] >= 1000 else (" 🔥" if r["fire_count"] >= 100 else "")
        print(f"  {r['commodity']}·{r['name']}: {r['fire_count']} 火点 (高置信{r['high_conf']}) FRP={r['total_frp']} [{r['condition']}]{flag}")


if __name__ == "__main__":
    main()
