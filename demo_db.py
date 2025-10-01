#!/usr/bin/env python3
# demo_db.py
import sqlite3
import json
import datetime
import os
DB_FILE = "demo.db"
def get_conn():
    return sqlite3.connect(DB_FILE)
def init_db():
    if not os.path.exists(DB_FILE):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            quantity INTEGER DEFAULT 0,
            price REAL DEFAULT 0.0,
            in_stock INTEGER DEFAULT 1,        -- 0/1 as boolean
            created_at TEXT,                   -- ISO datetime string
            metadata TEXT                       -- JSON stored as text
        )
        """)
        conn.commit()
        conn.close()

def add_item():
    name = input("名称: ").strip()
    if not name:
        print("名称不能为空。"); return
    try:
        quantity = int(input("数量 (整数): ").strip() or "0")
    except:
        print("数量格式错误，设为0"); quantity = 0
    try:
        price = float(input("价格 (浮点): ").strip() or "0")
    except:
        print("价格格式错误，设为0.0"); price = 0.0
    in_stock = input("是否有库存? (y/n) [y]: ").strip().lower()
    in_stock = 1 if in_stock in ("", "y", "yes") else 0
    created_at = datetime.datetime.now().isoformat()
    # metadata 示例：自由填写 JSON，比如 {"color": "red"}
    meta_in = input("metadata (JSON 格式, 可留空): ").strip()
    try:
        metadata = json.dumps(json.loads(meta_in)) if meta_in else json.dumps({})
    except Exception as e:
        print("metadata 解析失败，使用空对象。")
        metadata = json.dumps({})

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO items (name, quantity, price, in_stock, created_at, metadata)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, quantity, price, in_stock, created_at, metadata))
    conn.commit()
    print(f"已添加 id={cur.lastrowid}")
    conn.close()

def list_items(limit=20):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, quantity, price, in_stock, created_at, metadata FROM items ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    if not rows:
        print("没有记录。")
    else:
        for r in rows:
            id, name, quantity, price, in_stock, created_at, metadata = r
            print(f"[{id}] {name} | qty={quantity} | price={price} | in_stock={bool(in_stock)} | created_at={created_at} | metadata={metadata}")
    conn.close()

def delete_item():
    try:
        id = int(input("输入要删除的 id: ").strip())
    except:
        print("id 格式错误"); return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM items WHERE id = ?", (id,))
    if cur.fetchone()[0] == 0:
        print("未找到该 id。"); conn.close(); return
    cur.execute("DELETE FROM items WHERE id = ?", (id,))
    conn.commit()
    print("已删除。")
    conn.close()

def update_item():
    try:
        id = int(input("输入要更新的 id: ").strip())
    except:
        print("id 格式错误"); return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, quantity, price, in_stock, created_at, metadata FROM items WHERE id = ?", (id,))
    row = cur.fetchone()
    if not row:
        print("未找到该 id。"); conn.close(); return
    _, name, quantity, price, in_stock, created_at, metadata = row
    print(f"当前: name={name}, quantity={quantity}, price={price}, in_stock={bool(in_stock)}, created_at={created_at}, metadata={metadata}")
    new_name = input(f"新名称 [{name}]: ").strip() or name
    try:
        new_quantity = int(input(f"新数量 [{quantity}]: ").strip() or quantity)
    except:
        print("数量格式错误，保持原值"); new_quantity = quantity
    try:
        new_price = float(input(f"新价格 [{price}]: ").strip() or price)
    except:
        print("价格格式错误，保持原值"); new_price = price
    in_stock_in = input(f"是否有库存? (y/n) [{'y' if in_stock else 'n'}]: ").strip().lower()
    new_in_stock = in_stock if in_stock_in=="" else (1 if in_stock_in in ("y","yes") else 0)
    meta_in = input(f"metadata (JSON) [{metadata}]: ").strip()
    if meta_in:
        try:
            new_metadata = json.dumps(json.loads(meta_in))
        except:
            print("metadata 解析失败，保持原值"); new_metadata = metadata
    else:
        new_metadata = metadata

    cur.execute("""
        UPDATE items SET name=?, quantity=?, price=?, in_stock=?, metadata=? WHERE id=?
    """, (new_name, new_quantity, new_price, new_in_stock, new_metadata, id))
    conn.commit()
    print("已更新。")
    conn.close()
def search_items():
    # 支持模糊搜索：按 name 或 metadata 内容模糊匹配，也可按数值范围（示例）
    q = input("输入模糊搜索关键字（会在 name 与 metadata 中搜索）: ").strip()
    if not q:
        print("关键字为空。"); return
    like = f"%{q}%"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, quantity, price, in_stock, created_at, metadata
        FROM items
        WHERE name LIKE ? OR metadata LIKE ?
        ORDER BY id DESC
        LIMIT 100
    """, (like, like))
    rows = cur.fetchall()
    if not rows:
        print("未找到匹配。")
    else:
        for r in rows:
            id, name, quantity, price, in_stock, created_at, metadata = r
            print(f"[{id}] {name} | qty={quantity} | price={price} | in_stock={bool(in_stock)} | created_at={created_at} | metadata={metadata}")
    conn.close()
def advanced_search():
    # 示例：按价格区间与是否有库存过滤
    try:
        minp = float(input("最小价格 (留空表示无): ").strip() or "-inf")
    except:
        minp = float("-inf")
    try:
        maxp = float(input("最大价格 (留空表示无): ").strip() or "inf")
    except:
        maxp = float("inf")
    instock_only = input("仅显示有库存? (y/n) [n]: ").strip().lower() in ("y","yes")
    q = "SELECT id, name, quantity, price, in_stock, created_at, metadata FROM items WHERE price BETWEEN ? AND ?"
    params = [minp if minp!=-float("inf") else -1e308, maxp if maxp!=float("inf") else 1e308]
    if instock_only:
        q += " AND in_stock=1"
    q += " ORDER BY id DESC LIMIT 100"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(q, params)
    rows = cur.fetchall()
    for r in rows:
        id, name, quantity, price, in_stock, created_at, metadata = r
        print(f"[{id}] {name} | qty={quantity} | price={price} | in_stock={bool(in_stock)} | created_at={created_at} | metadata={metadata}")
    conn.close()
def print_menu():
    print("""
请选择操作：
1) 列表 (最近 20)
2) 添加
3) 删除
4) 更新
5) 模糊搜索 (name / metadata)
6) 高级搜索 (价格区间 & 库存)
0) 退出
""")

def main():
    init_db()
    while True:
        print_menu()
        cmd = input("输入选项: ").strip()
        if cmd == "1":
            list_items()
        elif cmd == "2":
            add_item()
        elif cmd == "3":
            delete_item()
        elif cmd == "4":
            update_item()
        elif cmd == "5":
            search_items()
        elif cmd == "6":
            advanced_search()
        elif cmd == "0":
            print("退出。"); break
        else:
            print("无效选项。")
if __name__ == "__main__":
    main()
