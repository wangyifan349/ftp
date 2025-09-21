# interactive_chacha20poly1305_gui_pretty.py
import os
import sys
import pathlib
import secrets
from hashlib import sha256
from typing import List, Optional, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from functools import partial

from PyQt5 import QtCore, QtGui, QtWidgets
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

# ---------------------------
# Constants / File format
# ---------------------------
NONCE_SIZE = 12                # ChaCha20-Poly1305 nonce
SALT_SIZE = 16                 # salt for PBKDF2
CHUNK_SIZE = 64 * 1024         # 64KB
PBKDF2_ITERATIONS = 5000       # per your request
OUTPUT_SUFFIX = ".enc"         # encrypted file suffix

# File layout for encrypted file:
# [salt (16 bytes)] [nonce (12 bytes)] [ciphertext...]
# salt is per-file random, used to derive key from password.

# ---------------------------
# Crypto helpers
# ---------------------------
def derive_key_pbkdf2(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    """Derive 32-byte key using PBKDF2-HMAC-SHA256."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
        backend=default_backend(),
    )
    return kdf.derive(password.encode('utf-8'))

def encrypt_file_fileformat(input_path: pathlib.Path, password: str) -> None:
    """Encrypt a single file. Output file will be input + .enc.
       File layout: salt(16) | nonce(12) | ciphertext...
    """
    if input_path.suffix == OUTPUT_SUFFIX:
        return
    salt = secrets.token_bytes(SALT_SIZE)
    key = derive_key_pbkdf2(password, salt)
    nonce = secrets.token_bytes(NONCE_SIZE)
    aead = ChaCha20Poly1305(key)
    out_path = input_path.with_name(input_path.name + OUTPUT_SUFFIX)
    with input_path.open('rb') as fin, out_path.open('wb') as fout:
        fout.write(salt)
        fout.write(nonce)
        while True:
            chunk = fin.read(CHUNK_SIZE)
            if not chunk:
                break
            ct = aead.encrypt(nonce, chunk, None)
            fout.write(ct)
    input_path.unlink()  # remove original file

def decrypt_file_fileformat(enc_path: pathlib.Path, password: str) -> None:
    """Decrypt a single .enc file written by encrypt_file_fileformat."""
    if enc_path.suffix != OUTPUT_SUFFIX:
        return
    with enc_path.open('rb') as fin:
        salt = fin.read(SALT_SIZE)
        if len(salt) != SALT_SIZE:
            raise ValueError("Invalid encrypted file (missing salt).")
        nonce = fin.read(NONCE_SIZE)
        if len(nonce) != NONCE_SIZE:
            raise ValueError("Invalid encrypted file (missing nonce).")
        key = derive_key_pbkdf2(password, salt)
        aead = ChaCha20Poly1305(key)
        out_name = enc_path.name[:-len(OUTPUT_SUFFIX)]
        out_path = enc_path.with_name(out_name)
        with out_path.open('wb') as fout:
            while True:
                chunk = fin.read(CHUNK_SIZE + 16)  # ciphertext chunk + tag
                if not chunk:
                    break
                pt = aead.decrypt(nonce, chunk, None)
                fout.write(pt)
    enc_path.unlink()

def collect_files_recursive(root: str) -> List[pathlib.Path]:
    result: List[pathlib.Path] = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            result.append(pathlib.Path(dirpath) / name)
    return result

# ---------------------------
# Worker (runs in background thread)
# ---------------------------
class WorkerSignals(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, int)    # processed, total
    log = QtCore.pyqtSignal(str)              # log messages
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)

class FileWorker(QtCore.QObject):
    def __init__(self, root: str, password: str, mode: str, max_workers: Optional[int]):
        super().__init__()
        self.root = root
        self.password = password
        self.mode = mode  # 'encrypt' or 'decrypt'
        self.max_workers = max_workers
        self._should_stop = False
        self.signals = WorkerSignals()

    @QtCore.pyqtSlot()
    def run(self):
        try:
            all_files = collect_files_recursive(self.root)
            if self.mode == 'encrypt':
                targets = [p for p in all_files if p.suffix != OUTPUT_SUFFIX]
            else:
                targets = [p for p in all_files if p.suffix == OUTPUT_SUFFIX]
            total = len(targets)
            self.signals.log.emit(f"Found {total} file(s) to process.")
            if total == 0:
                self.signals.finished.emit()
                return

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_path: Dict[Future, pathlib.Path] = {}
                for p in targets:
                    if self._should_stop:
                        break
                    if self.mode == 'encrypt':
                        fut = executor.submit(encrypt_file_fileformat, p, self.password)
                    else:
                        fut = executor.submit(decrypt_file_fileformat, p, self.password)
                    future_to_path[fut] = p

                processed = 0
                for fut in as_completed(future_to_path):
                    if self._should_stop:
                        break
                    p = future_to_path[fut]
                    try:
                        fut.result()
                        self.signals.log.emit(f"[OK] {p}")
                    except Exception as exc:
                        self.signals.log.emit(f"[ERROR] {p}: {exc}")
                    processed += 1
                    self.signals.progress.emit(processed, total)

            if self._should_stop:
                self.signals.log.emit("Operation cancelled by user.")
            else:
                self.signals.log.emit("Operation completed.")
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit(str(e))
            self.signals.finished.emit()

    def stop(self):
        self._should_stop = True

# ---------------------------
# Pretty GUI
# ---------------------------
class PrettyMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChaCha20-Poly1305 Batch Encrypt/Decrypt")
        self.resize(820, 560)
        self._setup_ui()
        self.worker_thread: Optional[QtCore.QThread] = None
        self.file_worker: Optional[FileWorker] = None

    def _setup_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Header card
        header = QtWidgets.QFrame()
        header.setFrameShape(QtWidgets.QFrame.NoFrame)
        header.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #3b8ec2, stop:1 #2b6fa3); border-radius:8px;")
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        title = QtWidgets.QLabel("ChaCha20-Poly1305 批量加/解密")
        title.setStyleSheet("color:white; font-size:16px; font-weight:600;")
        subtitle = QtWidgets.QLabel("Uses PBKDF2 (5000 iterations) per-file salt. Files become .enc")
        subtitle.setStyleSheet("color: rgba(255,255,255,0.85);")
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(subtitle)
        main_layout.addWidget(header)

        # Form card
        card = QtWidgets.QFrame()
        card.setFrameShape(QtWidgets.QFrame.StyledPanel)
        card.setStyleSheet("QFrame{background:#f7f9fb; border-radius:8px;}")
        card_layout = QtWidgets.QGridLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setHorizontalSpacing(10)
        card_layout.setVerticalSpacing(8)

        # Mode
        card_layout.addWidget(QtWidgets.QLabel("Mode:"), 0, 0)
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["Encrypt", "Decrypt"])
        card_layout.addWidget(self.mode_combo, 0, 1)

        # Directory
        card_layout.addWidget(QtWidgets.QLabel("Target Directory:"), 1, 0)
        dir_h = QtWidgets.QHBoxLayout()
        self.dir_edit = QtWidgets.QLineEdit()
        btn_browse = QtWidgets.QPushButton("Browse")
        btn_browse.clicked.connect(self._on_browse)
        dir_h.addWidget(self.dir_edit)
        dir_h.addWidget(btn_browse)
        card_layout.addLayout(dir_h, 1, 1)

        # Password
        card_layout.addWidget(QtWidgets.QLabel("Password:"), 2, 0)
        self.password_edit = QtWidgets.QLineEdit()
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        card_layout.addWidget(self.password_edit, 2, 1)

        # Thread count
        card_layout.addWidget(QtWidgets.QLabel("Threads (empty = CPU cores):"), 3, 0)
        self.threads_edit = QtWidgets.QLineEdit()
        self.threads_edit.setPlaceholderText("e.g. 4")
        card_layout.addWidget(self.threads_edit, 3, 1)

        # Start/Stop buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Start")
        self.start_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaStop))
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        btn_layout.addStretch()
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        card_layout.addLayout(btn_layout, 4, 0, 1, 2)

        main_layout.addWidget(card)

        # Progress and log area (splitter)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        # Progress bar with summary
        prog_widget = QtWidgets.QWidget()
        prog_layout = QtWidgets.QHBoxLayout(prog_widget)
        prog_layout.setContentsMargins(6, 6, 6, 6)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setValue(0)
        self.status_label = QtWidgets.QLabel("Idle")
        prog_layout.addWidget(self.progress_bar)
        prog_layout.addWidget(self.status_label)
        splitter.addWidget(prog_widget)

        # Log
        self.log_edit = QtWidgets.QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        font = QtGui.QFont("Monospace")
        font.setPointSize(10)
        self.log_edit.setFont(font)
        splitter.addWidget(self.log_edit)
        splitter.setStretchFactor(1, 3)
        main_layout.addWidget(splitter)

        # Status bar
        status_bar = QtWidgets.QStatusBar()
        self.setStatusBar(status_bar)
        status_bar.showMessage("Ready")

        # Shortcuts and polish
        self.password_edit.returnPressed.connect(self._on_start_clicked)

    def _append_log(self, text: str):
        self.log_edit.appendPlainText(text)
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select target directory", os.path.expanduser("~"))
        if d:
            self.dir_edit.setText(d)

    def _on_start_clicked(self):
        target_dir = self.dir_edit.text().strip()
        if not target_dir or not os.path.isdir(target_dir):
            QtWidgets.QMessageBox.critical(self, "Invalid Directory", "Please select a valid target directory.")
            return
        password = self.password_edit.text()
        if not password:
            QtWidgets.QMessageBox.critical(self, "Missing Password", "Please enter a password for key derivation.")
            return

        # confirm destructive action
        mode_name = self.mode_combo.currentText()
        warning = (f"You are about to {mode_name.lower()} files under:\n\n{target_dir}\n\n"
                   "This operation will replace original files (encrypted files will get '.enc' suffix).\n"
                   "Make sure you have backups. Continue?")
        reply = QtWidgets.QMessageBox.warning(self, f"Confirm {mode_name}", warning,
                                              QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                              QtWidgets.QMessageBox.No)
        if reply != QtWidgets.QMessageBox.Yes:
            return

        # parse threads
        threads_text = self.threads_edit.text().strip()
        max_workers: Optional[int]
        if threads_text == "":
            max_workers = None
        else:
            if not threads_text.isdigit() or int(threads_text) <= 0:
                QtWidgets.QMessageBox.critical(self, "Invalid Threads", "Threads must be a positive integer.")
                return
            max_workers = int(threads_text)

        # UI state
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("Running...")
        self.log_edit.clear()
        self._append_log("Task started.")

        mode = 'encrypt' if self.mode_combo.currentText() == 'Encrypt' else 'decrypt'
        self.file_worker = FileWorker(target_dir, password, mode, max_workers)
        self.worker_thread = QtCore.QThread()
        self.file_worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.file_worker.run)
        self.file_worker.signals.progress.connect(self._on_progress)
        self.file_worker.signals.log.connect(self._append_log)
        self.file_worker.signals.finished.connect(self._on_finished)
        self.file_worker.signals.error.connect(lambda e: self._append_log(f"[FATAL] {e}"))
        self.worker_thread.start()

    def _on_stop_clicked(self):
        if self.file_worker:
            self.file_worker.stop()
            self._append_log("Cancellation requested; waiting for active tasks to finish...")
            self.stop_btn.setEnabled(False)

    def _on_progress(self, processed: int, total: int):
        pct = int(processed * 100 / total) if total else 0
        self.progress_bar.setValue(pct)
        self.status_label.setText(f"{processed}/{total} ({pct}%)")
        self.statusBar().showMessage(f"Processing: {processed}/{total}")

    def _on_finished(self):
        self._append_log("Task finished.")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.statusBar().showMessage("Ready")
        # clean up thread
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()
        self.worker_thread = None
        self.file_worker = None

def main():
    app = QtWidgets.QApplication(sys.argv)
    # optional: set Fusion style + palette for nicer look
    QtWidgets.QApplication.setStyle("Fusion")
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#eef2f5"))
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#222222"))
    app.setPalette(palette)

    w = PrettyMainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
