#!/usr/bin/env python3
"""Rebuild WILTW KB index.html from JSON metadata + available PDFs."""

import json, os, glob
from collections import OrderedDict

KB_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(KB_DIR, "reports")
INDEX_PATH = os.path.join(KB_DIR, "index.html")

# ── Load all report JSONs ──
reports = []
for json_path in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.json"))):
    with open(json_path) as f:
        r = json.load(f)
    rid = r["report_id"]
    # Check if PDF exists
    pdf_path = os.path.join(REPORTS_DIR, f"{rid}-mono.pdf")
    r["has_full"] = os.path.exists(pdf_path)
    r["file_ext"] = "pdf"
    reports.append(r)

# ── Collect categories and all tags ──
categories = []
all_tags = []
seen_cat = set()
seen_tag = set()
for r in reports:
    for s in r["sections"]:
        if s["category"] not in seen_cat:
            seen_cat.add(s["category"])
            categories.append(s["category"])
        for t in s["tags"]:
            if t not in seen_tag:
                seen_tag.add(t)
                all_tags.append(t)

total_completed = sum(1 for r in reports if r.get("has_full"))

embedded = json.dumps({
    "reports": reports,
    "categories": categories,
    "all_tags": all_tags,
    "total_completed": total_completed,
}, ensure_ascii=False, separators=(",", ":"))

