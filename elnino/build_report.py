#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
厄尔尼诺研究 — 完整报告生成器
动态读取 elnino_data.json，生成打印友好的完整 HTML 报告（概览/结论/事件池/价格/产量/种植知识）。
随后用 Chrome headless 转 PDF。
用法:
  python3 build_report.py            # 生成 report.html
  python3 build_report.py --pdf      # 生成 report.html 并转 report.pdf
"""
import json, os, html, subprocess, sys, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE, "data", "elnino_data.json")
OUT_HTML = os.path.join(BASE, "report.html")
OUT_PDF = os.path.join(BASE, "report.pdf")

PRICE_WINDOWS = ["pre", "peak_w", "post0_6", "post6_12", "post12_24"]
PRICE_WL = {"pre": "启动→峰值前", "peak_w": "峰值±1月", "post0_6": "峰值后0-6月",
            "post6_12": "峰值后6-12月", "post12_24": "峰值后12-24月"}


def esc(s):
    return html.escape(str(s))


def fmt_pct(v):
    if v is None or (isinstance(v, float) and v != v):
        return '<span class="na">—</span>'
    cls = "pos" if v >= 0 else "neg"
    sign = "+" if v >= 0 else ""
    return f'<span class="{cls}">{sign}{v:.1f}%</span>'


def heat_table(agg, windows, labels, title=None):
    codes = list(agg.keys())
    h = ['<table class="heat">', "<tr><th>品种</th>"]
    for w in windows:
        h.append(f"<th>{labels[w]}</th>")
    h.append("</tr>")
    for c in codes:
        h.append(f"<tr><td class=\"rowh\">{esc(agg[c]['name'])}</td>")
        for w in windows:
            h.append(f"<td>{fmt_pct(agg[c].get(w))}</td>")
        h.append("</tr>")
    h.append("</table>")
    return "".join(h)


def detail_tables(results, commodities, windows, labels):
    codes = list(commodities.keys())
    h = []
    for c in codes:
        rows = [r for r in results if r["commodity"] == c]
        if not rows:
            continue
        h.append(f"<h4>{esc(commodities[c])}</h4>")
        h.append('<table><tr><th>事件</th><th>强度</th>')
        for w in windows:
            h.append(f"<th>{labels[w]}</th>")
        h.append("</tr>")
        for r in rows:
            h.append(f"<tr><td>{esc(r['event'])}</td><td><span class=\"g g-{esc(r['grade'])}\">{esc(r['grade'])}</span></td>")
            for w in windows:
                h.append(f"<td>{fmt_pct(r.get(w))}</td>")
            h.append("</tr>")
        h.append("</table>")
    return "".join(h)


def events_table(events):
    h = ['<table><tr><th>事件</th><th>ONI起止</th><th>峰值月</th><th>峰值ONI</th><th>强度</th><th>备注</th></tr>']
    for e in events:
        h.append(f"<tr><td>{esc(e['id'])}</td><td>{esc(e['start'])} ~ {esc(e['end'])}</td><td>{esc(e['peak'])}</td>"
                 f"<td>+{e['oni']}</td><td><span class=\"g g-{esc(e['grade'])}\">{esc(e['grade'])}</span></td>"
                 f"<td class=\"l\">{esc(e['note'])}</td></tr>")
    h.append("</table>")
    return "".join(h)


def agronomy_cards(ag):
    emoji = {"P": "🌴", "RU": "🌳", "SR": "🍬", "SB": "🫘", "CT": "🧵"}
    h = []
    for c, o in ag["commodities"].items():
        h.append(f'<div class="agri-card">')
        h.append(f'<h3>{emoji.get(c,"")} {esc(o["name"])} <span class="sub">（{esc(o["crop"])} · {esc(o["type"])}）</span></h3>')
        h.append(f'<p class="cycle"><b>生长周期：</b>{esc(o["cycle"])}</p>')
        h.append('<table><tr><th>阶段</th><th>时期</th><th>需水</th><th>需肥</th><th>关键</th><th>不可逆影响</th></tr>')
        for s in o["stages"]:
            cls = ' class="keyrow"' if s["key"] else ''
            keytd = '<span class="keytag">关键</span>' if s["key"] else ''
            h.append(f'<tr{cls}><td>{esc(s["stage"])}</td><td>{esc(s["timing"])}</td>'
                     f'<td class="l">{esc(s["water"])}</td><td class="l">{esc(s["fert"])}</td>'
                     f'<td>{keytd}</td>'
                     f'<td class="l">{esc(s["irrev"])}</td></tr>')
        h.append("</table>")
        h.append(f'<div class="crit">🎯 <b>关键阶段：</b>{esc(o["critical"])}</div>')
        h.append(f'<div class="irrev"><b>⚠️ 不可逆损伤 / 益处：</b><ul>{"".join("<li>"+esc(x)+"</li>" for x in o["irreversible"])}</ul></div>')
        h.append(f'<div class="elnino">🌊 <b>厄尔尼诺传导：</b>{esc(o["el_nino"])}</div>')
        # 产区细分
        regs = o.get("regions", [])
        if regs:
            h.append('<div class="region-title">📍 产区细分（气候 · 位置 · 土壤）</div>')
            for r in regs:
                h.append(f'<div class="region-card">'
                         f'<div class="region-head">{esc(r["name"])}<span class="region-rank">{esc(r["rank"])}</span></div>'
                         f'<div class="region-row"><span class="rk">位置</span>{esc(r["location"])}</div>'
                         f'<div class="region-row"><span class="rk">气候</span>{esc(r["climate"])}</div>'
                         f'<div class="region-row"><span class="rk">土壤</span>{esc(r["soil"])}</div>'
                         f'<div class="region-row en"><span class="rk">厄尔尼诺</span>{esc(r["elnino"])}</div>'
                         f'</div>')
        h.append(f'<p class="link">🔗 {esc(o["link"])}</p></div>')
    return "".join(h)


def usd_section(usd, price):
    if not usd:
        return ""
    h = ['<h3>💵 美元汇率因素（剔除美元估值效应）</h3>']
    h.append(f'<div class="note">{esc(usd["method"])}<br><b>说明：</b>{esc(usd["note"])}</div>')
    # 美元指数窗口涨幅表
    h.append('<h4>美元指数(REER)各事件窗口涨跌幅（%）</h4>')
    h.append('<table class="heat"><tr><th>事件</th>')
    for w in PRICE_WINDOWS:
        h.append(f'<th>{PRICE_WL[w]}</th>')
    h.append('</tr>')
    for eid, wchg in usd["windows_by_event"].items():
        h.append(f'<tr><td class="rowh">{esc(eid)}</td>')
        for w in PRICE_WINDOWS:
            v = wchg.get(w)
            if v is None:
                h.append('<td class="na">—</td>')
            else:
                cls = "pos" if v >= 0 else "neg"
                h.append(f'<td class="{cls}">{v:+.1f}%</td>')
        h.append('</tr>')
    h.append('</table>')
    # 剔除后聚合表
    h.append('<h4>剔除汇率后 vs 原始名义（跨事件均值，%）</h4>')
    agg = usd["agg_adjusted"]
    orig = price["agg_by_commodity"]
    h.append('<table class="heat"><tr><th>品种</th>')
    for w in PRICE_WINDOWS:
        h.append(f'<th>{PRICE_WL[w]}</th>')
    h.append('</tr>')
    for c in agg:
        h.append(f'<tr><td class="rowh">{esc(agg[c]["name"])}</td>')
        for w in PRICE_WINDOWS:
            a = agg[c].get(w)
            o = orig.get(c, {}).get(w)
            if a is None:
                h.append('<td class="na">—</td>')
            else:
                cls = "pos" if a >= 0 else "neg"
                ostr = f' ({o:+.1f})' if o is not None else ''
                h.append(f'<td class="{cls}">{a:+.1f}%<span class="na">{ostr}</span></td>')
        h.append('</tr>')
    h.append('</table>')
    # 逐事件对比（剔除 vs 名义）
    h.append('<h4>各品种 × 各事件：剔除汇率后 vs 名义（逐事件，%）</h4>')
    adj_rows = usd.get("results_adjusted", [])
    orig_map = {r["commodity"] + "|" + r["event"]: r for r in price.get("results", [])}
    for c, name in price["commodities"].items():
        rows = [r for r in adj_rows if r["commodity"] == c]
        if not rows:
            continue
        h.append(f'<div class="subhead">{esc(name)}</div>')
        h.append('<table><tr><th>事件</th><th>强度</th>')
        for w in PRICE_WINDOWS:
            h.append(f'<th>{PRICE_WL[w]}</th>')
        h.append('</tr>')
        for r in rows:
            o = orig_map.get(c + "|" + r["event"])
            h.append(f'<tr><td>{esc(r["event"])}</td><td><span class="g g-{esc(r["grade"])}">{esc(r["grade"])}</span></td>')
            for w in PRICE_WINDOWS:
                a = r.get(w)
                ov = o.get(w) if o else None
                if a is None:
                    h.append('<td class="na">—</td>')
                else:
                    cls = "pos" if a >= 0 else "neg"
                    ostr = f' <span class="na">({ov:+.1f})</span>' if ov is not None else ''
                    h.append(f'<td class="{cls}">{a:+.1f}{ostr}</td>')
            h.append('</tr>')
        h.append('</table>')
    return "".join(h)


def macro_section(macro):
    if not macro:
        return ""
    h = []
    h.append(f'<div class="note">{esc(macro["note"])}</div>')

    # 宏观轨迹表（转向检测）
    h.append('<h4>🧭 宏观轨迹（启动期 → 峰值后6-12月，检测转向）</h4>')
    h.append('<table><tr><th>事件</th><th>强度</th><th>启动期PMI</th><th>启动期油%</th><th>启动态</th><th>峰后PMI</th><th>峰后油%</th><th>峰后态</th><th>PMI转向</th><th>原油转向</th><th>轨迹</th></tr>')
    for e in macro["events"]:
        ph = e.get("phase", {})
        st = ph.get("start", {}); pt = ph.get("post6_12", {})
        def state_cell(s):
            if not s: return '<span class="na">—</span>'
            cls = "pos" if s == "顺" else ("neg" if s == "逆" else "")
            return f'<span class="{cls}"><b>{s}</b></span>'
        traj_cls = {"全程顺风": "pos", "顺风转逆风": "neg", "逆风转顺风": "pos", "全程逆风": "neg"}.get(e["trajectory"], "")
        def f(v, is_pct=True):
            if v is None: return '<span class="na">—</span>'
            if is_pct:
                cls = "pos" if v >= 0 else "neg"
                return f'<span class="{cls}">{v:+.1f}%</span>'
            return f"{v:.1f}"
        h.append(f'<tr><td>{esc(e["event"])}</td><td><span class="g g-{esc(e["grade"])}">{esc(e["grade"])}</span></td>'
                 f'<td>{f(st.get("pmi"), False)}</td><td>{f(st.get("oil"))}</td><td>{state_cell(st.get("state"))}</td>'
                 f'<td>{f(pt.get("pmi"), False)}</td><td>{f(pt.get("oil"))}</td><td>{state_cell(pt.get("state"))}</td>'
                 f'<td>{esc(e.get("pmi_cross") or "—")}</td><td>{esc(e.get("oil_cross") or "—")}</td>'
                 f'<td class="{traj_cls}"><b>{esc(e["trajectory"])}</b></td></tr>')
    h.append('</table>')

    # 宏观状态快照表（静态口径）
    h.append('<h4>各事件宏观状态快照（静态口径）</h4>')
    h.append('<table><tr><th>事件</th><th>强度</th><th>PMI峰值</th><th>PMI状态</th><th>PMI走势</th><th>原油pre%</th><th>原油+6月%</th><th>宏观背景</th></tr>')
    for e in macro["events"]:
        pmi_cls = "pos" if e["pmi_state"] == "扩张" else ("neg" if e["pmi_state"] == "收缩" else "")
        label_cls = "pos" if e["macro_label"] == "顺风" else ("neg" if e["macro_label"] == "逆风" else "")
        def pct_cell(v):
            if v is None:
                return '<span class="na">—</span>'
            cls = "pos" if v >= 0 else "neg"
            return f'<span class="{cls}">{v:+.1f}%</span>'
        h.append(f'<tr><td>{esc(e["event"])}</td><td><span class="g g-{esc(e["grade"])}">{esc(e["grade"])}</span></td>'
                 f'<td>{e["pmi_peak"]:.1f}</td>'
                 f'<td class="{pmi_cls}">{e["pmi_state"] or "—"}</td>'
                 f'<td>{e["pmi_trend"]:+.1f}</td>'
                 f'<td>{pct_cell(e["oil_pre"])}</td>'
                 f'<td>{pct_cell(e["oil_post0_6"])}</td>'
                 f'<td class="{label_cls}"><b>{e["macro_label"]}</b></td></tr>')
    h.append('</table>')

    # 轨迹分组对比表
    traj_names = {"全程顺风": "🌬️ 全程顺风", "顺风转逆风": "⚠️ 顺风转逆风",
                  "逆风转顺风": "🔄 逆风转顺风", "全程逆风": "🥶 全程逆风", "分化": "🌗 分化"}
    for g, agg in macro.get("agg_by_trajectory", {}).items():
        ev_ids = macro.get("trajectory_groups", {}).get(g, [])
        h.append(f'<h4>{traj_names.get(g, g)}（{"、".join(ev_ids)}）</h4>')
        h.append('<table class="heat"><tr><th>品种</th>')
        for w in PRICE_WINDOWS:
            h.append(f'<th>{PRICE_WL[w]}</th>')
        h.append('</tr>')
        for c in agg:
            a = agg[c]
            h.append(f'<tr><td class="rowh">{esc(a["name"])}</td>')
            for w in PRICE_WINDOWS:
                v = a.get(w)
                if v is None:
                    h.append('<td class="na">—</td>')
                else:
                    cls = "pos" if v >= 0 else "neg"
                    h.append(f'<td class="{cls}">{v:+.1f}%</td>')
            h.append('</tr>')
        h.append('</table>')

    # 静态分组对比表
    label_names = {"顺风": "🌬️ 宏观顺风", "逆风": "🥶 宏观逆风", "混合": "🌗 混合"}
    for g in ["顺风", "逆风", "混合"]:
        if g not in macro["agg_by_macro"]:
            continue
        agg = macro["agg_by_macro"][g]
        ev_ids = macro["groups"].get(g, [])
        h.append(f'<h4>{label_names.get(g, g)}（{"、".join(ev_ids)}）</h4>')
        h.append('<table class="heat"><tr><th>品种</th>')
        for w in PRICE_WINDOWS:
            h.append(f'<th>{PRICE_WL[w]}</th>')
        h.append('</tr>')
        for c in agg:
            a = agg[c]
            h.append(f'<tr><td class="rowh">{esc(a["name"])}</td>')
            for w in PRICE_WINDOWS:
                v = a.get(w)
                if v is None:
                    h.append('<td class="na">—</td>')
                else:
                    cls = "pos" if v >= 0 else "neg"
                    h.append(f'<td class="{cls}">{v:+.1f}%</td>')
            h.append('</tr>')
        h.append('</table>')

    # 洞察
    h.append('<h4>关键洞察</h4><ul>')
    for x in macro.get("insight", []):
        h.append(f'<li>{esc(x)}</li>')
    h.append('</ul>')
    return "".join(h)


def attribution_section(at):
    if not at:
        return ""
    h = []
    h.append(f'<div class="note">{esc(at["note"])}</div>')

    att_cls = {
        "供给+宏观共振": "pos", "供给主导": "pos", "供给压过宏观": "pos",
        "宏观主导": "pos", "宏观压过供给": "pos",
        "双重压制（价格反走）": "neg", "宏观背离（价格反走）": "neg", "供给背离（价格反走）": "neg",
        "多空交织": "", "驱动待兑现": "", "信号中性": "",
    }
    emoji = {"P": "🌴", "SR": "🍬", "RU": "🌳", "SB": "🫘", "CT": "🧵"}
    supply_dir = {1: "减产(利多)", -1: "增产(利空)", 0: "中性"}
    macro_dir = {1: "顺", -1: "逆", 0: "—"}
    price_dir = {1: "涨", -1: "跌", 0: "平"}

    for c, ci in at["commodities"].items():
        primary_w = ci["events"][0].get("primary_window", "post6_12") if ci["events"] else "post6_12"
        pw_label = "峰值后0-6月(主)" if primary_w == "post0_6" else "峰值后0-6月"
        h.append(f'<h4>{emoji.get(c, "")} {esc(ci["name"])}（{"、".join(ci["prod_sources"]) if ci["prod_sources"] else "⚠️无产量数据"}）</h4>')
        h.append(f'<table><tr><th>事件</th><th>强度</th><th>供给冲击%</th><th>供给信号</th><th>宏观轨迹</th><th>{pw_label}%</th><th>归因(早)</th><th>峰值后6-12月%</th><th>归因(主)</th></tr>')
        for e in ci["events"]:
            def g(v, pct=True):
                if v is None:
                    return '<span class="na">—</span>'
                if pct:
                    cls = "pos" if v >= 0 else "neg"
                    return f'<span class="{cls}">{v:+.1f}%</span>'
                return f"{v:.1f}"
            acE = att_cls.get(e.get("attribution_early"), "")
            acL = att_cls.get(e["attribution"], "")
            h.append(f'<tr><td>{esc(e["event"])}</td><td><span class="g g-{esc(e["grade"])}">{esc(e["grade"])}</span></td>'
                     f'<td>{g(e["prod_shock"])}</td>'
                     f'<td>{supply_dir.get(e["supply_dir"], "—")}</td>'
                     f'<td>{esc(e["macro_traj"] or "—")}</td>'
                     f'<td>{g(e["price_post06"])}</td>'
                     f'<td class="{acE}">{esc(e.get("attribution_early") or "—")}</td>'
                     f'<td>{g(e["price_post612"])}</td>'
                     f'<td class="{acL}"><b>{esc(e["attribution"])}</b></td></tr>')
        h.append('</table>')

    # 关注要点
    h.append('<h4>各品种需着重关注的点</h4>')
    for f in at.get("focus", []):
        h.append(f'<div class="agri-card"><h3>{emoji.get(f["commodity"], "")} {esc(f["name"])}</h3><ul>')
        for p in f["points"]:
            h.append(f'<li>{esc(p)}</li>')
        h.append('</ul></div>')
    return "".join(h)


def build():
    with open(JSON_PATH, encoding="utf-8") as f:
        d = json.load(f)
    price = d["price"]
    prod = d["production"]
    ag = d.get("agronomy", {})
    usd = d.get("usd", {})
    macro = d.get("macro", {})
    attribution = d.get("attribution", {})

    concl = "".join(f"<li>{esc(c)}</li>" for c in d["conclusions"])

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>厄尔尼诺事件研究 — 农产品分段窗口报告</title>
<style>
  @page {{ size: A4; margin: 16mm 14mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: "PingFang SC","Microsoft YaHei","Hiragino Sans GB",sans-serif; color:#1a1a1a; font-size:11px; line-height:1.55; margin:0; }}
  h1 {{ font-size:20px; margin:0 0 4px; color:#0d3b66; }}
  .meta {{ color:#666; font-size:10px; margin-bottom:14px; }}
  h2 {{ font-size:15px; color:#0d3b66; border-bottom:2px solid #0d3b66; padding-bottom:4px; margin:22px 0 10px; page-break-after:avoid; }}
  h3 {{ font-size:13px; color:#1d6fb8; margin:14px 0 6px; page-break-after:avoid; }}
  h4 {{ font-size:12px; color:#333; margin:12px 0 4px; page-break-after:avoid; }}
  p {{ margin:4px 0; }}
  table {{ border-collapse:collapse; width:100%; margin:6px 0 10px; page-break-inside:auto; }}
  th,td {{ border:1px solid #bbb; padding:4px 6px; text-align:center; font-size:10px; }}
  th {{ background:#eef3f8; color:#0d3b66; font-weight:600; }}
  td.rowh, th.rowh {{ text-align:left; }}
  td.l {{ text-align:left; }}
  .pos {{ color:#c0392b; font-weight:600; }}
  .neg {{ color:#1e8449; font-weight:600; }}
  .na {{ color:#999; }}
  .heat td {{ font-weight:600; }}
  .g {{ display:inline-block; padding:0 6px; border-radius:8px; font-size:9px; font-weight:700; }}
  .g-超强 {{ background:#fdecea; color:#c0392b; }}
  .g-强 {{ background:#fdecea; color:#d35400; }}
  .g-中强 {{ background:#fef5e7; color:#b9770e; }}
  .g-中 {{ background:#eafaf1; color:#1e8449; }}
  .g-弱 {{ background:#eaf2f8; color:#2471a3; }}
  ul {{ margin:6px 0 6px 20px; padding:0; }}
  li {{ margin:3px 0; }}
  .note {{ font-size:10px; color:#555; background:#f5f6f7; border:1px dashed #ccc; border-radius:4px; padding:8px 10px; margin:8px 0; }}
  .agri-card {{ border:1px solid #d5dbe0; border-radius:6px; padding:10px 12px; margin:10px 0; page-break-inside:avoid; }}
  .agri-card h3 {{ margin:0 0 2px; }}
  .sub {{ color:#888; font-size:10px; font-weight:400; }}
  .cycle {{ font-size:10px; color:#555; margin:2px 0 6px; }}
  .keyrow {{ background:#fff8e1; }}
  .keytag {{ display:inline-block; padding:0 6px; border-radius:8px; font-size:9px; background:#f1c40f; color:#333; font-weight:700; }}
  .crit {{ background:#eaf2f8; border-left:3px solid #2471a3; padding:6px 10px; margin:8px 0; font-size:10.5px; border-radius:0 4px 4px 0; }}
  .irrev {{ background:#eafaf1; border-left:3px solid #1e8449; padding:6px 10px; margin:8px 0; font-size:10.5px; border-radius:0 4px 4px 0; }}
  .irrev ul {{ margin:3px 0 0 18px; }}
  .elnino {{ background:#fef5e7; border-left:3px solid #b9770e; padding:6px 10px; margin:8px 0; font-size:10.5px; border-radius:0 4px 4px 0; }}
  .link {{ font-size:9px; color:#888; margin:4px 0 0; }}
  .region-title {{ font-size:11px; color:#0d3b66; font-weight:700; margin:8px 0 4px; }}
  .region-card {{ border:1px solid #d5dbe0; border-left:3px solid #2471a3; border-radius:4px; padding:6px 10px; margin:5px 0; page-break-inside:avoid; }}
  .region-head {{ font-weight:700; color:#222; font-size:11px; }}
  .region-rank {{ display:inline-block; font-size:9px; color:#2471a3; background:#eaf2f8; border-radius:8px; padding:0 6px; margin-left:6px; font-weight:600; }}
  .region-row {{ font-size:10px; color:#333; margin:2px 0; }}
  .region-row.en {{ color:#8a5a00; }}
  .rk {{ display:inline-block; color:#888; font-size:9px; width:44px; }}
  .subhead {{ font-weight:700; color:#0d3b66; font-size:11px; margin:8px 0 2px; page-break-after:avoid; }}
  .pagebreak {{ page-break-before:always; }}
</style>
</head>
<body>
<h1>🌊 厄尔尼诺事件研究 — 农产品分段窗口报告</h1>
<div class="meta">事件池 9 次（1982–2024）· 价格口径 5 品种 + 产量口径 8 品种 · 种植知识 5 品种 · 生成时间：{esc(d['generated'])}</div>

<h2>一、核心结论</h2>
<ol>{concl}</ol>

<h2>二、事件池与强度分级</h2>
{events_table(d['events'])}

<h2>三、价格口径（国际价格，美元计价）</h2>
<div class="note">{esc(price['source_note'])}</div>
<h3>品种 × 分段窗口（跨事件均值，%）</h3>
{heat_table(price['agg_by_commodity'], PRICE_WINDOWS, PRICE_WL)}
<h3>各品种 × 各事件明细</h3>
{detail_tables(price['results'], price['commodities'], PRICE_WINDOWS, PRICE_WL)}
{usd_section(usd, price)}

<h2 class="pagebreak">四、宏观周期叠加（PMI + 原油）</h2>
{macro_section(macro)}

<h2 class="pagebreak">五、供给冲击 vs 宏观/供需 归因拆解</h2>
{attribution_section(attribution)}

<h2 class="pagebreak">六、产量口径（iFinD EDB 年度产量，双口径对比）</h2>
<div class="note">{esc(prod['season_note'])}</div>
<h3>口径A：前5年基线偏离（含长期扩产趋势）</h3>
<div class="note">{esc(prod['baseline']['note'])}</div>
{heat_table(prod['baseline']['agg_by_commodity'], prod['windows'], prod['window_labels'])}
{detail_tables(prod['baseline']['results'], prod['commodities'], prod['windows'], prod['window_labels'])}

<h3>口径B：对数去趋势偏离（前10年滚动，剔除趋势）</h3>
<div class="note">{esc(prod['detrended']['note'])}</div>
{heat_table(prod['detrended']['agg_by_commodity'], prod['windows'], prod['window_labels'])}
{detail_tables(prod['detrended']['results'], prod['commodities'], prod['windows'], prod['window_labels'])}

<h2 class="pagebreak">七、种植知识 — 生长阶段 / 水肥需求 / 关键期 / 不可逆损伤</h2>
<div class="note">{esc(ag.get('intro',''))}<br><b>图例：</b>{esc(ag.get('legend',''))}</div>
{agronomy_cards(ag)}

<h2>八、数据源说明</h2>
<div class="note">{esc(d['note'])}<br><b>生成时间：</b>{esc(d['generated'])} · 数据源：IMF商品价格 + CBOT大豆 + 郑棉期货 + iFinD EDB/USDA产量</div>
</body>
</html>"""

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"OK 生成 {OUT_HTML} ({len(html_doc)} 字符)")
    return OUT_HTML


def to_pdf(html_path):
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    cmd = [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
           f"--print-to-pdf={OUT_PDF}", f"file://{html_path}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if os.path.exists(OUT_PDF) and os.path.getsize(OUT_PDF) > 10000:
        print(f"OK 生成 {OUT_PDF} ({os.path.getsize(OUT_PDF)} 字节)")
    else:
        print("PDF 生成失败:", r.stderr[-500:])
        sys.exit(1)


if __name__ == "__main__":
    p = build()
    if "--pdf" in sys.argv:
        to_pdf(p)
