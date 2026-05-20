#!/usr/bin/env python3
"""
思考与Q&A 入库脚本
用法: echo '{"product":"碳酸锂",...}' | python3 qa_add.py
      python3 qa_add.py --file /tmp/qa_entry.json

answer 字段支持 Markdown 格式：
  - 用 ### 标题、**粗体**、- 列表
  - 前端自动渲染为 HTML（h3, strong, ul/li）
  - 飞书中发送的格式会在入库时保留为 Markdown
"""
import sys, os, json
from datetime import datetime

KB_DIR = os.path.dirname(os.path.abspath(__file__))
QA_DIR = os.path.join(KB_DIR, "qa")
DATA_DIR = os.path.join(QA_DIR, "data")
INDEX_PATH = os.path.join(DATA_DIR, "index.json")

# Product name → code mapping
PRODUCT_MAP = {
    "碳酸锂": "LC", "工业硅": "SI", "多晶硅": "PS",
    "螺纹钢": "RB", "热卷": "HC", "铁矿石": "I", "焦炭": "J", "焦煤": "JM",
    "不锈钢": "SS", "硅铁": "SF", "锰硅": "SM",
    "沪铜": "CU", "沪铝": "AL", "沪锌": "ZN", "沪铅": "PB", "沪镍": "NI", "沪锡": "SN",
    "氧化铝": "AO", "国际铜": "BC",
    "沪金": "AU", "沪银": "AG",
    "原油": "SC", "燃料油": "FU", "低硫燃油": "LU", "沥青": "BU", "液化气": "PG",
    "PTA": "TA", "甲醇": "MA", "塑料": "L", "聚丙烯": "PP", "PVC": "V",
    "乙二醇": "EG", "苯乙烯": "EB", "纯碱": "SA", "尿素": "UR", "烧碱": "SH", "短纤": "PF",
    "橡胶": "RU", "20号胶": "NR", "纸浆": "SP",
    "豆粕": "M", "豆油": "Y", "棕榈油": "P", "豆一": "A", "豆二": "B",
    "玉米": "C", "玉米淀粉": "CS", "白糖": "SR", "棉花": "CF",
    "菜粕": "RM", "菜油": "OI", "苹果": "AP", "红枣": "CJ", "花生": "PK",
    "生猪": "LH", "鸡蛋": "JD",
    "中证500": "IC", "上证50": "IH", "中证1000": "IM",
    "2年国债": "TS", "5年国债": "TF", "10年国债": "T", "30年国债": "TL",
    # 方法论研究专题
    "方法论研究": "MT",
}

def load_index():
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {"entries": [], "products": {}}

def save_index(idx):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(INDEX_PATH, 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

def add_entry(data):
    """Add a Q&A entry. data must have: product, question, answer.
    Optional: category, tags, key_findings."""
    product = data['product']
    product_code = PRODUCT_MAP.get(product, product[:2].upper())
    
    # Generate ID
    today = datetime.now().strftime('%Y-%m-%d')
    idx = load_index()
    count = sum(1 for e in idx['entries'] if e['product_code'] == product_code)
    entry_id = f"{product_code}-{today}-{count+1:03d}"
    
    entry = {
        "id": entry_id,
        "product": product,
        "product_code": product_code,
        "category": data.get('category', '回测分析'),
        "date": today,
        "question": data['question'],
        "answer": data['answer'],
        "key_findings": data.get('key_findings', []),
        "tags": data.get('tags', []),
    }
    
    # Save individual file
    product_dir = os.path.join(DATA_DIR, product_code)
    os.makedirs(product_dir, exist_ok=True)
    entry_path = os.path.join(product_dir, f"{entry_id}.json")
    with open(entry_path, 'w', encoding='utf-8') as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    
    # Update index — include full answer so frontend can render
    idx['entries'].append({
        "id": entry_id,
        "product": product,
        "product_code": product_code,
        "category": entry['category'],
        "date": today,
        "question": data['question'],
        "answer": data['answer'],
        "tags": entry['tags'],
        "key_findings": entry['key_findings'],
    })
    
    if product_code not in idx['products']:
        idx['products'][product_code] = product
    idx['products'][product_code] = product  # update name
    
    save_index(idx)
    print(f"✅ QA entry saved: {entry_id} → {entry_path}")
    return entry

if __name__ == '__main__':
    if '--file' in sys.argv:
        path = sys.argv[sys.argv.index('--file') + 1]
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)
    
    add_entry(data)
