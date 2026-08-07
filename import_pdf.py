#!/usr/bin/env python3
"""
WILTW KB 一体化导入脚本
用法: /usr/bin/python3 import_pdf.py <WILTW_YYYY-MM-DD.pdf>

流程: PDF → pdf2zh 翻译 → 自动分类打标 → 中文 PDF 入库 → 重建仪表盘 → GitHub Pages
"""
import subprocess, sys, os, shutil, glob, json, re
from pathlib import Path

KB_DIR = "/Users/gkx/WILTW_KB"
REPORTS_DIR = os.path.join(KB_DIR, "reports")
PAGES_DIR = "/Users/gkx/wiltw-pages"
PDF2ZH = "/Users/gkx/.local/bin/pdf2zh"

# DeepSeek config
os.environ["DEEPSEEK_API_KEY"] = "sk-8c30b9ec1ea04210aa4ae31db829b174"
os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"

def run(cmd, timeout=600):
    """Run shell command, return (success, output)."""
    print(f"  → {cmd}")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            print(f"  ✗ FAILED:\n{r.stderr[-500:]}")
            return False, r.stderr
        return True, r.stdout
    except subprocess.TimeoutExpired:
        print("  ✗ TIMEOUT")
        return False, "timeout"

def translate_pdf(pdf_path, out_dir):
    """Translate PDF using pdf2zh, return mono PDF path."""
    print(f"📖 Translating: {pdf_path}")
    ok, _ = run(f'{PDF2ZH} "{pdf_path}" -s deepseek -li en -lo zh -o "{out_dir}"', timeout=1200)
    
    # Find the generated mono PDF (pdf2zh preserves original filename)
    matches = glob.glob(os.path.join(out_dir, "*-mono.pdf"))
    if matches:
        mono = sorted(matches, key=os.path.getmtime, reverse=True)[0]
        print(f"✅ Translated: {mono}")
        return mono
    else:
        print(f"✗ No mono PDF found in {out_dir}")
        return None


# ═══════════════════════════════════════════════
# 自动分类器 — 基于关键词规则的章节分类和打标
# ═══════════════════════════════════════════════

CATEGORY_RULES = [
    # (category, [keywords], bonus_score)
    ("投资策略", ["资产配置", "投资组合", "策略与资产", "高信念", "确信", "配置表现"], 10),
    ("地缘政治", ["战争", "伊朗", "军事", "冲突", "选举", "政治", "外交", "制裁",
                   "国防", "军队", "北约", "俄罗斯", "乌克兰", "中东", "地缘", "霍尔木兹"], 10),
    ("科技与社会", ["AI", "人工智能", "量子", "机器人", "芯片", "数字化", "算法",
                     "ChatGPT", "科技", "屏幕", "社交媒体", "代币", "算力"], 8),
    ("关键矿产", ["矿产", "供应链", "稀土", "锑", "铜矿", "锂", "钴", "镍", "采矿",
                   "矿业", "关键材料", "金属供应"], 10),
    ("宏观与政策", ["利率", "央行", "债务", "通胀", "收益率", "货币政策", "财政",
                     "主权债务", "美联储", "购金", "美元走弱"], 8),
    ("环境与健康", ["气候", "环境", "塑料", "珊瑚", "珊瑚礁", "海洋", "污染", "碳排放",
                     "水资源", "生态", "蓝色经济", "生物多样", "粮食安全", "危机",
                     "灾难", "衰退"], 10),
    ("农业", ["小麦", "玉米", "大豆", "粮食", "收成", "产量", "化肥", "农产品",
               "粮食危机", "粮食安全", "厄尔尼诺"], 10),
    ("电动车", ["电动", "电池", "卡车", "充电", "新能源车", "重汽", "电车"], 10),
    ("贵金属", ["黄金", "白银", "金矿", "铂金", "钯金", "贵金属", "金银"], 10),
    ("教育与社会", ["教育", "学校", "学习", "童年", "屏幕", "儿童", "暑期",
                     "打工", "财务素养", "青年"], 6),
    ("思想与人文", ["哲学", "心理", "文化", "反思", "人文", "苏格拉底", "认知",
                     "社会", "快乐", "孤独"], 5),
    ("产业投资", ["产业", "行业", "投资机会", "深科技", "半导体", "制药", "能源",
                   "电网", "基建"], 6),
    ("中国宏观经济", ["中国", "人民币", "CIPS", "国债", "A股", "港股", "沪深",
                       "中国股票", "中证", "上证"], 8),
]

