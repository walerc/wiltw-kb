#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
soil_awc_extract.py — 从 HWSD v2.0 提取 39 产区的土壤可用持水量 AWC(mm/m)

流程:
  1. 读 HWSD2.mdb → {SMU_ID: AWC_mm_per_m}
  2. 读 HWSD2.bil 栅格(全球1km, 21600×43200 uint16)，像素值=SMU_ID
  3. 对每个产区 bbox 切片，映射 AWC，取中位数(与降水口径一致)
  4. 输出 data/soil_awc.json

用法: /usr/bin/python3 soil_awc_extract.py
"""
import os, sys, json
import numpy as np
from access_parser import AccessParser

BASE = os.path.dirname(os.path.abspath(__file__))
MDB_PATH = "/tmp/hwsd/HWSD2.mdb"
BIL_PATH = "/tmp/hwsd/HWSD2.bil"
REGIONS_PATH = os.path.join(BASE, "data", "production_regions.json")
OUT_PATH = os.path.join(BASE, "data", "soil_awc.json")

# 栅格地理参数（来自 HWSD2.hdr）
ULXMAP = -179.995833333333
ULYMAP = 89.9958333333333
XDIM = 0.00833333333333333   # 1/120 度 ≈ 1km
YDIM = 0.00833333333333333
NROWS = 21600
NCOLS = 43200
NODATA = 65535

def lonlat_to_pix(lon, lat):
    """经纬度 → (col, row)。row 向下增。"""
    col = (lon - ULXMAP) / XDIM
    row = (ULYMAP - lat) / YDIM
    return col, row

def main():
    # 1. SMU → AWC 映射
    print("读取 HWSD2.mdb SMU 表 ...")
    db = AccessParser(MDB_PATH)
    smu = db.parse_table("HWSD2_SMU")
    smu_ids = smu["HWSD2_SMU_ID"]
    awc_vals = smu["AWC"]
    awc_map = {}
    for sid, awc in zip(smu_ids, awc_vals):
        if awc is not None:
            awc_map[int(sid)] = float(awc)
    print(f"  SMU→AWC 映射 {len(awc_map)} 条 (AWC范围 {min(awc_map.values()):.0f}~{max(awc_map.values()):.0f} mm/m)")

    # 2. 读栅格 (memmap 省内存)
    print("读取 HWSD2.bil 栅格 (1.87GB, memmap) ...")
    raster = np.memmap(BIL_PATH, dtype="<u2", mode="r", shape=(NROWS, NCOLS))

    # 3. 产区
    regions = json.load(open(REGIONS_PATH, encoding="utf-8"))["regions"]
    print(f"提取 {len(regions)} 产区 AWC ...")

    result = {"_meta": {
        "source": "HWSD v2.0 (FAO/IIASA)，栅格1km，AWC=Available Water Capacity mm/m",
        "method": "产区bbox内所有有效像素AWC取中位数(与降水口径一致)；排除NODATA海洋/水体",
        "note": "AWC单位mm/m；TAW=min(作物根深,土壤有效深)×AWC。AWC=0多为岩石/水体/城市。",
        "updated": "2026-09-21",
    }, "regions": {}}

    for r in regions:
        rid = r["id"]
        north, south = r["north"], r["south"]
        west, east = r["west"], r["east"]
        # 经纬度 → 像素范围（注意 row 向下，north 在上=row小）
        col_left, row_top = lonlat_to_pix(west, north)
        col_right, row_bottom = lonlat_to_pix(east, south)
        c0 = max(0, int(np.floor(col_left)))
        c1 = min(NCOLS - 1, int(np.ceil(col_right)))
        r0 = max(0, int(np.floor(row_top)))
        r1 = min(NROWS - 1, int(np.ceil(row_bottom)))
        if c1 < c0 or r1 < r0:
            print(f"  ⚠️ {rid} bbox 越界，跳过")
            continue

        block = np.array(raster[r0:r1 + 1, c0:c1 + 1]).ravel()
        # 排除 NODATA
        valid = block[block != NODATA]
        if len(valid) == 0:
            print(f"  ⚠️ {rid} 无有效像素(全海洋?)，跳过")
            continue

        # 映射 AWC
        awcs = np.array([awc_map.get(int(v), np.nan) for v in valid], dtype=float)
        awcs = awcs[~np.isnan(awcs)]
        if len(awcs) == 0:
            print(f"  ⚠️ {rid} 像素SMU无AWC映射，跳过")
            continue

        median_awc = float(np.median(awcs))
        mean_awc = float(np.mean(awcs))
        zero_frac = float(np.sum(awcs <= 1.0) / len(awcs))
        result["regions"][rid] = {
            "awc_mm_per_m": round(median_awc, 1),
            "awc_mean": round(mean_awc, 1),
            "awc_p25": round(float(np.percentile(awcs, 25)), 1),
            "awc_p75": round(float(np.percentile(awcs, 75)), 1),
            "n_pixels": int(len(awcs)),
            "zero_frac": round(zero_frac, 3),
        }
        print(f"  {rid:<20} AWC中位数={median_awc:6.1f} mm/m  均值={mean_awc:6.1f}  "
              f"像素={len(awcs):5d}  岩石/水体占比={zero_frac*100:4.1f}%")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n已写入 {OUT_PATH}（{len(result['regions'])} 产区）")

if __name__ == "__main__":
    main()
