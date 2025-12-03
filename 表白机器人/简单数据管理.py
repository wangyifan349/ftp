#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sqlite3
from pathlib import Path
from typing import List, Optional, Any
DB_PATH = Path("code_notes.db")
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
# ---------- CRUD ----------
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
    fields, values = [], []
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
def query_by_note(keyword: str) -> List[sqlite3.Row]:
    pattern = f"%{keyword}%"
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM entries WHERE note LIKE ?;", (pattern,))
        return cur.fetchall()
def query_by_tag(tag: str) -> List[sqlite3.Row]:
    pattern = f"%{tag}%"
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM entries WHERE tags LIKE ?;", (pattern,))
        return cur.fetchall()
def get_all() -> List[sqlite3.Row]:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM entries;")
        return cur.fetchall()
# ---------- 辅助 ----------
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
# ---------- 主菜单 ----------
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
            code = input("代码片段: ").strip()
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
