#!/usr/bin/env python3
"""
notes_app.py

Simple local note-taking application using SQLite3.
Features:
- Create, read, update, delete notes.
- Search notes by computing LCS (longest common subsequence) between
  the query and each note's title and content; results sorted by total LCS score descending.

Usage:
    python3 notes_app.py
"""

from typing import List, Optional, Tuple
import sqlite3
import os
import sys
import datetime

DATABASE_FILE_PATH = "notes.db"


# ------------------------------
# Database initialization
# ------------------------------
def initialize_database(connection: sqlite3.Connection) -> None:
    """
    Create the notes table if it does not already exist.

    Schema:
        id INTEGER PRIMARY KEY AUTOINCREMENT
        title TEXT NOT NULL
        content TEXT NOT NULL
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()


# ------------------------------
# LCS (Longest Common Subsequence)
# ------------------------------
def lcs_length(first_string: str, second_string: str) -> int:
    """
    Compute the length of the longest common subsequence (LCS) between
    first_string and second_string using dynamic programming.

    Uses a rolling (two-row) DP array to reduce memory usage to O(min(n, m)).
    """
    if not first_string or not second_string:
        return 0

    len_first = len(first_string)
    len_second = len(second_string)

    # Ensure second_string is the shorter one to minimize memory usage
    if len_second > len_first:
        first_string, second_string = second_string, first_string
        len_first, len_second = len_second, len_first

    previous_row = [0] * (len_second + 1)
    current_row = [0] * (len_second + 1)

    for i in range(1, len_first + 1):
        first_char = first_string[i - 1]
        for j in range(1, len_second + 1):
            if first_char == second_string[j - 1]:
                current_row[j] = previous_row[j - 1] + 1
            else:
                # take max(previous_row[j], current_row[j-1])
                if previous_row[j] >= current_row[j - 1]:
                    current_row[j] = previous_row[j]
                else:
                    current_row[j] = current_row[j - 1]
        # swap rows for next iteration
        previous_row, current_row = current_row, previous_row

    return previous_row[len_second]


# ------------------------------
# CRUD operations
# ------------------------------
def create_note(connection: sqlite3.Connection, title: str, content: str) -> int:
    """
    Insert a new note and return the new note id.
    """
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO notes (title, content) VALUES (?, ?)",
        (title, content)
    )
    connection.commit()
    return cursor.lastrowid


def read_note(connection: sqlite3.Connection, note_id: int) -> Optional[Tuple[int, str, str, str, str]]:
    """
    Return a single note by id, or None if not found.
    Returned tuple: (id, title, content, created_at, updated_at)
    """
    cursor = connection.cursor()
    cursor.execute(
        "SELECT id, title, content, created_at, updated_at FROM notes WHERE id = ?",
        (note_id,)
    )
    return cursor.fetchone()


def update_note(connection: sqlite3.Connection, note_id: int, title: Optional[str] = None,
                content: Optional[str] = None) -> bool:
    """
    Update the title and/or content of a note. Returns True if a row was updated.
    """
    if title is None and content is None:
        return False

    assignments: List[str] = []
    parameters: List[object] = []

    if title is not None:
        assignments.append("title = ?")
        parameters.append(title)
    if content is not None:
        assignments.append("content = ?")
        parameters.append(content)

    # Always update updated_at timestamp
    assignments.append("updated_at = CURRENT_TIMESTAMP")

    sql_statement = "UPDATE notes SET " + ", ".join(assignments) + " WHERE id = ?"
    parameters.append(note_id)

    cursor = connection.cursor()
    cursor.execute(sql_statement, parameters)
    connection.commit()
    return cursor.rowcount > 0


def delete_note(connection: sqlite3.Connection, note_id: int) -> bool:
    """
    Delete a note by id. Returns True if a row was deleted.
    """
    cursor = connection.cursor()
    cursor.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    connection.commit()
    return cursor.rowcount > 0


def list_all_notes(connection: sqlite3.Connection) -> List[Tuple[int, str, str, str, str]]:
    """
    Return all notes ordered by updated_at descending.
    Each row is: (id, title, content, created_at, updated_at)
    """
    cursor = connection.cursor()
    cursor.execute(
        "SELECT id, title, content, created_at, updated_at FROM notes ORDER BY updated_at DESC"
    )
    return cursor.fetchall()


# ------------------------------
# Search functionality
# ------------------------------
def search_notes_by_lcs(connection: sqlite3.Connection, query: str,
                        case_sensitive: bool = False,
                        max_results: int = 100) -> List[Tuple[int, int, str, str, str, str]]:
    """
    Search notes by computing LCS(query, title) + LCS(query, content) as the score.
    Returns a list of tuples sorted by score descending.

    Returned tuple format:
      (score, id, title, content, created_at, updated_at)
    """
    cursor = connection.cursor()
    cursor.execute("SELECT id, title, content, created_at, updated_at FROM notes")
    rows = cursor.fetchall()

    normalized_query = query if case_sensitive else query.lower()

    scored_results: List[Tuple[int, int, str, str, str, str]] = []

    for row in rows:
        note_id, note_title, note_content, created_at, updated_at = row
        title_for_compare = note_title if case_sensitive else (note_title or "").lower()
        content_for_compare = note_content if case_sensitive else (note_content or "").lower()

        score_title = lcs_length(title_for_compare, normalized_query)
        score_content = lcs_length(content_for_compare, normalized_query)
        total_score = score_title + score_content

        if total_score > 0:
            scored_results.append((total_score, note_id, note_title, note_content, created_at, updated_at))

    # Sort by score descending, then by updated_at descending (if available)
    def sort_key(item: Tuple[int, int, str, str, str, str]) -> Tuple[int, float]:
        score_value = item[0]
        updated_value = 0.0
        try:
            # Attempt to parse timestamp if it is a string
            updated_raw = item[5]
            if isinstance(updated_raw, str):
                updated_value = datetime.datetime.fromisoformat(updated_raw).timestamp()
            elif isinstance(updated_raw, (int, float)):
                updated_value = float(updated_raw)
            elif isinstance(updated_raw, datetime.datetime):
                updated_value = updated_raw.timestamp()
        except Exception:
            updated_value = 0.0
        return (-score_value, -updated_value)

    scored_results.sort(key=sort_key)
    return scored_results[:max_results]


# ------------------------------
# Command-line interface
# ------------------------------
def run_command_line_interface() -> None:
    """
    Run a simple command-line prompt for the notes application.

    Supported commands:
        add     - add a new note
        list    - list all notes
        get     - get a note by id
        update  - update a note by id
        delete  - delete a note by id
        search  - search notes using LCS scoring
        exit    - exit the application
    """
    connection = sqlite3.connect(
        DATABASE_FILE_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )
    initialize_database(connection)

    try:
        print("Notes App — commands: add / list / get / update / delete / search / exit")
        while True:
            command = input("command> ").strip().lower()
            if command == "add":
                title_input = input("Title: ").strip()
                print("Enter content lines. A single line with a dot (.) on its own finishes input.")
                content_lines: List[str] = []
                while True:
                    line = input()
                    if line == ".":
                        break
                    content_lines.append(line)
                content_input = "\n".join(content_lines)
                created_id = create_note(connection, title_input, content_input)
                print(f"Note created with id={created_id}")

            elif command == "list":
                rows = list_all_notes(connection)
                for row in rows:
                    note_id, title, _, created_at, updated_at = row
                    print(f"[{note_id}] {title} (updated: {updated_at})")

            elif command == "get":
                id_text = input("Note id: ").strip()
                if not id_text.isdigit():
                    print("Note id must be an integer.")
                    continue
                note = read_note(connection, int(id_text))
                if note:
                    note_id, title, content, created_at, updated_at = note
                    print(f"---- [{note_id}] {title} ----")
                    print(content)
                    print("----------------------------")
                else:
                    print("Note not found.")

            elif command == "update":
                id_text = input("Note id: ").strip()
                if not id_text.isdigit():
                    print("Note id must be an integer.")
                    continue
                note_id = int(id_text)
                new_title = input("New title (leave empty to keep unchanged): ")
                print("Enter new content lines. A single line with a dot (.) finishes input. To keep content unchanged, enter a single dot immediately.")
                first_line = input()
                if first_line == ".":
                    new_content = None
                else:
                    content_lines = [first_line]
                    while True:
                        line = input()
                        if line == ".":
                            break
                        content_lines.append(line)
                    new_content = "\n".join(content_lines)

                if new_title == "" and new_content is None:
                    print("No changes provided.")
                else:
                    updated = update_note(connection, note_id,
                                          title=new_title if new_title != "" else None,
                                          content=new_content)
                    print("Update succeeded." if updated else "Update failed or note not found.")

            elif command == "delete":
                id_text = input("Note id: ").strip()
                if not id_text.isdigit():
                    print("Note id must be an integer.")
                    continue
                deleted = delete_note(connection, int(id_text))
                print("Deleted." if deleted else "Note not found.")

            elif command == "search":
                query_text = input("Search query: ").strip()
                if not query_text:
                    print("Query must not be empty.")
                    continue
                case_choice = input("Case sensitive? (y/N): ").strip().lower()
                results = search_notes_by_lcs(connection, query_text, case_sensitive=(case_choice == "y"), max_results=50)
                if not results:
                    print("No matches found.")
                else:
                    for score, note_id, title, content, created_at, updated_at in results:
                        preview_line = (content.splitlines()[0] if content else "")
                        print(f"[{note_id}] (score={score}) {title} — {preview_line}")

            elif command == "exit":
                break

            elif command == "":
                continue

            else:
                print("Unknown command. Available: add, list, get, update, delete, search, exit")

    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
    finally:
        connection.close()


if __name__ == "__main__":
    run_command_line_interface()
