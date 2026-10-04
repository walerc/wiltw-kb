#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fire_prod_corr.py — 火点 → 棕榈产量 关联分析框架

验证假设：火点(火灾物理破坏) 是否是棕榈减产的独立信号，
        还是仅仅"水分(SPI/SPEI)"的冗余代理（两者都受降水驱动）。

分析层次：
  ① 火点 ↔ 产量 相关系数（Pearson，含 0/1/2/3 月滞后）
  ② 火点 → 产量 滞后回归（Ridge，复用 analysis_palm_reg 框架）
  ③ 控制水分(SPI)后的偏相关 —— 火点的「独立」解释力
  ④ 参照 baseline：水分→产量 R²、厄尔尼诺事件→产量（已有结论）

数据：
  火点  data/fire_history.csv        （累积式，样本随时间增长）
  产量  data/palm_prod_monthly.json  （马来 2016+）
  水分  data/spi_weekly_series.json  （2006+，周度→月度）

用法：cd ~/WILTW_KB/elnino && /usr/bin/python3 fire_prod_corr.py
"""
import json, csv, os
import numpy as np
from datetime import date
from scipy import stats

BASE = os.path.dirname(os.path.abspath(__file__))


# ---------- 数据加载 ----------
def load_fire_monthly():
    """fire_history.csv → {month: 各产区火点加权和}（用 global_share 加权）"""
    pr = json.load(open(f"{BASE}/data/production_regions.json", encoding="utf-8"))
    palm = [r for r in pr["regions"] if r["commodity"] == "棕榈油"]
    w = {r["id"]: r.get("global_share", 0) for r in palm}
    wsum = sum(w.values()) or 1.0
    hist = f"{BASE}/data/fire_history.csv"
    if not os.path.exists(hist):
        return {}
    month = {}
    with open(hist, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rid = row["region_id"]
            if rid not in w:
                continue
            m = row["date"][:7]
            try:
                v = float(row["fire_count"])
            except (ValueError, TypeError):
                continue
            month[m] = month.get(m, 0.0) + w[rid] * v
    return {m: round(v / wsum, 1) for m, v in month.items()}


def load_prod_yoy():
    """马来月度产量 → YoY（同比）"""
    prod = json.load(open(f"{BASE}/data/palm_prod_monthly.json", encoding="utf-8"))
    my = {k[:7]: v for k, v in dict(prod["MY"]).items()}
    months = sorted(my)
    yoy = {}
    for m in months:
        y, mo = int(m[:4]), int(m[5:7])
        prev = f"{y-1:04d}-{mo:02d}"
        if prev in my and my[prev] > 0:
            yoy[m] = my[m] / my[prev] - 1.0
    return yoy


def load_spi_monthly(scale="spi4w"):
    """周度 SPI → 月度（每月取末周值），按马来产区 global_share 加权"""
    spi = json.load(open(f"{BASE}/data/spi_weekly_series.json", encoding="utf-8"))
    weeks = spi["meta"]["weeks"]
    pr = json.load(open(f"{BASE}/data/production_regions.json", encoding="utf-8"))
    palm = [r for r in pr["regions"] if r["commodity"] == "棕榈油" and r["country"] == "马来西亚"]
    w = {r["id"]: r.get("global_share", 0) for r in palm}
    wsum = sum(w.values()) or 1.0
    per = {}
    for rid in w:
        vals = spi["series"][rid][scale]
        mm = {}
        for wk, v in zip(weeks, vals):
            if v is None:
                continue
            y, wn = wk.split("-W")
            d = date.fromisocalendar(int(y), int(wn), 7)
            mm[f"{d.year:04d}-{d.month:02d}"] = v
        per[rid] = mm
    allm = set()
    for mm in per.values():
        allm |= set(mm)
    return {m: sum(w[r] * per[r].get(m, 0.0) for r in w) / wsum for m in allm}


# ---------- 工具 ----------
def shift_month(m, k):
    y, mo = int(m[:4]), int(m[5:7])
    idx = m
    for _ in range(abs(k)):
        y2, mo2 = int(idx[:4]), int(idx[5:7])
        mo2 = mo2 - 1 if k > 0 else mo2 + 1
        if mo2 == 0:
            mo2, y2 = 12, y2 - 1
        if mo2 == 13:
            mo2, y2 = 1, y2 + 1
        idx = f"{y2:04d}-{mo2:02d}"
    return idx


def pearson_r(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = ~(np.isnan(x) | np.isnan(y))
    if mask.sum() < 5:
        return None, mask.sum()
    r, p = stats.pearsonr(x[mask], y[mask])
    return r, mask.sum()


def ridge_r2(X, y, lam=10.0):
    n, p = X.shape
    Xc = X - X.mean(0)
    yc = y - y.mean()
    try:
        beta = np.linalg.solve(Xc.T @ Xc + lam * np.eye(p), Xc.T @ yc)
    except np.linalg.LinAlgError:
        return None
    yhat = Xc @ beta + y.mean()
    ss_res = ((y - yhat) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    return 1 - ss_res / ss_tot if ss_tot > 0 else None


def partial_corr(y, x1, x2):
    """y 与 x1 的偏相关（控制 x2）"""
    y, x1, x2 = np.asarray(y, float), np.asarray(x1, float), np.asarray(x2, float)
    mask = ~(np.isnan(y) | np.isnan(x1) | np.isnan(x2))
    if mask.sum() < 8:
        return None, mask.sum()
    y, x1, x2 = y[mask], x1[mask], x2[mask]
    # 残差化：y ~ x2, x1 ~ x2
    ry = y - np.polyval(np.polyfit(x2, y, 1), x2)
    rx = x1 - np.polyval(np.polyfit(x2, x1, 1), x2)
    r, p = stats.pearsonr(ry, rx)
    return r, mask.sum()


# ---------- 主流程 ----------
def main():
    fire = load_fire_monthly()
    yoy = load_prod_yoy()
    spi = load_spi_monthly("spi4w")

    print("=" * 70)
    print("火点 → 棕榈产量 关联分析（马来）")
    print("=" * 70)

    # ---- baseline：水分 → 产量 ----
    print("\n【Baseline】水分(SPI4w) → 产量YoY")
    months = sorted(set(yoy) & set(spi))
    xs, ys = [], []
    for m in months:
        xs.append(spi[m])
        ys.append(yoy[m])
    if len(xs) >= 10:
        r, n = pearson_r(xs, ys)
        print(f"  SPI↔产量同期相关: r={r:+.3f} (n={n})")
        for lag in [1, 2, 3, 6, 12]:
            xs_l, ys_l = [], []
            for m in months:
                idx = shift_month(m, lag)
                if idx in spi:
                    xs_l.append(spi[idx])
                    ys_l.append(yoy[m])
            if len(xs_l) >= 10:
                rl, nl = pearson_r(xs_l, ys_l)
                print(f"  SPI lag{-lag}↔产量: r={rl:+.3f} (n={nl})")

    # ---- ① 火点 ↔ 产量 相关 ----
    print("\n【① 火点 ↔ 产量 相关】")
    if len(fire) < 2:
        print(f"  ⚠️ 火点历史样本不足（当前 {len(fire)} 个月），需累积/下载历史数据")
        print("  火点关联分析框架已就位，待 fire_history.csv 积累后自动跑出结果")
    else:
        fm = sorted(set(fire) & set(yoy))
        xs, ys = [fire[m] for m in fm], [yoy[m] for m in fm]
        r, n = pearson_r(xs, ys)
        print(f"  火点↔产量同期: r={r:+.3f} (n={n})")
        for lag in [1, 2, 3]:
            xs_l, ys_l = [], []
            for m in fm:
                idx = shift_month(m, lag)
                if idx in fire:
                    xs_l.append(fire[idx])
                    ys_l.append(yoy[m])
            if len(xs_l) >= 5:
                rl, nl = pearson_r(xs_l, ys_l)
                print(f"  火点 lag{-lag}↔产量: r={rl:+.3f} (n={nl})")

    # ---- ② 火点 → 产量 滞后回归 ----
    print("\n【② 火点 → 产量 滞后回归(Ridge)】")
    if len(fire) < 12:
        print(f"  ⚠️ 火点样本不足，无法回归（需 ≥12 个月，当前 {len(fire)}）")
    else:
        lags = list(range(0, 7))
        X, y = [], []
        for m in sorted(set(yoy) & set(fire)):
            row = []
            ok = True
            for lag in lags:
                idx = shift_month(m, lag)
                if idx in fire:
                    row.append(fire[idx])
                else:
                    ok = False
                    break
            if ok:
                X.append(row)
                y.append(yoy[m])
        if len(y) >= 20:
            r2 = ridge_r2(np.array(X), np.array(y))
            print(f"  火点 lag0-6 → 产量: R²={r2:.3f} (n={len(y)})")

    # ---- ③ 控制水分后的偏相关 ----
    print("\n【③ 控制水分(SPI)后 火点的独立解释力】")
    if len(fire) < 8:
        print(f"  ⚠️ 火点样本不足，无法做偏相关（需 ≥8 个月，当前 {len(fire)}）")
    else:
        common = sorted(set(fire) & set(yoy) & set(spi))
        xs_f, xs_s, ys = [], [], []
        for m in common:
            xs_f.append(fire[m])
            xs_s.append(spi[m])
            ys.append(yoy[m])
        if len(ys) >= 8:
            rc, n = partial_corr(ys, xs_f, xs_s)
            print(f"  产量 ~ 火点（控制SPI）偏相关: r={rc:+.3f} (n={n})")
            print("  解读：|r| 显著 > 0 → 火点有独立于水分的解释力；≈0 → 火点只是水分冗余代理")

    print("\n" + "=" * 70)
    print("已有 baseline 结论（来自 analysis_palm_reg / event_study）：")
    print("  · 水分(SPI全滞后) → 产量YoY: R²≈0.32（短期仅0.12），弱关联")
    print("  · 厄尔尼诺事件后 1-2 年产量不降反升(+14.8%)，3年后才-4.4%")
    print("  → 棕榈生物周期(性别分化~24月滞后)会掩盖火灾的即时破坏效应")
    print("=" * 70)


if __name__ == "__main__":
    main()
