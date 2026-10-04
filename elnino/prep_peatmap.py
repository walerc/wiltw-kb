#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prep_peatmap.py — 从 PEATMAP 东南亚泥炭 shapefile 提取产区泥炭多边形，存轻量 JSON

PEATMAP (Xu et al. 2017) 全球泥炭分布。Asia 部分的 SEA_Peatland.shp 是东南亚泥炭，
坐标为 EPSG:4087（World Equidistant Cylindrical，米制），需转回经纬度。

本脚本：
  1. 投影转换（米 → 经纬度）
  2. 按 parts 拆分成多个多边形
  3. 只保留东南亚产区 bbox 内的多边形
  4. 简化后存 JSON，供 fetch_fire.py 做 point-in-polygon

用法：
  1. 下载 Asia.zip: https://archive.researchdata.leeds.ac.uk/251/5/Asia.zip
  2. 解压到 /tmp/peatmap_asia/
  3. cd ~/WILTW_KB/elnino && /usr/bin/python3 prep_peatmap.py

输出：data/peat_polygons.json
依赖：pyshp
"""
import shapefile, json, os, math

BASE = os.path.dirname(os.path.abspath(__file__))
SHP = "/tmp/peatmap_asia/Asia/SEA_Peatland.shp"
# 东南亚产区 bbox（印尼/马来/泰国南部棕榈+橡胶核心区）
SEA = {"west": 95, "east": 120, "south": -5, "north": 11}
# EPSG:4087 等距圆柱投影：米 → 度
R = 6378137.0
DEG = R * math.pi / 180.0  # ≈ 111319.49 米/度


def proj_to_ll(x, y):
    return round(x / DEG, 5), round(y / DEG, 5)


def main():
    if not os.path.exists(SHP):
        print(f"❌ 未找到 shapefile: {SHP}，请先下载并解压 Asia.zip")
        return
    sf = shapefile.Reader(SHP)
    s = sf.shapes()[0]
    points = s.points
    parts = list(s.parts) + [len(points)]

    polys = []
    n_skipped = 0
    n_bad = 0
    for i in range(len(parts) - 1):
        seg = points[parts[i]:parts[i + 1]]
        if len(seg) < 4:
            n_bad += 1
            continue
        ll = [proj_to_ll(x, y) for x, y in seg]
        minx = min(p[0] for p in ll)
        maxx = max(p[0] for p in ll)
        miny = min(p[1] for p in ll)
        maxy = max(p[1] for p in ll)
        if maxx < SEA["west"] or minx > SEA["east"] or maxy < SEA["south"] or miny > SEA["north"]:
            n_skipped += 1
            continue
        # 简化：每 N 点取 1（保留首尾）
        step = max(1, len(ll) // 50)
        simp = ll[::step]
        if simp[-1] != ll[-1]:
            simp.append(ll[-1])
        polys.append({"poly": simp})

    out = os.path.join(BASE, "data", "peat_polygons.json")
    json.dump({"source": "PEATMAP (Xu et al. 2017) SEA_Peatland", "bbox": SEA, "polys": polys},
              open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"✅ 提取 {len(polys)} 个东南亚泥炭多边形（跳过 {n_skipped} 个 bbox 外，{n_bad} 个点不足）→ {out}")


if __name__ == "__main__":
    main()
