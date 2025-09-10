#!/usr/bin/env python3
"""
organize_media_gui_en.py

Media Organizer (PyQt5 GUI)
Features:
- Select multiple source directories (recursive).
- Select a destination directory.
- Classify files by extension into Videos/ Audios/ Images/ Others.
- Copy or move files.
- Deduplicate files based on SHA-256 (size grouping then hash).
- Optionally delete duplicate source files.
- Dry-run (simulation) mode.
- Background worker thread (QThread) to avoid UI blocking.
- Themed stylesheet (soft green + soft gold).
- All identifiers and comments are in English.
Requirements:
    pip install PyQt5
Usage:
    python organize_media_gui_en.py
"""
import sys
import shutil
import hashlib
import traceback
from pathlib import Path
from typing import List, Set, Dict, Optional

from PyQt5 import QtWidgets, QtCore, QtGui

# ---------------- Configuration ----------------
VIDEO_EXTS: Set[str] = {
    "mp4", "mkv", "mov", "avi", "wmv", "flv", "webm", "mpeg", "mpg", "m4v"
}
AUDIO_EXTS: Set[str] = {
    "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma"
}
IMAGE_EXTS: Set[str] = {
    "jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "heic"
}
TARGET_SUBDIRS = {
    "video": "Videos",
    "audio": "Audios",
    "image": "Images",
    "other": "Others"
}

# Block size for hashing large files (4 MiB)
HASH_BLOCK_SIZE = 4 * 1024 * 1024
# ------------------------------------------------
def classify_by_extension(path: Path) -> str:
    """Return category key based on file extension."""
    ext = path.suffix.lower().lstrip(".")
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        return "image"
    return "other"
def unique_target_path(destination_dir: Path, filename: str) -> Path:
    """
    Generate a non-conflicting target Path in destination_dir.
    If filename exists, append ' (1)', ' (2)', ... before the extension.
    """
    base = Path(filename)
    stem = base.stem
    suffix = base.suffix  # includes dot, e.g. ".mp4"
    candidate = destination_dir / filename
    counter = 1
    while candidate.exists():
        candidate = destination_dir / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate
def collect_files(source_dirs: List[Path], status_callback=None) -> List[Path]:
    """
    Recursively collect files from source_dirs.
    status_callback(optional): callable(str) to receive progress messages.
    """
    files = []
    for d in source_dirs:
        if not d.exists():
            if status_callback:
                status_callback(f"Source not found: {d}")
            continue
        if d.is_file():
            files.append(d)
            continue
        for p in d.rglob("*"):
            if p.is_file():
                files.append(p)
                if status_callback and len(files) % 200 == 0:
                    status_callback(f"Scanning... found {len(files)} files")
    return files
