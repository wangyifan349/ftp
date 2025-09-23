#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
file_organizer_dark.py
A cleaner, function-oriented PyQt5 file organizer with a dark theme.
Features:
- Scan directory and compute SHA256 to detect duplicates
- Delete duplicates (with confirmation and keep strategy)
- Migrate files by type to a target folder (images/videos/music/documents/others)
- Organize files by date (YYYY-MM) or by extension
- Threaded operations using QThreadPool + QRunnable with signals for UI updates
- Conflict handling: rename / overwrite / skip
- Dark macOS-like style and improved layout
"""
import sys
import os
import hashlib
import shutil
import fnmatch
import traceback
from pathlib import Path
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar,
    QTabWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QCheckBox,
    QComboBox, QSizePolicy, QSpacerItem
)
from PyQt5.QtCore import Qt, QRunnable, QThreadPool, pyqtSignal, QObject
# -------------------------
# Constants & helpers
# -------------------------
BLOCK_SIZE = 65536
TYPE_PATTERNS = {
    "images": ["*.jpg", "*.jpeg", "*.png", "*.gif", "*.bmp", "*.tiff", "*.webp", "*.heic"],
    "videos": ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.wmv", "*.flv"],
    "music":  ["*.mp3", "*.wav", "*.flac", "*.aac", "*.ogg", "*.m4a"],
    "documents": ["*.pdf", "*.doc", "*.docx", "*.xls", "*.xlsx", "*.ppt", "*.pptx", "*.txt", "*.md"]
}
def compute_sha256(file_path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(BLOCK_SIZE), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None
def match_type(filename: str, key: str) -> bool:
    name = filename.lower()
    for pattern in TYPE_PATTERNS.get(key, []):
        if fnmatch.fnmatch(name, pattern):
            return True
    return False
def safe_move(src: str, dst: str) -> None:
    """
    Move file safely across devices. Use shutil.move which handles cross-device.
    If failure occurs, raise exception so caller can log and decide.
    """
    shutil.move(src, dst)
def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    base = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 1
    while True:
        candidate = parent / f"{base} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1
# -------------------------
# Worker signals (single QObject)
# -------------------------
class Signals(QObject):
    progress = pyqtSignal(int)
    message = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
# -------------------------
# Workers as functions returning QRunnable
# -------------------------
def make_scan_worker(root: str, exclude_patterns: list[str], follow_links: bool):
    signals = Signals()
    class ScanTask(QRunnable):
        def run(self):
            try:
                files = []
                for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_links):
                    for fname in filenames:
                        full = os.path.join(dirpath, fname)
                        skip = False
                        for pat in exclude_patterns:
                            if fnmatch.fnmatch(full, pat) or fnmatch.fnmatch(fname, pat):
                                skip = True
                                break
                        if not skip:
                            files.append(full)
                total = len(files)
                if total == 0:
                    signals.message.emit("No files found to scan.")
                    signals.finished.emit({})
                    return
                hashes = {}
                for idx, f in enumerate(files, start=1):
                    signals.message.emit(f"Hashing: {f}")
                    h = compute_sha256(f)
                    if h:
                        hashes.setdefault(h, []).append(f)
                    else:
                        signals.message.emit(f"Unable to read: {f}")
                    signals.progress.emit(int(idx/total*100))
                signals.message.emit("Scan completed.")
                signals.finished.emit(hashes)
            except Exception as e:
                signals.error.emit(traceback.format_exc())
    task = ScanTask()
    task.signals = signals
    return task, signals
def make_delete_worker(hashes: dict, keep_strategy: str):
    signals = Signals()
    class DeleteTask(QRunnable):
        def run(self):
            try:
                duplicate_groups = [(h, paths) for h, paths in hashes.items() if len(paths) > 1]
                total = len(duplicate_groups)
                if total == 0:
                    signals.message.emit("No duplicates found.")
                    signals.finished.emit(0)
                    return
                deleted = 0
                for idx, (h, paths) in enumerate(duplicate_groups, start=1):
                    # choose keeper
                    keeper = paths[0]
                    if keep_strategy in ("newest", "oldest"):
                        paths_sorted = sorted(paths, key=lambda p: os.path.getmtime(p))
                        keeper = paths_sorted[-1] if keep_strategy == "newest" else paths_sorted[0]
                    for p in paths:
                        if p == keeper:
                            continue
                        try:
                            os.remove(p)
                            deleted += 1
                            signals.message.emit(f"Deleted: {p}")
                        except Exception as e:
                            signals.message.emit(f"Failed to delete {p}: {e}")
                    signals.progress.emit(int(idx/total*100))
                signals.message.emit(f"Delete completed. Deleted {deleted} files.")
                signals.finished.emit(deleted)
            except Exception:
                signals.error.emit(traceback.format_exc())
    task = DeleteTask()
    task.signals = signals
    return task, signals
def make_migrate_worker(src_root: str, dst_root: str, type_keys: list[str], conflict: str, exclude_patterns: list[str]):
    signals = Signals()
    class MigrateTask(QRunnable):
        def run(self):
            try:
                files = []
                for dirpath, dirnames, filenames in os.walk(src_root):
                    for fname in filenames:
                        full = os.path.join(dirpath, fname)
                        skip = any(fnmatch.fnmatch(full, pat) or fnmatch.fnmatch(fname, pat) for pat in exclude_patterns)
                        if not skip:
                            files.append(full)
                total = len(files)
                if total == 0:
                    signals.message.emit("No files to migrate.")
                    signals.finished.emit(0)
                    return
                moved = 0
                for idx, f in enumerate(files, start=1):
                    name = os.path.basename(f)
                    moved_flag = False
                    for key in type_keys:
                        if match_type(name, key):
                            target_dir = os.path.join(dst_root, key)
                            os.makedirs(target_dir, exist_ok=True)
                            dst = os.path.join(target_dir, name)
                            if os.path.exists(dst):
                                if conflict == "skip":
                                    signals.message.emit(f"Exists, skip: {dst}")
                                    moved_flag = True
                                    break
                                elif conflict == "overwrite":
                                    try:
                                        os.remove(dst)
                                    except Exception:
                                        pass
                                else:  # rename
                                    dst = str(unique_path(Path(dst)))
                            try:
                                safe_move(f, dst)
                                moved += 1
                                signals.message.emit(f"Moved: {f} -> {dst}")
                            except Exception as e:
                                signals.message.emit(f"Move failed {f}: {e}")
                            moved_flag = True
                            break
                    if not moved_flag:
                        target_dir = os.path.join(dst_root, "others")
                        os.makedirs(target_dir, exist_ok=True)
                        dst = os.path.join(target_dir, name)
                        if os.path.exists(dst):
                            if conflict == "skip":
                                signals.message.emit(f"Exists, skip: {dst}")
                            elif conflict == "overwrite":
                                try:
                                    os.remove(dst)
                                except Exception:
                                    pass
                                try:
                                    safe_move(f, dst)
                                    moved += 1
                                    signals.message.emit(f"Moved: {f} -> {dst}")
                                except Exception as e:
                                    signals.message.emit(f"Move failed {f}: {e}")
                            else:
                                dst = str(unique_path(Path(dst)))
                                try:
                                    safe_move(f, dst)
                                    moved += 1
                                    signals.message.emit(f"Moved: {f} -> {dst}")
                                except Exception as e:
                                    signals.message.emit(f"Move failed {f}: {e}")
                        else:
                            try:
                                safe_move(f, dst)
                                moved += 1
                                signals.message.emit(f"Moved: {f} -> {dst}")
                            except Exception as e:
                                signals.message.emit(f"Move failed {f}: {e}")
                    signals.progress.emit(int(idx/total*100))
                signals.message.emit(f"Migrate completed. Moved {moved} files.")
                signals.finished.emit(moved)
            except Exception:
                signals.error.emit(traceback.format_exc())
    task = MigrateTask()
    task.signals = signals
    return task, signals
def make_organize_worker(root: str, mode: str, conflict: str, exclude_patterns: list[str]):
    signals = Signals()
    class OrganizeTask(QRunnable):
        def run(self):
            try:
                files = []
                for dirpath, dirnames, filenames in os.walk(root):
                    for fname in filenames:
                        full = os.path.join(dirpath, fname)
                        skip = any(fnmatch.fnmatch(full, pat) or fnmatch.fnmatch(fname, pat) for pat in exclude_patterns)
                        if not skip:
                            files.append(full)
                total = len(files)
                if total == 0:
                    signals.message.emit("No files to organize.")
                    signals.finished.emit(0)
                    return
                moved = 0
                for idx, f in enumerate(files, start=1):
                    name = os.path.basename(f)
                    if mode == "by_date":
                        try:
                            mtime = datetime.fromtimestamp(os.path.getmtime(f))
                            folder = f"{mtime.year}-{mtime.month:02d}"
                        except Exception:
                            folder = "unknown_date"
                    else:
                        ext = Path(name).suffix.lower().lstrip(".")
                        folder = ext if ext else "no_ext"
                    target_dir = os.path.join(root, folder)
                    os.makedirs(target_dir, exist_ok=True)
                    dst = os.path.join(target_dir, name)
                    if os.path.exists(dst):
                        if conflict == "skip":
                            signals.message.emit(f"Exists, skip: {dst}")
                        elif conflict == "overwrite":
                            try:
                                os.remove(dst)
                            except Exception:
                                pass
                            try:
                                safe_move(f, dst)
                                moved += 1
                                signals.message.emit(f"Moved (overwrite): {f} -> {dst}")
                            except Exception as e:
                                signals.message.emit(f"Move failed {f}: {e}")
                        else:
                            dst = str(unique_path(Path(dst)))
                            try:
                                safe_move(f, dst)
                                moved += 1
                                signals.message.emit(f"Moved (rename): {f} -> {dst}")
                            except Exception as e:
                                signals.message.emit(f"Move failed {f}: {e}")
                    else:
                        try:
                            safe_move(f, dst)
                            moved += 1
                            signals.message.emit(f"Moved: {f} -> {dst}")
                        except Exception as e:
                            signals.message.emit(f"Move failed {f}: {e}")
                    signals.progress.emit(int(idx/total*100))
                signals.message.emit(f"Organize completed. Moved {moved} files.")
                signals.finished.emit(moved)
            except Exception:
                signals.error.emit(traceback.format_exc())
    task = OrganizeTask()
    task.signals = signals
    return task, signals
# -------------------------
# UI building (function-based)
# -------------------------
def apply_dark_style(app: QApplication):
    dark_sheet = """
    QWidget { background-color: #151515; color: #E6E6E6; font-family: "Segoe UI", "Helvetica Neue", Arial; }
    QTabWidget::pane { border: 1px solid #222; }
    QTabBar::tab { background: #1f1f1f; padding: 8px 16px; margin: 2px; border-radius: 6px; }
    QTabBar::tab:selected { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2b2b2b, stop:1 #232323); }
    QPushButton { background: #2a2a2a; border: 1px solid #333; padding: 6px 10px; border-radius: 6px; }
    QPushButton:hover { background: #313131; }
    QPushButton:pressed { background: #1f1f1f; }
    QLineEdit, QTextEdit { background: #0f0f0f; border: 1px solid #333; padding: 6px; border-radius: 6px; color: #ddd; }
    QProgressBar { background: #111; border: 1px solid #333; border-radius: 6px; text-align: center; }
    QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00aaff, stop:1 #0066cc); border-radius: 6px; }
    QLabel { color: #cccccc; }
    QComboBox { background: #0f0f0f; border: 1px solid #333; padding: 4px; border-radius: 6px; }
    QCheckBox { color: #ddd; }
    """
    app.setStyleSheet(dark_sheet)
def create_main_window():
    window = QMainWindow()
    window.setWindowTitle("File Organizer — Dark")
    window.resize(1000, 700)
    central = QWidget()
    window.setCentralWidget(central)
    main_layout = QVBoxLayout(central)
    tabs = QTabWidget()
    main_layout.addWidget(tabs)
    # --- Tab: Scan & Dedupe ---
    tab_scan = QWidget()
    tabs.addTab(tab_scan, "Scan & Dedupe")
    s_layout = QVBoxLayout(tab_scan)
    grid = QGridLayout()
    s_layout.addLayout(grid)
    lbl_scan_dir = QLabel("Scan directory:")
    edit_scan_dir = QLineEdit()
    btn_browse_scan = QPushButton("Browse")
    btn_scan = QPushButton("Start Scan")
    btn_delete = QPushButton("Delete Duplicates")
    combo_keep = QComboBox()
    combo_keep.addItems(["first", "newest", "oldest"])
    edit_exclude = QLineEdit()
    edit_exclude.setPlaceholderText("Exclude patterns, separated by ; e.g. *.tmp;*/node_modules/*")
    grid.addWidget(lbl_scan_dir, 0, 0)
    grid.addWidget(edit_scan_dir, 0, 1)
    grid.addWidget(btn_browse_scan, 0, 2)
    grid.addWidget(btn_scan, 0, 3)
    grid.addWidget(btn_delete, 0, 4)
    grid.addWidget(QLabel("Keep:"), 1, 0)
    grid.addWidget(combo_keep, 1, 1)
    grid.addWidget(QLabel("Exclude:"), 2, 0)
    grid.addWidget(edit_exclude, 2, 1, 1, 4)
    progress_scan = QProgressBar()
    log_scan = QTextEdit()
    log_scan.setReadOnly(True)
    s_layout.addWidget(progress_scan)
    s_layout.addWidget(log_scan)
    # --- Tab: Migrate ---
    tab_migrate = QWidget()
    tabs.addTab(tab_migrate, "Migrate")
    m_layout = QVBoxLayout(tab_migrate)
    m_grid = QGridLayout()
    m_layout.addLayout(m_grid)
    lbl_src = QLabel("Source:")
    edit_src = QLineEdit()
    btn_browse_src = QPushButton("Browse")
    lbl_dst = QLabel("Target:")
    edit_dst = QLineEdit()
    btn_browse_dst = QPushButton("Browse")
    m_grid.addWidget(lbl_src, 0, 0); m_grid.addWidget(edit_src, 0, 1); m_grid.addWidget(btn_browse_src, 0, 2)
    m_grid.addWidget(lbl_dst, 1, 0); m_grid.addWidget(edit_dst, 1, 1); m_grid.addWidget(btn_browse_dst, 1, 2)
    types_layout = QHBoxLayout()
    chk_images = QCheckBox("Images"); chk_images.setChecked(True)
    chk_videos = QCheckBox("Videos"); chk_videos.setChecked(True)
    chk_music = QCheckBox("Music"); chk_music.setChecked(True)
    chk_docs = QCheckBox("Documents"); chk_docs.setChecked(True)
    types_layout.addWidget(chk_images); types_layout.addWidget(chk_videos)
    types_layout.addWidget(chk_music); types_layout.addWidget(chk_docs)
    types_layout.addStretch()
    types_layout.addWidget(QLabel("Conflict:"))
    combo_migrate_conflict = QComboBox(); combo_migrate_conflict.addItems(["rename", "overwrite", "skip"])
    types_layout.addWidget(combo_migrate_conflict)
    m_layout.addLayout(types_layout)
    progress_migrate = QProgressBar()
    log_migrate = QTextEdit(); log_migrate.setReadOnly(True)
    m_layout.addWidget(progress_migrate); m_layout.addWidget(log_migrate)
    btn_start_migrate = QPushButton("Start Migrate")
    btn_start_migrate.setFixedWidth(160)
    m_layout.addWidget(btn_start_migrate, alignment=Qt.AlignRight)
    # --- Tab: Organize ---
    tab_organize = QWidget()
    tabs.addTab(tab_organize, "Organize")
    o_layout = QVBoxLayout(tab_organize)
    o_grid = QGridLayout()
    o_layout.addLayout(o_grid)
    lbl_root = QLabel("Directory:")
    edit_root = QLineEdit()
    btn_browse_root = QPushButton("Browse")
    o_grid.addWidget(lbl_root, 0, 0); o_grid.addWidget(edit_root, 0, 1); o_grid.addWidget(btn_browse_root, 0, 2)
    o_opts = QHBoxLayout()
    combo_mode = QComboBox(); combo_mode.addItems(["by_date", "by_ext"])
    combo_conflict = QComboBox(); combo_conflict.addItems(["rename", "overwrite", "skip"])
    o_opts.addWidget(QLabel("Mode:")); o_opts.addWidget(combo_mode)
    o_opts.addStretch()
    o_opts.addWidget(QLabel("Conflict:")); o_opts.addWidget(combo_conflict)
    o_layout.addLayout(o_opts)
    progress_organize = QProgressBar()
    log_organize = QTextEdit(); log_organize.setReadOnly(True)
    o_layout.addWidget(progress_organize); o_layout.addWidget(log_organize)
    btn_start_organize = QPushButton("Start Organize"); btn_start_organize.setFixedWidth(160)
    o_layout.addWidget(btn_start_organize, alignment=Qt.AlignRight)
    # --- Thread pool & state ---
    pool = QThreadPool.globalInstance()
    last_hashes = {}
    # --- UX helpers ---
    def append_log(widget: QTextEdit, text: str):
        widget.append(f"{datetime.now().strftime('%H:%M:%S')}  {text}")
    def choose_directory(line_edit: QLineEdit):
        d = QFileDialog.getExistingDirectory(window, "Select Directory", os.path.expanduser("~"))
        if d:
            line_edit.setText(d)
    # connect browse buttons
    btn_browse_scan.clicked.connect(lambda: choose_directory(edit_scan_dir))
    btn_browse_src.clicked.connect(lambda: choose_directory(edit_src))
    btn_browse_dst.clicked.connect(lambda: choose_directory(edit_dst))
    btn_browse_root.clicked.connect(lambda: choose_directory(edit_root))
    # --- Actions ---
    def on_scan_finished(result):
        nonlocal last_hashes
        last_hashes = result or {}
        dup_groups = sum(1 for v in last_hashes.values() if len(v) > 1)
        dup_files = sum(len(v)-1 for v in last_hashes.values() if len(v) > 1)
        append_log(log_scan, f"Scan finished: {len(last_hashes)} unique hashes, {dup_groups} duplicate groups, {dup_files} duplicate files.")
        progress_scan.setValue(100)
    def start_scan():
        root = edit_scan_dir.text().strip()
        if not root or not os.path.isdir(root):
            QMessageBox.warning(window, "Invalid Directory", "Please select a valid scan directory.")
            return
        exclude = [p.strip() for p in edit_exclude.text().split(";") if p.strip()]
        task, signals = make_scan_worker(root, exclude, follow_links=False)
        signals.progress.connect(progress_scan.setValue)
        signals.message.connect(lambda s: append_log(log_scan, s))
        signals.finished.connect(on_scan_finished)
        signals.error.connect(lambda e: append_log(log_scan, f"Error:\n{e}"))
        append_log(log_scan, "Start scanning...")
        pool.start(task)
    def start_delete():
        nonlocal last_hashes
        if not last_hashes:
            QMessageBox.information(window, "No Data", "No scan results available. Please scan first.")
            return
        keep = combo_keep.currentText()
        # confirmation with counts
        dup_groups = sum(1 for v in last_hashes.values() if len(v) > 1)
        dup_files = sum(len(v)-1 for v in last_hashes.values() if len(v) > 1)
        if dup_groups == 0:
            QMessageBox.information(window, "No Duplicates", "No duplicate files detected.")
            return
        reply = QMessageBox.question(window, "Confirm Delete",
                                     f"Detected {dup_groups} duplicate groups and {dup_files} duplicate files.\n"
                                     f"Keep strategy: {keep}.\nThis will permanently delete duplicates. Continue?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        task, signals = make_delete_worker(last_hashes, keep)
        signals.progress.connect(progress_scan.setValue)
        signals.message.connect(lambda s: append_log(log_scan, s))
        signals.finished.connect(lambda n: append_log(log_scan, f"Delete finished, deleted {n} files."))
        signals.error.connect(lambda e: append_log(log_scan, f"Error:\n{e}"))
        append_log(log_scan, "Start deleting duplicates...")
        pool.start(task)

    def start_migrate_action():
        src = edit_src.text().strip()
        dst = edit_dst.text().strip()
        if not src or not os.path.isdir(src):
            QMessageBox.warning(window, "Invalid Source", "Please select a valid source directory.")
            return
        if not dst:
            QMessageBox.warning(window, "Invalid Target", "Please select a target directory.")
            return
        os.makedirs(dst, exist_ok=True)
        keys = []
        if chk_images.isChecked(): keys.append("images")
        if chk_videos.isChecked(): keys.append("videos")
        if chk_music.isChecked(): keys.append("music")
        if chk_docs.isChecked(): keys.append("documents")
        conflict = combo_migrate_conflict.currentText()
        exclude = [p.strip() for p in edit_exclude.text().split(";") if p.strip()]
        # estimate file count (fast)
        estimated = sum(len(files) for _, _, files in os.walk(src))
        if estimated == 0:
            QMessageBox.information(window, "No Files", "No files found to migrate.")
            return
        reply = QMessageBox.question(window, "Confirm Migrate",
                                     f"This will move up to {estimated} files from:\n{src}\n to:\n{dst}\n"
                                     f"Types: {', '.join(keys) if keys else 'others only'}\nConflict: {conflict}\nProceed?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        task, signals = make_migrate_worker(src, dst, keys, conflict, exclude)
        signals.progress.connect(progress_migrate.setValue)
        signals.message.connect(lambda s: append_log(log_migrate, s))
        signals.finished.connect(lambda n: append_log(log_migrate, f"Migrate finished, moved {n} files."))
        signals.error.connect(lambda e: append_log(log_migrate, f"Error:\n{e}"))
        append_log(log_migrate, "Start migrating...")
        pool.start(task)
    def start_organize_action():
        root = edit_root.text().strip()
        if not root or not os.path.isdir(root):
            QMessageBox.warning(window, "Invalid Directory", "Please select a valid directory to organize.")
            return
        mode = combo_mode.currentText()
        conflict = combo_conflict.currentText()
        exclude = [p.strip() for p in edit_exclude.text().split(";") if p.strip()]
        estimated = sum(len(files) for _, _, files in os.walk(root))
        if estimated == 0:
            QMessageBox.information(window, "No Files", "No files found to organize.")
            return
        reply = QMessageBox.question(window, "Confirm Organize",
                                     f"This will move up to {estimated} files inside:\n{root}\nMode: {mode}\nConflict: {conflict}\nProceed?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        task, signals = make_organize_worker(root, mode, conflict, exclude)
        signals.progress.connect(progress_organize.setValue)
        signals.message.connect(lambda s: append_log(log_organize, s))
        signals.finished.connect(lambda n: append_log(log_organize, f"Organize finished, moved {n} files."))
        signals.error.connect(lambda e: append_log(log_organize, f"Error:\n{e}"))
        append_log(log_organize, "Start organizing...")
        pool.start(task)
    # connect UI buttons
    btn_scan.clicked.connect(start_scan)
    btn_delete.clicked.connect(start_delete)
    btn_start_migrate.clicked.connect(start_migrate_action)
    btn_start_organize.clicked.connect(start_organize_action)
    # polish layout spacing
    main_layout.addItem(QSpacerItem(20, 12))
    return window
# -------------------------
# Main
# -------------------------
def main():
    app = QApplication(sys.argv)
    apply_dark_style(app)
    window = create_main_window()
    window.show()
    sys.exit(app.exec_())
if __name__ == "__main__":
    main()