# Common tags that can be auto-extracted from text
AUTO_TAGS = [
    "黄金", "白银", "铜", "石油", "天然气", "小麦", "玉米", "大豆", "棉花",
    "AI", "人工智能", "量子", "机器人", "电池", "电动车", "芯片", "半导体",
    "供应链", "稀土", "锂", "钴", "镍", "锑", "铀",
    "美元", "利率", "通胀", "央行", "美联储", "国债", "债务",
    "中国", "美国", "俄罗斯", "乌克兰", "伊朗", "印度", "欧洲", "日本",
    "战争", "冲突", "制裁", "选举", "地缘",
    "气候", "碳排放", "塑料", "水", "珊瑚", "生物多样",
    "教育", "心理", "社会", "文化", "屏幕", "社交媒体",
    "比特币", "加密货币", "数字资产",
    "电网", "核能", "太阳能", "风能",
    "粮食安全", "能源安全", "供应链安全",
    "投资", "资产配置", "大宗商品", "股票", "债券",
]

def classify_section(title, summary_text):
    """Classify a section based on its title and summary using keyword rules."""
    text = (title + " " + summary_text).lower()
    
    scores = {}
    for cat, keywords, bonus in CATEGORY_RULES:
        score = 0
        for kw in keywords:
            if kw.lower() in text:
                score += 1
        if score > 0:
            scores[cat] = score + bonus
    
    if not scores:
        # Fallback: check title-only for weak signals
        for cat, keywords, bonus in CATEGORY_RULES:
            for kw in keywords[:3]:  # Only first 3 keywords
                if kw.lower() in title.lower():
                    scores[cat] = bonus
                    break
    
    if not scores:
        return "产业投资"  # Default fallback
    
    return max(scores, key=scores.get)

def extract_tags(title, summary_text):
    """Extract relevant tags from section title and summary."""
    text = title + " " + summary_text
    found = []
    seen = set()
    for tag in AUTO_TAGS:
        if tag in text and tag not in seen:
            found.append(tag)
            seen.add(tag)
    return found[:8]  # Max 8 tags