# ── Build HTML ──
html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex">
<title>WILTW 知识库 — 13D Research</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f0f2f5; color: #333; }}
header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #fff; padding: 1.5rem 2rem; }}
header h1 {{ font-size: 1.6rem; font-weight: 700; }}
header p {{ opacity: 0.7; font-size: 0.85rem; margin-top: 0.3rem; }}
.toolbar {{ background: #fff; border-bottom: 1px solid #e0e0e0; padding: 1rem 2rem; display: flex; gap: 1rem; flex-wrap: wrap; align-items: center; position: sticky; top: 0; z-index: 10; }}
.toolbar input {{ flex: 1; min-width: 200px; padding: 0.5rem 1rem; border: 1px solid #ddd; border-radius: 6px; font-size: 0.9rem; }}
.toolbar select {{ padding: 0.5rem 1rem; border: 1px solid #ddd; border-radius: 6px; font-size: 0.9rem; background: #fff; }}
.toolbar .stats {{ font-size: 0.8rem; color: #888; white-space: nowrap; }}
.main {{ max-width: 1200px; margin: 0 auto; padding: 1.5rem; }}
.tags-bar {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 1.5rem; }}
.tag {{ padding: 0.25rem 0.7rem; border-radius: 20px; font-size: 0.78rem; cursor: pointer; border: 1px solid #ddd; background: #fff; transition: all 0.2s; user-select: none; }}
.tag:hover {{ border-color: #e0c068; background: #fdfaf0; }}
.tag.active {{ background: #e0c068; color: #1a1a2e; border-color: #c9a840; font-weight: 600; }}
.cat-section {{ margin-bottom: 2rem; }}
.cat-header {{ font-size: 1.1rem; font-weight: 700; color: #1a1a2e; padding: 0.5rem 0; border-bottom: 2px solid #e0c068; margin-bottom: 0.8rem; display: flex; align-items: center; gap: 0.5rem; }}
.cat-header .count {{ background: #e0c068; color: #1a1a2e; font-size: 0.75rem; padding: 0.1rem 0.5rem; border-radius: 10px; }}
.report-card {{ background: #fff; border-radius: 8px; padding: 1.2rem 1.5rem; margin-bottom: 0.8rem; box-shadow: 0 1px 4px rgba(0,0,0,0.06); cursor: pointer; transition: all 0.2s; border-left: 4px solid transparent; }}
.report-card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,0.1); transform: translateY(-1px); }}
.report-card .meta {{ display: flex; gap: 0.8rem; align-items: center; margin-bottom: 0.4rem; flex-wrap: wrap; }}
.report-card .date {{ font-size: 0.8rem; color: #888; background: #f5f5f5; padding: 0.15rem 0.5rem; border-radius: 4px; }}
.report-card .cat-badge {{ font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 4px; }}
.cat-投资策略 {{ background: #e3f2fd; color: #1565c0; }}
.cat-贵金属 {{ background: #fff3e0; color: #e65100; }}
.cat-中国宏观经济 {{ background: #fce4ec; color: #c62828; }}
.cat-科技与社会 {{ background: #e8f5e9; color: #2e7d32; }}
.cat-关键矿产 {{ background: #f3e5f5; color: #6a1b9a; }}
.cat-地缘政治 {{ background: #eceff1; color: #37474f; }}
.cat-产业投资 {{ background: #e0f7fa; color: #006064; }}
.cat-思想与人文 {{ background: #fff8e1; color: #f57f17; }}
.cat-环境与健康 {{ background: #e8eaf6; color: #283593; }}
.report-card h3 {{ font-size: 1rem; margin-bottom: 0.3rem; }}
.report-card .summary {{ font-size: 0.85rem; color: #555; line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
.report-card .tags {{ display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.5rem; }}
.mini-tag {{ font-size: 0.7rem; padding: 0.1rem 0.4rem; border-radius: 10px; background: #f0f0f0; color: #666; }}
.report-card.has-full {{ border-left-color: #4caf50; }}
.report-card.meta-only {{ border-left-color: #ff9800; }}
.report-badge {{ font-size: 0.7rem; padding: 0.1rem 0.5rem; border-radius: 10px; margin-left: 0.5rem; }}
.report-badge.full {{ background: #e8f5e9; color: #2e7d32; }}
.report-badge.meta {{ background: #fff3e0; color: #e65100; }}
.modal {{ display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 100; overflow-y: auto; }}
.modal.active {{ display: block; }}
.modal-content {{ background: #fff; margin: 2rem auto; max-width: 960px; border-radius: 12px; box-shadow: 0 8px 40px rgba(0,0,0,0.2); }}
.modal-header {{ padding: 1.2rem 1.5rem; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; background: #fff; border-radius: 12px 12px 0 0; z-index: 1; }}
.modal-header h2 {{ font-size: 1.2rem; }}
.modal-close {{ background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #888; padding: 0.3rem; }}
.modal-body {{ padding: 1.5rem; max-height: 70vh; overflow-y: auto; }}
.modal-body h3 {{ font-size: 1rem; color: #1a1a2e; margin: 1rem 0 0.5rem; padding-top: 0.5rem; border-top: 1px solid #f0f0f0; }}
.modal-body .section-summary {{ background: #f9f9f9; padding: 0.8rem 1rem; border-radius: 6px; margin: 0.3rem 0 0.8rem; font-size: 0.9rem; line-height: 1.7; }}
.modal-footer {{ padding: 1rem 1.5rem; border-top: 1px solid #eee; display: flex; gap: 0.8rem; }}
.modal-footer button {{ padding: 0.5rem 1.2rem; border-radius: 6px; border: 1px solid #ddd; cursor: pointer; font-size: 0.9rem; background: #fff; }}
.modal-footer .btn-primary {{ background: #1a1a2e; color: #fff; border-color: #1a1a2e; }}
.modal-footer .btn-primary:hover {{ background: #2d2d4e; }}
.modal-footer .btn-primary:disabled {{ background: #ccc; border-color: #ccc; cursor: not-allowed; }}
.empty {{ text-align: center; padding: 3rem; color: #888; }}
@media (max-width: 768px) {{ .toolbar {{ padding: 0.8rem 1rem; }} .main {{ padding: 1rem; }} .report-card {{ padding: 1rem; }} .modal-content {{ margin: 0; border-radius: 0; min-height: 100vh; }} }}
</style>
</head>
<body>
<header><h1>📚 WILTW 知识库</h1><p>13D Research & Strategy · "What I Learned This Week" 中文知识库 · <span id="headerStats"></span></p></header>
<div class="toolbar">
  <input type="text" id="searchInput" placeholder="🔍 搜索报告内容、标签、关键词..." oninput="filterReports()">
  <select id="catFilter" onchange="filterReports()"><option value="all">全部分类</option></select>
  <span class="stats" id="stats">加载中...</span>
</div>
<div class="main">
  <div class="tags-bar" id="tagCloud"></div>
  <div id="reportList"></div>
</div>
<div class="modal" id="modal">
  <div class="modal-content">
    <div class="modal-header"><h2 id="modalTitle"></h2><button class="modal-close" onclick="closeModal()">✕</button></div>
    <div class="modal-body" id="modalBody"></div>
    <div class="modal-footer">
      <button class="btn-primary" id="btnOpenReport">📄 查看完整报告</button>
      <button onclick="closeModal()">关闭</button>
    </div>
  </div>
</div>
<script>
const EMBEDDED_DATA = {embedded};
let data=null,activeTag=null,currentReportId=null;
function init(){{data=EMBEDDED_DATA;document.getElementById('headerStats').textContent=data.total_completed+'/'+data.reports.length+' 完整翻译';const c=document.getElementById('catFilter');data.categories.forEach(x=>{{let n=0;data.reports.forEach(r=>r.sections.forEach(s=>{{if(s.category===x)n++}}));const o=document.createElement('option');o.value=x;o.textContent=x+' ('+n+')';c.appendChild(o)}});renderTagCloud();filterReports()}}
function renderTagCloud(){{const t=activeTag?[activeTag,...data.all_tags.filter(x=>x!==activeTag)]:data.all_tags;document.getElementById('tagCloud').innerHTML=t.map(x=>'<span class="tag '+(x===activeTag?'active':'')+'" onclick="toggleTag(\\''+x.replace(/'/g,"\\\\'")+'\\')">'+x+'</span>').join('')}}
function toggleTag(t){{activeTag=activeTag===t?null:t;renderTagCloud();filterReports()}}
function filterReports(){{const q=document.getElementById('searchInput').value.toLowerCase(),cf=document.getElementById('catFilter').value;let vs=[];data.reports.forEach(r=>r.sections.forEach(s=>{{if(cf!=='all'&&s.category!==cf)return;if(activeTag&&!s.tags.includes(activeTag))return;if(q){{const st=(s.title+' '+s.summary+' '+s.tags.join(' ')).toLowerCase();if(!st.includes(q))return}}vs.push({{report:r,section:s}})}}));document.getElementById('stats').textContent='共 '+data.reports.length+' 期报告 · '+vs.length+' 个匹配条目';const g={{}};vs.forEach(({{report:r,section:s}})=>{{if(!g[s.category])g[s.category]=[];g[s.category].push({{report:r,section:s}})}});const l=document.getElementById('reportList');if(vs.length===0){{l.innerHTML='<div class="empty">📭 没有匹配的内容</div>';return}}l.innerHTML=Object.entries(g).map(([cat,items])=>'<div class="cat-section"><div class="cat-header">'+cat+' <span class="count">'+items.length+'</span></div>'+items.map(({{report:r,section:s}})=>'<div class="report-card cat-'+cat+(r.has_full?' has-full':' meta-only')+'" onclick="openDetail(\\''+r.report_id+'\\',\\''+s.id+'\\')"><div class="meta"><span class="date">📅 '+r.date+'</span>'+(r.has_full?'<span class="report-badge full">✓ PDF</span>':'<span class="report-badge meta">⏳</span>')+'<span class="cat-badge cat-'+cat+'">'+cat+'</span></div><h3>'+s.id+'. '+s.title+'</h3><div class="summary">'+s.summary+'</div><div class="tags">'+s.tags.map(t=>'<span class="mini-tag">#'+t+'</span>').join(' ')+'</div></div>').join('')+'</div>').join('')}}
function openDetail(rid,sid){{const r=data.reports.find(x=>x.report_id===rid);if(!r)return;const s=r.sections.find(x=>x.id===sid)||r.sections[0];currentReportId=rid;document.getElementById('modalTitle').textContent=r.date+' · '+s.title;document.getElementById('modalBody').innerHTML='<p style="color:#888;margin-bottom:1rem">📰 '+r.publisher+' · 共'+r.total_pages+'页 · '+r.sections.length+' 个主题</p>'+r.sections.map(x=>'<h3 style="color:'+(x.id===sid?'#e0c068':'#888')+'">'+x.id+'. '+x.title+' <span style="font-size:0.75rem;font-weight:normal">['+x.pages+'页]</span></h3><div class="section-summary">'+x.summary+'</div><div style="display:flex;flex-wrap:wrap;gap:0.3rem;margin-bottom:1rem">'+x.tags.map(t=>'<span class="mini-tag">#'+t+'</span>').join(' ')+'</div>').join('');const b=document.getElementById('btnOpenReport');if(r.has_full){{b.disabled=false;b.textContent='📄 查看完整中文报告 (PDF)';b.style.background='#1a1a2e';b.style.color='#fff';b.onclick=function(){{window.open('reports/'+rid+'-mono.pdf','_blank')}}}}else{{b.disabled=true;b.textContent='⏳ 翻译生成中...';b.style.background='#ccc';b.style.color='#666';b.onclick=null}}document.getElementById('modal').classList.add('active');document.body.style.overflow='hidden'}}
function closeModal(){{document.getElementById('modal').classList.remove('active');document.body.style.overflow=''}}
document.getElementById('modal').addEventListener('click',function(e){{if(e.target===this)closeModal()}});
document.addEventListener('keydown',function(e){{if(e.key==='Escape')closeModal();if((e.metaKey||e.ctrlKey)&&e.key==='k'){{e.preventDefault();document.getElementById('searchInput').focus()}}}});
init();
</script>
</body>
</html>'''

with open(INDEX_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print(f"✅ index.html rebuilt: {total_completed}/{len(reports)} reports have PDFs")
print(f"   Categories: {len(categories)}")
print(f"   Tags: {len(all_tags)}")
for r in reports:
    status = "✓ PDF" if r.get("has_full") else "⏳ missing"
    print(f"   {r['report_id']}  {status}")
