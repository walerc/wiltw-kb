#!/usr/bin/env python3
"""QA delete processor — 处理「思考与Q&A」删除请求"""
import sys, os, json

KB_DIR = os.path.dirname(os.path.abspath(__file__))
PAGES_DIR = os.path.join(os.path.dirname(KB_DIR), 'wiltw-pages')
DATA_DIR = os.path.join(KB_DIR, 'qa', 'data')
INDEX_PATH = os.path.join(DATA_DIR, 'index.json')

def load_index():
    with open(INDEX_PATH, encoding='utf-8') as f:
        return json.load(f)

def save_index(idx, path=None):
    path = path or INDEX_PATH
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

def delete_entries(ids: list[str]) -> dict:
    """Delete QA entries by ID list. Returns stats."""
    if not ids:
        return {"deleted": 0, "errors": [], "ids": []}

    idx = load_index()
    id_set = set(ids)
    
    deleted = []
    errors = []
    
    for entry in idx['entries'][:]:
        if entry['id'] in id_set:
            # Delete individual file
            pdir = os.path.join(DATA_DIR, entry['product_code'])
            fpath = os.path.join(pdir, f"{entry['id']}.json")
            if os.path.exists(fpath):
                os.remove(fpath)
            # Remove from product count & clean empty dirs
            idx['entries'].remove(entry)
            deleted.append(entry['id'])
            id_set.discard(entry['id'])
    
    # Rebuild product list
    idx['products'] = {}
    for e in idx['entries']:
        idx['products'][e['product_code']] = e['product']
    
    # Clean empty product directories
    for code in sorted(os.listdir(DATA_DIR)):
        pdir = os.path.join(DATA_DIR, code)
        if os.path.isdir(pdir) and not os.listdir(pdir):
            os.rmdir(pdir)
    
    save_index(idx)
    
    # Also update pages copy
    pages_index = os.path.join(PAGES_DIR, 'qa', 'data', 'index.json')
    if os.path.exists(os.path.dirname(pages_index)):
        save_index(idx, pages_index)
    
    for eid in id_set:
        errors.append(f"ID not found: {eid}")
    
    return {"deleted": len(deleted), "errors": errors, "ids": deleted}

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python3 qa_delete.py ID1 [ID2 ...]")
        print("      python3 qa_delete.py --file /tmp/delete_list.txt")
        sys.exit(1)
    
    if '--file' in sys.argv:
        path = sys.argv[sys.argv.index('--file') + 1]
        with open(path) as f:
            ids = [line.strip() for line in f if line.strip()]
    else:
        ids = sys.argv[1:]
    
    result = delete_entries(ids)
    print(f"✅ 已删除 {result['deleted']} 个条目")
    for eid in result['ids']:
        print(f"   - {eid}")
    for err in result['errors']:
        print(f"⚠️  {err}")
    print(f"剩余 {len(load_index()['entries'])} 个条目")