def auto_categorize(mono_pdf_path, report_date, total_pages):
    """
    Auto-categorize a translated WILTW PDF.
    
    Steps:
    1. Extract ToC from page 2
    2. For each section, get first-page text
    3. Classify and tag
    4. Write JSON metadata
    
    Returns: JSON path if created, None if skipped (already exists)
    """
    json_path = os.path.join(REPORTS_DIR, f"WILTW-{report_date}.json")
    if os.path.exists(json_path):
        print(f"🏷️  JSON already exists, skipping categorization: {json_path}")
        return json_path
    
    print("🏷️  Auto-categorizing sections...")
    
    try:
        import fitz
    except ImportError:
        print("  ⚠️  pymupdf not available, skipping auto-categorization")
        return None
    
    doc = fitz.open(mono_pdf_path)
    
    # Step 1: Extract ToC from page 2 (0-indexed = page 1)
    if doc.page_count < 2:
        doc.close()
        return None
    
    toc_text = doc[1].get_text()
    
    # Parse section entries from ToC
    # The ToC has entries like "NN Title... P. XX" but titles may span multiple lines
    # Some sections (e.g. 03, 08) may lack explicit number prefixes
    section_entries = []
    
    # Normalize: collapse all whitespace but keep structure
    lines = toc_text.split('\n')
    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if any(skip in line for skip in [
            '13D RESEARCH', 'PRINT ONCE', '机密', 'Back to ToC',
            'WHAT I LEARNED', '本周所学', '目录', 'June ', 'May ', '2026',
            '2375472783@qq.com'
        ]) or re.search(r'\bOF\s+\d+\b', line):  # Any "OF NN" page-count noise
            continue
        clean_lines.append(line)
    
    full_toc = ' '.join(clean_lines)
    
    # Strategy 1: Find all page markers (English "P. NN" or Chinese "第N页")
    page_markers = list(re.finditer(r'(?:[Pp]\.\s*(\d+)|第\s*(\d+)\s*页)', full_toc))
    # Normalize: use group(1) for English, group(2) for Chinese
    norm_markers = []
    for pm in page_markers:
        pn = pm.group(1) if pm.group(1) else pm.group(2)
        norm_markers.append((pm, int(pn)))
    
    if len(norm_markers) < 2:
        print("  ⚠️  Too few page markers found")
        doc.close()
        return None
    
    # Strategy 2: Extract text between consecutive page markers as sections
    last_end = 0
    auto_id = 0
    
    for i, (pm, page_num) in enumerate(norm_markers):
        # Text from last_end to this marker
        segment = full_toc[last_end:pm.start()].strip()
        last_end = pm.end()
        
        if not segment:
            continue
        
        # Try to extract a section number from the start
        m_num = re.match(r'(\d{2})\s+', segment)
        if m_num:
            sid = m_num.group(1)
            title = segment[m_num.end():].strip()
            auto_id = int(sid)
        else:
            # Unnumbered section — assign next ID
            auto_id += 1
            # Check if next ID would conflict with upcoming numbered section
            # Skip if this segment is just noise before the next section
            if len(segment) < 8:
                continue
            sid = f"{auto_id:02d}"
            title = segment
        
        # Clean title
        title = re.sub(r'\s+', ' ', title).strip(' .。,-')
        # Remove trailing page references that crept in
        title = re.sub(r'\s*[Pp]\.\s*\d+\s*$', '', title)
        
        if title and len(title) > 3:
            section_entries.append((sid, title, page_num))
    
    if not section_entries:
        print("  ⚠️  Could not parse ToC, skipping")
        doc.close()
        return None
    
    print(f"  Found {len(section_entries)} sections in ToC")
    
    # Step 2: Extract first-page text for each section
    sections = []
    for i, (sid, title, start_page) in enumerate(section_entries):
        page_idx = start_page - 1
        if page_idx >= doc.page_count:
            continue
        
        # Determine end page
        if i + 1 < len(section_entries):
            next_start = section_entries[i + 1][2]
            end_page = next_start - 1
        else:
            end_page = total_pages
        
        # Extract first page text
        first_page_text = doc[page_idx].get_text()
        clean = first_page_text.replace('\n', ' ').strip()
        summary = clean[:400]
        
        # Classify
        category = classify_section(title, summary)
        tags = extract_tags(title, summary)
        
        # Ensure section ID "00" is always 投资策略
        if sid == "00":
            category = "投资策略"
            if "资产配置" not in tags:
                tags.insert(0, "资产配置")
        
        sections.append({
            "id": sid,
            "title": title,
            "title_en": "",
            "category": category,
            "tags": tags,
            "pages": f"{start_page}-{end_page}",
            "summary": summary
        })
        print(f"    {sid}: [{category}] {title[:50]}")
    
    doc.close()
    
    if not sections:
        return None
    
    # Step 3: Build title from first 3-4 section topics
    main_topics = [s["title"].split("：")[0].split("——")[0][:20] for s in sections[1:5]]
    report_title = " · ".join(main_topics)
    
    # Step 4: Write JSON
    report = {
        "report_id": f"WILTW-{report_date}",
        "date": report_date,
        "title": report_title,
        "publisher": "13D Research & Strategy",
        "total_pages": total_pages,
        "sections": sections
    }
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Auto-categorized: {json_path} ({len(sections)} sections)")
    return json_path


