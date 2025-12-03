"""
1. 这段程序是一个本地的代码片段笔记管理工具，使用 SQLite 存储每条记录的代码、备注和标签；  
2. 它提供新增、删除、修改和查询四大基本操作，并通过交互式菜单让用户可以直观地完成这些任务；  
3. 查询备注时采用最长公共子序列（LCS）算法，对用户输入的关键字与备注之间的公共部分进行长度计算，并按该长度降序返回结果，从而在关键字中夹杂噪声时仍能准确匹配有效信息。
"""
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
from pathlib import Path
from typing import List, Optional

DB_PATH = Path("code_notes.db")

# -------------------------------------------------
# Database helpers
# -------------------------------------------------
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                note TEXT,
                tags TEXT
            );
            """
        )
        conn.commit()

# -------------------------------------------------
# CRUD operations
# -------------------------------------------------
def add_entry(code: str, note: str = "", tags: List[str] = None) -> int:
    tags_str = ",".join(tags) if tags else ""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO entries (code, note, tags) VALUES (?, ?, ?);",
            (code, note, tags_str),
        )
        conn.commit()
        return cur.lastrowid

def delete_entry(entry_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM entries WHERE id = ?;", (entry_id,))
        conn.commit()
        return cur.rowcount > 0

def update_entry(
    entry_id: int,
    code: Optional[str] = None,
    note: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> bool:
    fields = []
    values = []
    if code is not None:
        fields.append("code = ?")
        values.append(code)
    if note is not None:
        fields.append("note = ?")
        values.append(note)
    if tags is not None:
        fields.append("tags = ?")
        values.append(",".join(tags))
    if not fields:
        return False
    values.append(entry_id)
    sql = f"UPDATE entries SET {', '.join(fields)} WHERE id = ?;"
    with get_connection() as conn:
        cur = conn.execute(sql, tuple(values))
        conn.commit()
        return cur.rowcount > 0

# -------------------------------------------------
# LCS utility (dynamic programming, space‑optimized)
# -------------------------------------------------
def lcs_length(a: str, b: str) -> int:
    """Return length of longest common subsequence of a and b."""
    if len(a) < len(b):
        a, b = b, a                     # make a the longer string
    prev = [0] * (len(b) + 1)
    cur = [0] * (len(b) + 1)

    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                left = cur[j - 1]
                up = prev[j]
                cur[j] = left if left > up else up
        prev, cur = cur, prev
    return prev[-1]

# -------------------------------------------------
# Query functions
# -------------------------------------------------
def query_by_note(keyword: str) -> List[sqlite3.Row]:
    """
    Return rows whose note shares a non‑zero LCS with keyword,
    sorted by LCS length descending.
    """
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM entries;")
        all_rows = cur.fetchall()

    rows_with_score = []
    for row in all_rows:
        note_text = row["note"] if row["note"] else ""
        score = lcs_length(keyword, note_text)
        if score > 0:
            rows_with_score.append((score, row))

    rows_with_score.sort(key=lambda x: x[0], reverse=True)

    result = []
    for _, row in rows_with_score:
        result.append(row)
    return result

def query_by_tag(tag: str) -> List[sqlite3.Row]:
    pattern = f"%{tag}%"
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM entries WHERE tags LIKE ?;", (pattern,))
        return cur.fetchall()

def get_all() -> List[sqlite3.Row]:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM entries;")
        return cur.fetchall()

# -------------------------------------------------
# Display / input helpers
# -------------------------------------------------
def print_rows(rows: List[sqlite3.Row]) -> None:
    if not rows:
        print("未找到匹配记录。")
        return
    for r in rows:
        print(
            f"id: {r['id']}\n"
            f"code: {r['code']}\n"
            f"note: {r['note']}\n"
            f"tags: {r['tags']}\n"
            "--------------------"
        )

def input_tags() -> List[str]:
    raw = input("输入标签（多个标签请用逗号分隔）: ").strip()
    return [t.strip() for t in raw.split(",")] if raw else []

def read_multiline(prompt: str = "代码片段 (结束请单独输入 EOF): ") -> str:
    """Read multiple lines until a line containing only EOF is entered."""
    print(prompt)
    lines = []
    while True:
        line = input()
        if line.strip() == "EOF":
            break
        lines.append(line)
    return "\n".join(lines)

# -------------------------------------------------
# Main menu
# -------------------------------------------------
def main_menu() -> None:
    menu = """
请选择操作:
1. 新增记录
2. 删除记录
3. 修改记录
4. 按备注关键字查询（模糊搜索）
5. 按标签关键字查询（模糊搜索）
6. 查看全部记录
0. 退出
> """
    while True:
        choice = input(menu).strip()
        if choice == "1":
            code = read_multiline()
            note = input("备注信息: ").strip()
            tags = input_tags()
            new_id = add_entry(code, note, tags)
            print(f"已插入，记录 id = {new_id}")

        elif choice == "2":
            try:
                eid = int(input("要删除的记录 id: ").strip())
                if delete_entry(eid):
                    print("删除成功。")
                else:
                    print("未找到该 id。")
            except ValueError:
                print("id 必须是整数。")

        elif choice == "3":
            try:
                eid = int(input("要修改的记录 id: ").strip())
                print("留空表示不修改该字段。")
                code = input("新代码（或回车跳过）: ").strip() or None
                note = input("新备注（或回车跳过）: ").strip() or None
                tags_input = input("新标签（逗号分隔，或回车跳过）: ").strip()
                tags = [t.strip() for t in tags_input.split(",")] if tags_input else None
                if update_entry(eid, code, note, tags):
                    print("更新成功。")
                else:
                    print("未找到该 id 或未提供任何修改。")
            except ValueError:
                print("id 必须是整数。")

        elif choice == "4":
            kw = input("输入备注关键字（支持模糊搜索）: ").strip()
            rows = query_by_note(kw)
            print_rows(rows)

        elif choice == "5":
            kw = input("输入标签关键字（支持模糊搜索）: ").strip()
            rows = query_by_tag(kw)
            print_rows(rows)

        elif choice == "6":
            rows = get_all()
            print_rows(rows)

        elif choice == "0":
            print("再见！")
            break
        else:
            print("无效选项，请重新输入。")

if __name__ == "__main__":
    init_db()
    main_menu()