def sha256_hash(path: Path, block_size: int = HASH_BLOCK_SIZE) -> str:
    """Compute SHA-256 hash of a file in streaming manner."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(block_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
# ---------------- Worker Thread ----------------
class OrganizerWorker(QtCore.QThread):
    """
    QThread worker that performs scanning, deduplication, copy/move operations.
    Communicates with GUI via Qt signals.
    """
    signal_progress = QtCore.pyqtSignal(int, int)    # processed, total
    signal_log = QtCore.pyqtSignal(str)              # log lines
    signal_stats = QtCore.pyqtSignal(dict)           # periodic stats
    signal_finished = QtCore.pyqtSignal(dict)        # summary on success
    signal_error = QtCore.pyqtSignal(str)            # error or cancellation

    def __init__(self,
                 source_dirs: List[Path],
                 destination_root: Path,
                 mode: str = "copy",                 # "copy" or "move"
                 dedupe: bool = True,
                 delete_duplicates: bool = False,    # delete duplicate files from source when True
                 dry_run: bool = False):
        super().__init__()
        self.source_dirs = source_dirs
        self.destination_root = destination_root
        self.mode = mode
        self.dedupe = dedupe
        self.delete_duplicates = delete_duplicates
        self.dry_run = dry_run
        self._cancel_requested = False

        # statistics
        self._total = 0
        self._processed = 0
        self._copied = 0
        self._moved = 0
        self._skipped = 0
        self._duplicates = 0
        self._errors = 0

    def request_cancel(self):
        """Request thread cancellation; worker cooperatively checks this flag."""
        self._cancel_requested = True

    def _emit_stats(self):
        """Emit current stats as a dict."""
        self.signal_stats.emit({
            "total": self._total,
            "processed": self._processed,
            "copied": self._copied,
            "moved": self._moved,
            "skipped": self._skipped,
            "duplicates": self._duplicates,
            "errors": self._errors
        })

    def run(self):
        try:
            self.signal_log.emit(f"Worker starting. mode={self.mode}, dedupe={self.dedupe}, delete_duplicates={self.delete_duplicates}, dry_run={self.dry_run}")
            if not self.dry_run:
                self.destination_root.mkdir(parents=True, exist_ok=True)

            # Collect files
            files = collect_files(self.source_dirs, status_callback=lambda s: self.signal_log.emit(s))
            self._total = len(files)
            if self._total == 0:
                self.signal_log.emit("No files found. Exiting.")
                self.signal_finished.emit({"message": "no files", "stats": {}})
                return

            # If dedupe requested, group by file size first to reduce hashes
            size_groups: Dict[int, List[Path]] = {}
            for p in files:
                try:
                    size_groups.setdefault(p.stat().st_size, []).append(p)
                except Exception as e:
                    self.signal_log.emit(f"Failed to stat file {p}: {e}")
                    self._errors += 1

            # Build a hash map of unique files (hash -> representative path)
            hash_map: Dict[str, Path] = {}
            if self.dedupe:
                self.signal_log.emit("Starting deduplication scan (size grouping then SHA-256)...")
                for size, group in size_groups.items():
                    if self._cancel_requested:
                        self.signal_log.emit("Cancellation requested during dedupe scan.")
                        self.signal_error.emit("Cancelled")
                        return
                    if len(group) == 1:
                        p = group[0]
                        try:
                            h = sha256_hash(p)
                            hash_map.setdefault(h, p)
                        except Exception as e:
                            self.signal_log.emit(f"Hash failed for {p}: {e}")
                            self._errors += 1
                    else:
                        for p in group:
                            if self._cancel_requested:
                                self.signal_log.emit("Cancellation requested during dedupe scan.")
                                self.signal_error.emit("Cancelled")
                                return
                            try:
                                h = sha256_hash(p)
                                if h in hash_map:
                                    # duplicate discovered
                                    self._duplicates += 1
                                    self.signal_log.emit(f"Duplicate discovered: {p} (same as {hash_map[h]})")
                                else:
                                    hash_map[h] = p
                            except Exception as e:
                                self.signal_log.emit(f"Hash failed for {p}: {e}")
                                self._errors += 1

                self.signal_log.emit(f"Deduplication scan complete. Duplicates found: {self._duplicates}")

            # Copy/move phase
            self._processed = 0
            for p in files:
                if self._cancel_requested:
                    self.signal_log.emit("Cancellation requested. Stopping operations.")
                    self.signal_error.emit("Cancelled")
                    return

                category = classify_by_extension(p)
                subdir = TARGET_SUBDIRS.get(category, TARGET_SUBDIRS["other"])
                dest_dir = self.destination_root / subdir
                if not self.dry_run:
                    dest_dir.mkdir(parents=True, exist_ok=True)

                # Dedup check for current file
                is_duplicate = False
                representative = None
                if self.dedupe:
                    try:
                        h = sha256_hash(p)
                        rep = hash_map.get(h)
                        # If rep exists and is not this path, it's a duplicate
                        if rep is not None and rep != p:
                            is_duplicate = True
                            representative = rep
                    except Exception as e:
                        self.signal_log.emit(f"Hash failed for {p} during operation: {e}")
                        self._errors += 1

                if is_duplicate:
                    self._skipped += 1
                    if self.delete_duplicates and not self.dry_run:
                        try:
                            p.unlink()
                            self.signal_log.emit(f"Deleted duplicate source file: {p} (duplicate of {representative})")
                        except Exception as e:
                            self.signal_log.emit(f"Failed to delete duplicate {p}: {e}")
                            self._errors += 1
                    else:
                        self.signal_log.emit(f"Skipped duplicate: {p} (duplicate of {representative})")
                    self._processed += 1
                    self.signal_progress.emit(self._processed, self._total)
                    self._emit_stats()
                    continue

                # Not a duplicate -> perform copy or move
                target_path = unique_target_path(dest_dir, p.name)
                try:
                    if self.dry_run:
                        self.signal_log.emit(f"DRY-RUN: {p} -> {target_path}")
                        self._skipped += 1
                    else:
                        if self.mode == "move":
                            shutil.move(str(p), str(target_path))
                            self._moved += 1
                            self.signal_log.emit(f"MOVED: {p} -> {target_path}")
                        else:
                            shutil.copy2(str(p), str(target_path))
                            self._copied += 1
                            self.signal_log.emit(f"COPIED: {p} -> {target_path}")
                except Exception as e:
                    self.signal_log.emit(f"Error processing {p}: {e}")
                    self._errors += 1

                self._processed += 1
                self.signal_progress.emit(self._processed, self._total)
                if self._processed % 20 == 0:
                    self._emit_stats()

            # Finalize
            self._emit_stats()
            summary = {
                "total": self._total,
                "copied": self._copied,
                "moved": self._moved,
                "skipped": self._skipped,
                "duplicates": self._duplicates,
                "errors": self._errors
            }
            self.signal_log.emit(f"Worker finished: {summary}")
            self.signal_finished.emit(summary)
        except Exception as e:
            tb = traceback.format_exc()
            self.signal_log.emit(f"Unhandled exception in worker: {e}\n{tb}")
            self.signal_error.emit(str(e))
# ---------------- GUI ----------------
class MainWindow(QtWidgets.QWidget):
    """Main application window for the media organizer GUI."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Organizer")
        self.resize(900, 640)
        self._worker: Optional[OrganizerWorker] = None
        self._setup_ui()
        self._apply_stylesheet()

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)

        # Header
        header_layout = QtWidgets.QHBoxLayout()
        title_label = QtWidgets.QLabel("Media Organizer")
        title_label.setFont(QtGui.QFont("Segoe UI", 16, QtGui.QFont.Bold))
        subtitle_label = QtWidgets.QLabel("Copy / Move / Deduplicate (SHA-256)")
        subtitle_label.setStyleSheet("color: #555;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(subtitle_label)
        main_layout.addLayout(header_layout)

        # Split layout: left controls, right log
        split_layout = QtWidgets.QHBoxLayout()
        left_layout = QtWidgets.QVBoxLayout()
        right_layout = QtWidgets.QVBoxLayout()

        # Source selection group
        src_group = QtWidgets.QGroupBox("Source Directories (recursive)")
        src_group_layout = QtWidgets.QVBoxLayout()
        self.src_list = QtWidgets.QListWidget()
        self.src_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        src_btn_layout = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("Add")
        btn_add.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DirOpenIcon))
        btn_remove = QtWidgets.QPushButton("Remove")
        btn_clear = QtWidgets.QPushButton("Clear")
        src_btn_layout.addWidget(btn_add)
        src_btn_layout.addWidget(btn_remove)
        src_btn_layout.addWidget(btn_clear)
        src_group_layout.addWidget(self.src_list)
        src_group_layout.addLayout(src_btn_layout)
        src_group.setLayout(src_group_layout)
        left_layout.addWidget(src_group)

        # Destination selection
        dest_group = QtWidgets.QGroupBox("Destination Directory")
        dest_group_layout = QtWidgets.QHBoxLayout()
        self.dest_lineedit = QtWidgets.QLineEdit()
        btn_browse_dest = QtWidgets.QPushButton("Browse")
        btn_browse_dest.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DirIcon))
        dest_group_layout.addWidget(self.dest_lineedit)
        dest_group_layout.addWidget(btn_browse_dest)
        dest_group.setLayout(dest_group_layout)
        left_layout.addWidget(dest_group)

        # Options group
        options_group = QtWidgets.QGroupBox("Options")
        options_layout = QtWidgets.QGridLayout()
        self.radio_copy = QtWidgets.QRadioButton("Copy")
        self.radio_copy.setChecked(True)
        self.radio_move = QtWidgets.QRadioButton("Move")
        self.checkbox_dedupe = QtWidgets.QCheckBox("Deduplicate by content (SHA-256)")
        self.checkbox_delete_dup = QtWidgets.QCheckBox("Delete duplicate source files (dangerous)")
        self.checkbox_dryrun = QtWidgets.QCheckBox("Dry-run (simulate only)")
        options_layout.addWidget(self.radio_copy, 0, 0)
        options_layout.addWidget(self.radio_move, 0, 1)
        options_layout.addWidget(self.checkbox_dedupe, 1, 0, 1, 2)
        options_layout.addWidget(self.checkbox_delete_dup, 2, 0, 1, 2)
        options_layout.addWidget(self.checkbox_dryrun, 3, 0, 1, 2)
        options_group.setLayout(options_layout)
        left_layout.addWidget(options_group)

        # Control buttons
        control_layout = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Start")
        self.btn_start.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DialogCloseButton))
        self.btn_cancel.setEnabled(False)
        control_layout.addWidget(self.btn_start)
        control_layout.addWidget(self.btn_cancel)
        left_layout.addLayout(control_layout)

        # Statistics panel
        stats_group = QtWidgets.QGroupBox("Statistics")
        stats_layout = QtWidgets.QFormLayout()
        self.lbl_total = QtWidgets.QLabel("0")
        self.lbl_processed = QtWidgets.QLabel("0")
        self.lbl_copied = QtWidgets.QLabel("0")
        self.lbl_moved = QtWidgets.QLabel("0")
        self.lbl_skipped = QtWidgets.QLabel("0")
        self.lbl_duplicates = QtWidgets.QLabel("0")
        self.lbl_errors = QtWidgets.QLabel("0")
        stats_layout.addRow("Total files:", self.lbl_total)
        stats_layout.addRow("Processed:", self.lbl_processed)
        stats_layout.addRow("Copied:", self.lbl_copied)
        stats_layout.addRow("Moved:", self.lbl_moved)
        stats_layout.addRow("Skipped:", self.lbl_skipped)
        stats_layout.addRow("Duplicates:", self.lbl_duplicates)
        stats_layout.addRow("Errors:", self.lbl_errors)
        stats_group.setLayout(stats_layout)
        left_layout.addWidget(stats_group)

        split_layout.addLayout(left_layout, 3)

        # Right: Log and progress
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        right_layout.addWidget(self.log_text)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setValue(0)
        right_layout.addWidget(self.progress_bar)

        split_layout.addLayout(right_layout, 5)
        main_layout.addLayout(split_layout)

        # Connect signals to slots
        btn_add.clicked.connect(self.add_source_directory)
        btn_remove.clicked.connect(self.remove_selected_sources)
        btn_clear.clicked.connect(lambda: self.src_list.clear())
        btn_browse_dest.clicked.connect(self.browse_destination_directory)
        self.btn_start.clicked.connect(self.start_task)
        self.btn_cancel.clicked.connect(self.cancel_task)

    def _apply_stylesheet(self):
        """Apply a soft green + soft gold themed stylesheet for aesthetics."""
        stylesheet = """
        QWidget {
            background: qlineargradient(x1:0 y1:0, x2:1 y2:1,
                        stop:0 #f6fff6, stop:1 #fffdf5);
            font-family: "Segoe UI", "Arial", "Helvetica", sans-serif;
            font-size: 12px;
        }
        QGroupBox {
            border: 1px solid #e6e6d8;
            border-radius: 6px;
            margin-top: 6px;
            padding: 8px;
            background: rgba(255,255,255,0.7);
        }
        QGroupBox:title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 3px 0 3px;
            color: #556b2f;
            font-weight: bold;
        }
        QPushButton {
            background: qlineargradient(x1:0 y1:0, x2:0 y2:1,
                        stop:0 #e8f8e8, stop:1 #f7f2e8);
            border: 1px solid #cfe6c7;
            padding: 6px 10px;
            border-radius: 6px;
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0 y1:0, x2:0 y2:1,
                        stop:0 #d7f0d7, stop:1 #efe6c7);
        }
        QLineEdit, QPlainTextEdit, QListWidget {
            background: #ffffff;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 4px;
        }
        QProgressBar {
            border: 1px solid #c7d9c7;
            border-radius: 6px;
            text-align: center;
            height: 18px;
            background: #fff;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0 y1:0, x2:1 y2:0,
                        stop:0 #bfe6b0, stop:1 #f0d78a);
            border-radius: 6px;
        }
        """
        self.setStyleSheet(stylesheet)
    # ---------------- UI helper methods ----------------
    def add_source_directory(self):
        """Open directory chooser to add a source directory."""
        dialog = QtWidgets.QFileDialog(self, "Select Source Directory")
        dialog.setFileMode(QtWidgets.QFileDialog.Directory)
        dialog.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        if dialog.exec_():
            for folder in dialog.selectedFiles():
                if not any(self.src_list.item(i).text() == folder for i in range(self.src_list.count())):
                    self.src_list.addItem(folder)
    def remove_selected_sources(self):
        """Remove selected items from source list."""
        for item in self.src_list.selectedItems():
            self.src_list.takeItem(self.src_list.row(item))

    def browse_destination_directory(self):
        """Open directory chooser to set destination directory."""
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Destination Directory", "")
        if d:
            self.dest_lineedit.setText(d)
    def append_log(self, text: str):
        """Append a line to the log widget (thread-safe via signal)."""
        self.log_text.appendPlainText(text)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    # ---------------- Task control ----------------
    def start_task(self):
        """Create and start the OrganizerWorker thread with current options."""
        if self._worker and self._worker.isRunning():
            QtWidgets.QMessageBox.information(self, "Running", "A task is already running. Cancel or wait for it to finish.")
            return

        sources = [Path(self.src_list.item(i).text()) for i in range(self.src_list.count())]
        if not sources:
            QtWidgets.QMessageBox.warning(self, "No sources", "Please add at least one source directory.")
            return
        dest = self.dest_lineedit.text().strip()
        if not dest:
            QtWidgets.QMessageBox.warning(self, "No destination", "Please select a destination directory.")
            return
        dest_path = Path(dest).expanduser().resolve()

        mode = "move" if self.radio_move.isChecked() else "copy"
        dedupe = self.checkbox_dedupe.isChecked()
        delete_dup = self.checkbox_delete_dup.isChecked()
        dry_run = self.checkbox_dryrun.isChecked()

        # Disable controls while running
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self._reset_stats_labels()
        self.append_log(f"Preparing to start. mode={mode}, dedupe={dedupe}, delete_duplicates={delete_dup}, dry_run={dry_run}")

        # Create worker and connect signals
        self._worker = OrganizerWorker(
            source_dirs=sources,
            destination_root=dest_path,
            mode=mode,
            dedupe=dedupe,
            delete_duplicates=delete_dup,
            dry_run=dry_run
        )
        self._worker.signal_progress.connect(self.on_progress)
        self._worker.signal_log.connect(self.append_log)
        self._worker.signal_stats.connect(self.on_stats)
        self._worker.signal_finished.connect(self.on_finished)
        self._worker.signal_error.connect(self.on_error)
        self._worker.start()

    def cancel_task(self):
        """Request cancellation of the running worker."""
        if self._worker:
            self._worker.request_cancel()
            self.append_log("Cancellation requested. Waiting for worker to stop...")
            self.btn_cancel.setEnabled(False)
    # ---------------- Slots for worker signals ----------------
    def on_progress(self, processed: int, total: int):
        """Update progress bar and processed/total labels."""
        self.lbl_processed.setText(str(processed))
        self.lbl_total.setText(str(total))
        if total > 0:
            pct = int(processed * 100 / total)
            self.progress_bar.setValue(pct)
        else:
            self.progress_bar.setValue(0)

    def on_stats(self, stats: dict):
        """Update statistics labels."""
        self.lbl_total.setText(str(stats.get("total", 0)))
        self.lbl_processed.setText(str(stats.get("processed", 0)))
        self.lbl_copied.setText(str(stats.get("copied", 0)))
        self.lbl_moved.setText(str(stats.get("moved", 0)))
        self.lbl_skipped.setText(str(stats.get("skipped", 0)))
        self.lbl_duplicates.setText(str(stats.get("duplicates", 0)))
        self.lbl_errors.setText(str(stats.get("errors", 0)))

    def on_finished(self, summary: dict):
        """Handle successful completion."""
        self.append_log(f"Finished: {summary}")
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setValue(100)

    def on_error(self, message: str):
        """Handle cancellation or error."""
        self.append_log(f"Worker ended with error or cancellation: {message}")
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def _reset_stats_labels(self):
        """Reset stat labels to zero."""
        self.lbl_total.setText("0")
        self.lbl_processed.setText("0")
        self.lbl_copied.setText("0")
        self.lbl_moved.setText("0")
        self.lbl_skipped.setText("0")
        self.lbl_duplicates.setText("0")
        self.lbl_errors.setText("0")
# ---------------- Entry point ----------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
if __name__ == "__main__":
    main()