def main():
    if len(sys.argv) < 2:
        print("用法: python3 import_pdf.py <WILTW_YYYY-MM-DD.pdf>")
        print("  将 WILTW PDF 自动翻译为中文并纳入知识库，推送到 GitHub Pages")
        sys.exit(1)
    
    pdf_path = os.path.abspath(sys.argv[1])
    if not os.path.exists(pdf_path):
        print(f"✗ 文件不存在: {pdf_path}")
        sys.exit(1)
    
    # Extract date from filename
    date_match = re.search(r'(\d{4}[-_]\d{2}[-_]\d{2})', os.path.basename(pdf_path))
    if not date_match:
        print("✗ 无法从文件名提取日期 (需要 YYYY-MM-DD 格式)")
        sys.exit(1)
    report_date = date_match.group(1).replace("_", "-")
    
    # Step 1: Translate
    tmpdir = "/tmp/wiltw_import"
    os.makedirs(tmpdir, exist_ok=True)
    mono_pdf = translate_pdf(pdf_path, tmpdir)
    if not mono_pdf:
        sys.exit(1)
    
    # Step 1.5: Auto-categorize
    total_pages = None
    try:
        import fitz
        doc = fitz.open(mono_pdf)
        total_pages = doc.page_count
        doc.close()
    except:
        pass
    
    auto_categorize(mono_pdf, report_date, total_pages or 60)
    
    # Step 2: Copy to reports/
    filename = os.path.basename(mono_pdf)
    # Clean filename
    base = filename
    base = re.sub(r'^[a-f0-9]+_[a-f0-9]+_', '', base)
    base = re.sub(r'^doc[a-f0-9_]+', '', base)
    target_name = base.replace("_", "-")
    if not target_name.startswith("WILTW-"):
        target_name = f"WILTW-{report_date}-mono.pdf"
    target_path = os.path.join(REPORTS_DIR, target_name)
    shutil.copy2(mono_pdf, target_path)
    print(f"📋 Copied to: {target_path}")
    
    # Step 3: Rebuild index.html
    print("🔨 Rebuilding index.html...")
    rebuild = os.path.join(KB_DIR, "rebuild_index.py")
    ok, out = run(f'/usr/bin/python3 "{rebuild}"', timeout=30)
    print(out)
    
    # Step 4: Sync to GitHub Pages repo
    print("🚀 Syncing to GitHub Pages...")
    shutil.copy2(target_path, os.path.join(PAGES_DIR, "reports", target_name))
    shutil.copy2(os.path.join(KB_DIR, "index.html"), os.path.join(PAGES_DIR, "index.html"))
    shutil.copy2(rebuild, os.path.join(PAGES_DIR, "rebuild_index.py"))
    
    # Copy rebuilt dashboard files (app.html + wiltw_data.json)
    for dash_file in ["app.html", "wiltw_data.json"]:
        src = os.path.join(KB_DIR, dash_file)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(PAGES_DIR, dash_file))
    
    # Copy JSON if generated
    json_name = f"WILTW-{report_date}.json"
    json_local = os.path.join(REPORTS_DIR, json_name)
    if os.path.exists(json_local):
        shutil.copy2(json_local, os.path.join(PAGES_DIR, "reports", json_name))
    
    # Commit and push
    subprocess.run(f'cd "{PAGES_DIR}" && git add -A && git commit -m "Import {target_name}"', shell=True, capture_output=True)
    ok2, _ = run(f'cd "{PAGES_DIR}" && git config http.postBuffer 524288000 && git push', timeout=120)
    
    if ok2:
        print("✅ 完成! https://walerc.github.io/wiltw-kb/")
    else:
        print("⚠️ 本地已更新，但 GitHub Push 失败（网络问题），稍后手动推送")

if __name__ == "__main__":
    main()
