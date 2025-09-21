#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Secure Notepad — PyQt5 version
Features:
 - AES-GCM encryption with PBKDF2-derived key, Base58 file encoding (compatible with prior implementation)
 - Open / Save / Save As (.snoteb58)
 - Find / Replace with optional case-sensitive matching and case-insensitive whole-match replace behavior
 - Highlight all matches (yellow background, black text) and current match (blue background, white text)
 - Font size controls (increase / decrease / reset)
 - Responsive UI (background file IO and crypto via QThread)
 - Dark theme; stylesheet-customizable
 - Clear, documented code with standardized comments suitable for open-source maintenance

Dependencies:
    pip install PyQt5 pycryptodome base58
Run:
    python secure_notepad_qt5_improved.py
"""
import sys
import os
import struct
from typing import Optional, Tuple, List
from PyQt5 import QtWidgets, QtGui, QtCore
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes
import base58
# -----------------------------
# Configuration constants
# -----------------------------
PBKDF2_ITERATIONS = 5000
SALT_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16
MAGIC_HEADER = b'SNOTE1.0'
FORMAT_VERSION = 1
DEFAULT_FONT_FAMILY = (
    "Consolas" if "Consolas" in QtGui.QFontDatabase().families() else "Courier"
)
DEFAULT_FONT_SIZE = 14
DEFAULT_EXTENSION = ".snoteb58"
STATUS_MSG_DURATION_MS = 5000
# -----------------------------
# Cryptography helpers
# -----------------------------
def derive_key(password: str, salt: bytes, key_len: int = 32) -> bytes:
    """
    Derive a symmetric key from a password using PBKDF2 (SHA1).
    Args:
        password: input password string.
        salt: salt bytes (SALT_BYTES length recommended).
        key_len: desired output key length in bytes.
    Returns:
        Derived key bytes.
    """
    return PBKDF2(password.encode("utf-8"), salt, dkLen=key_len, count=PBKDF2_ITERATIONS)
def encrypt_bytes_to_base58(plaintext: bytes, password: str) -> bytes:
    """
    Encrypt plaintext with AES-GCM and encode container in Base58.
    Container format (binary):
      MAGIC_HEADER (8 bytes) | version (1 byte) | salt (SALT_BYTES) |
      nonce (NONCE_BYTES) | ciphertext_length (8 bytes big-endian) |
      ciphertext | tag (TAG_BYTES)
    Returns:
        Base58-encoded bytes ready to write to file.
    """
    salt = get_random_bytes(SALT_BYTES)
    key = derive_key(password, salt)
    nonce = get_random_bytes(NONCE_BYTES)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    parts = [
        MAGIC_HEADER,
        struct.pack("B", FORMAT_VERSION),
        salt,
        nonce,
        struct.pack(">Q", len(ciphertext)),
        ciphertext,
        tag,
    ]
    raw = b"".join(parts)
    return base58.b58encode(raw)
def decrypt_base58_to_bytes(b58data: bytes, password: str) -> bytes:
    """
    Decode Base58 container and decrypt AES-GCM ciphertext.
    Raises:
        ValueError on unsupported format/version or InvalidTag for wrong password/tag.
    Returns:
        plaintext bytes.
    """
    raw = base58.b58decode(b58data)
    off = 0
    if raw[0: len(MAGIC_HEADER)] != MAGIC_HEADER:
        raise ValueError("Unsupported file format")
    off += len(MAGIC_HEADER)
    ver = raw[off]
    off += 1
    if ver != FORMAT_VERSION:
        raise ValueError("Unsupported version")
    salt = raw[off: off + SALT_BYTES]
    off += SALT_BYTES
    nonce = raw[off: off + NONCE_BYTES]
    off += NONCE_BYTES
    (ct_len,) = struct.unpack(">Q", raw[off: off + 8])
    off += 8
    ciphertext = raw[off: off + ct_len]
    off += ct_len
    tag = raw[off: off + TAG_BYTES]
    key = derive_key(password, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)
# -----------------------------
# Worker threads for file IO and crypto
# -----------------------------
class FileLoadResult(QtCore.QObject):
    """Signals container for file load thread result."""
    finished = QtCore.pyqtSignal(bytes)
    error = QtCore.pyqtSignal(Exception)
class FileLoadWorker(QtCore.QRunnable):
    """
    Worker to read and decrypt file off the UI thread.
    Emits signals via the provided FileLoadResult.
    """
    def __init__(self, path: str, password: str, result_emitter: FileLoadResult):
        super().__init__()
        self.path = path
        self.password = password
        self.emitter = result_emitter
    @QtCore.pyqtSlot()
    def run(self):
        try:
            with open(self.path, "rb") as f:
                data = f.read()
            plaintext = decrypt_base58_to_bytes(data, self.password)
            self.emitter.finished.emit(plaintext)
        except Exception as e:
            self.emitter.error.emit(e)
class FileSaveResult(QtCore.QObject):
    """Signals container for file save thread result."""
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(Exception)
class FileSaveWorker(QtCore.QRunnable):
    """
    Worker to encrypt and write file off the UI thread.
    Emits signals via the provided FileSaveResult.
    """
    def __init__(self, path: str, password: str, plaintext: bytes, result_emitter: FileSaveResult):
        super().__init__()
        self.path = path
        self.password = password
        self.plaintext = plaintext
        self.emitter = result_emitter
    @QtCore.pyqtSlot()
    def run(self):
        try:
            b58 = encrypt_bytes_to_base58(self.plaintext, self.password)
            with open(self.path, "wb") as f:
                f.write(b58)
            self.emitter.finished.emit()
        except Exception as e:
            self.emitter.error.emit(e)
# -----------------------------
# Simple password dialog
# -----------------------------
class PasswordDialog(QtWidgets.QDialog):
    """
    Modal dialog to request a password. Supports optional confirmation.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, confirm: bool = False, title: str = "Password",
                 prompt: str = "Enter password:"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._value: Optional[str] = None
        self._confirm = confirm
        self._build_ui(prompt)
    def _build_ui(self, prompt: str):
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(prompt, self)
        layout.addWidget(label)
        self.edit_password = QtWidgets.QLineEdit(self)
        self.edit_password.setEchoMode(QtWidgets.QLineEdit.Password)
        layout.addWidget(self.edit_password)
        self.edit_confirm = None
        if self._confirm:
            self.edit_confirm = QtWidgets.QLineEdit(self)
            self.edit_confirm.setEchoMode(QtWidgets.QLineEdit.Password)
            self.edit_confirm.setPlaceholderText("Confirm password")
            layout.addWidget(self.edit_confirm)
        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
                                                parent=self)
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        self.resize(420, 120)
    def _on_accept(self):
        pw = self.edit_password.text()
        if self._confirm:
            pw2 = self.edit_confirm.text() if self.edit_confirm else ""
            if pw == "":
                QtWidgets.QMessageBox.critical(self, "Error", "Password cannot be empty")
                return
            if pw != pw2:
                QtWidgets.QMessageBox.critical(self, "Error", "Passwords do not match")
                return
        self._value = pw
        self.accept()
    def value(self) -> Optional[str]:
        return self._value
# -----------------------------
# Highlighter utilities
# -----------------------------
def create_format(background: QtGui.QColor, foreground: QtGui.QColor) -> QtGui.QTextCharFormat:
    """
    Create a QTextCharFormat with given background and foreground colors.
    """
    fmt = QtGui.QTextCharFormat()
    fmt.setBackground(QtGui.QBrush(background))
    fmt.setForeground(QtGui.QBrush(foreground))
    return fmt
class FinderHighlighter:
    """
    Manages extra selections on a QTextEdit for match highlighting.
    - All matches: light yellow background + black text.
    - Current match: blue background + white text.
    """

    def __init__(self, text_edit: QtWidgets.QTextEdit):
        self._text_edit = text_edit
        self._all_match_format = create_format(QtGui.QColor("#FFF59D"), QtGui.QColor("#000000"))
        self._current_format = create_format(QtGui.QColor("#1976D2"), QtGui.QColor("#FFFFFF"))

    def clear(self) -> None:
        """
        Clear all extra selections.
        """
        self._text_edit.setExtraSelections([])

    def highlight_all(self, pattern: str, case_sensitive: bool = False) -> int:
        """
        Highlight all occurrences of pattern. Returns number of matches.
        """
        self.clear()
        if not pattern:
            return 0
        doc = self._text_edit.document()
        flags = QtGui.QTextDocument.FindFlags()
        if case_sensitive:
            flags |= QtGui.QTextDocument.FindCaseSensitively

        cursor = doc.find(pattern, 0, flags)
        selections: List[QtWidgets.QTextEdit.ExtraSelection] = []
        count = 0
        while not cursor.isNull():
            sel = QtWidgets.QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = self._all_match_format
            selections.append(sel)
            count += 1
            # continue after current match
            cursor = doc.find(pattern, cursor.selectionEnd(), flags)
        self._text_edit.setExtraSelections(selections)
        return count
    def highlight_current(self, cursor: QtGui.QTextCursor) -> None:
        """
        Mark the current cursor selection as the current match with the current format.
        Keeps other matches intact.
        """
        existing = self._text_edit.extraSelections()
        # Remove prior 'current' marker if present
        remaining = [s for s in existing if not getattr(s, "_is_current_marker", False)]
        # Create new current marker
        sel = QtWidgets.QTextEdit.ExtraSelection()
        sel.cursor = cursor
        sel.format = self._current_format
        setattr(sel, "_is_current_marker", True)
        remaining.append(sel)
        self._text_edit.setExtraSelections(remaining)
# -----------------------------
# Main window
# -----------------------------
class MainWindow(QtWidgets.QMainWindow):
    """
    Main application window.
    Contains: QTextEdit, toolbar, status bar, find/replace dialog, and background workers for IO.
    """

    def __init__(self):
        super().__init__()
        self._current_path: Optional[str] = None
        self._font_family = DEFAULT_FONT_FAMILY
        self._font_size = DEFAULT_FONT_SIZE
        self._thread_pool = QtCore.QThreadPool.globalInstance()

        self._init_ui()
        # Highlighter
        self._finder = FinderHighlighter(self.text_edit)
        # Connect signals
        self.text_edit.cursorPositionChanged.connect(self._on_cursor_change)
        # Show startup choice after event loop starts
        QtCore.QTimer.singleShot(0, self._show_startup_dialog)

    # UI construction -------------------------------------------------
    def _init_ui(self) -> None:
        self.setWindowTitle("Secure Notepad (PyQt5 Improved)")
        self.resize(1000, 700)

        # Central text edit
        self.text_edit = QtWidgets.QTextEdit(self)
        self.text_edit.setAcceptRichText(False)
        self.setCentralWidget(self.text_edit)
        self._apply_default_font()
        self._apply_stylesheet()

        # Toolbar
        toolbar = QtWidgets.QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        act_open = QtWidgets.QAction("Open", self)
        act_open.triggered.connect(self.open_file)
        toolbar.addAction(act_open)

        act_save = QtWidgets.QAction("Save", self)
        act_save.triggered.connect(self.save_file)
        toolbar.addAction(act_save)

        act_save_as = QtWidgets.QAction("Save As", self)
        act_save_as.triggered.connect(self.save_file_as)
        toolbar.addAction(act_save_as)

        toolbar.addSeparator()
        toolbar.addAction(QtWidgets.QAction("A+", self, triggered=self.increase_font))
        toolbar.addAction(QtWidgets.QAction("A-", self, triggered=self.decrease_font))
        toolbar.addAction(QtWidgets.QAction("Reset Font", self, triggered=self.reset_font))
        toolbar.addSeparator()
        toolbar.addAction(QtWidgets.QAction("Find/Replace", self, triggered=self.open_find_replace))

        # Status bar
        self.status_bar = self.statusBar()
        self._set_status("Ready")

    def _apply_default_font(self) -> None:
        font = QtGui.QFont(self._font_family, self._font_size)
        self.text_edit.setFont(font)

    def _apply_stylesheet(self) -> None:
        # Dark theme with pleasant contrast and selection colors.
        stylesheet = """
        QWidget { background: #121212; color: #E0E0E0; }
        QTextEdit { background: #0F1720; color: #FF6B6B; padding: 8px; border: none; }
        QToolBar { background: #0B0B0B; border: none; spacing:6px; padding:4px; }
        QStatusBar { background: #0B0B0B; color: #CFCFCF; }
        QPushButton { background: #1E1E1E; color: #E0E0E0; border: 1px solid #2A2A2A; padding:4px 8px; }
        QPushButton:hover { background: #2A2A2A; }
        QLineEdit { background: #1A1A1A; color: #E0E0E0; border: 1px solid #2A2A2A; padding:4px; }
        QTextEdit { selection-background-color: #1155CC; selection-color: #FFFFFF; }
        """
        self.setStyleSheet(stylesheet)

    # Status helper -------------------------------------------------
    def _set_status(self, message: str, timeout_ms: int = STATUS_MSG_DURATION_MS) -> None:
        self.status_bar.showMessage(message, timeout_ms)

    # Font control -------------------------------------------------
    def increase_font(self) -> None:
        self._font_size += 2
        self._apply_default_font()

    def decrease_font(self) -> None:
        if self._font_size > 6:
            self._font_size -= 2
            self._apply_default_font()

    def reset_font(self) -> None:
        self._font_size = DEFAULT_FONT_SIZE
        self._apply_default_font()

    # File operations (use background workers) -----------------------
    def save_file(self) -> None:
        if not self._current_path:
            return self.save_file_as()
        self._do_save(self._current_path)

    def save_file_as(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save As",
            "",
            f"Secure Note (*{DEFAULT_EXTENSION});;All Files (*)"
        )
        if not path:
            self._set_status("Save canceled")
            return
        if not path.lower().endswith(DEFAULT_EXTENSION):
            path += DEFAULT_EXTENSION
        self._current_path = path
        self._do_save(path)

    def _do_save(self, path: str) -> None:
        dlg = PasswordDialog(self, confirm=True, title="Set Save Password", prompt="Enter password to encrypt file:")
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            self._set_status("Save canceled")
            return
        password = dlg.value()
        if password is None:
            self._set_status("Save canceled")
            return

        plaintext = self.text_edit.toPlainText().encode("utf-8")
        result_emitter = FileSaveResult()
        result_emitter.finished.connect(lambda: self._on_save_success(path))
        result_emitter.error.connect(self._on_save_error)
        worker = FileSaveWorker(path, password, plaintext, result_emitter)
        self._thread_pool.start(worker)
        self._set_status("Saving...")

    def _on_save_success(self, path: str) -> None:
        self._set_status(f"Saved: {os.path.basename(path)}")
        QtWidgets.QMessageBox.information(self, "Save", "File encrypted and saved successfully.")

    def _on_save_error(self, exc: Exception) -> None:
        QtWidgets.QMessageBox.critical(self, "Save Error", str(exc))
        self._set_status("Save failed")

    def open_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open File",
            "",
            f"Secure Note (*{DEFAULT_EXTENSION});;All Files (*)"
        )
        if not path:
            self._set_status("Open canceled")
            return
        dlg = PasswordDialog(self, confirm=False, title="Enter Open Password", prompt="Enter password to decrypt file:")
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            self._set_status("Open canceled")
            return
        password = dlg.value()
        if password is None:
            self._set_status("Open canceled")
            return

        result_emitter = FileLoadResult()
        result_emitter.finished.connect(lambda data: self._on_open_success(path, data))
        result_emitter.error.connect(self._on_open_error)
        worker = FileLoadWorker(path, password, result_emitter)
        self._thread_pool.start(worker)
        self._set_status("Opening...")

    def _on_open_success(self, path: str, plaintext: bytes) -> None:
        try:
            text = plaintext.decode("utf-8")
        except Exception:
            # fallback to latin-1 for extreme cases (unlikely)
            text = plaintext.decode("latin-1")
        self.text_edit.setPlainText(text)
        self._current_path = path
        self._set_status(f"Opened: {os.path.basename(path)}")
        QtWidgets.QMessageBox.information(self, "Open", "File decrypted and loaded successfully.")

    def _on_open_error(self, exc: Exception) -> None:
        QtWidgets.QMessageBox.critical(self, "Open/Decrypt Error", str(exc))
        self._set_status("Open failed")

    # Find / Replace dialog ----------------------------------------
    def open_find_replace(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Find and Replace")
        dialog.setModal(True)

        grid = QtWidgets.QGridLayout(dialog)
        grid.addWidget(QtWidgets.QLabel("Find:"), 0, 0)
        edit_find = QtWidgets.QLineEdit(dialog)
        grid.addWidget(edit_find, 0, 1)

        grid.addWidget(QtWidgets.QLabel("Replace with:"), 1, 0)
        edit_replace = QtWidgets.QLineEdit(dialog)
        grid.addWidget(edit_replace, 1, 1)

        chk_case = QtWidgets.QCheckBox("Case sensitive", dialog)
        grid.addWidget(chk_case, 2, 1)

        button_row = QtWidgets.QHBoxLayout()
        grid.addLayout(button_row, 3, 0, 1, 2)
        button_row.addStretch()
        btn_find_next = QtWidgets.QPushButton("Find Next", dialog)
        btn_highlight_all = QtWidgets.QPushButton("Highlight All", dialog)
        btn_replace_one = QtWidgets.QPushButton("Replace", dialog)
        btn_replace_all = QtWidgets.QPushButton("Replace All", dialog)
        btn_clear = QtWidgets.QPushButton("Clear Highlights", dialog)
        for b in (btn_find_next, btn_highlight_all, btn_replace_one, btn_replace_all, btn_clear):
            button_row.addWidget(b)

        # Button callbacks
        def on_highlight_all() -> None:
            pattern = edit_find.text()
            case_sensitive = chk_case.isChecked()
            cnt = self._finder.highlight_all(pattern, case_sensitive=case_sensitive)
            self._set_status(f"Highlighted {cnt} matches")

        def on_find_next() -> None:
            pattern = edit_find.text()
            if not pattern:
                self._set_status("Find string is empty")
                return
            flags = QtGui.QTextDocument.FindFlags()
            if chk_case.isChecked():
                flags |= QtGui.QTextDocument.FindCaseSensitively
            found = self.text_edit.find(pattern, flags)
            if not found:
                # wrap-around search
                self.text_edit.moveCursor(QtGui.QTextCursor.Start)
                found = self.text_edit.find(pattern, flags)
                if not found:
                    self._set_status("Not found")
                    return
            cur = self.text_edit.textCursor()
            self._finder.highlight_current(cur)
            self._set_status(f"Found at {cur.selectionStart()}")

        def on_replace_one() -> None:
            pattern = edit_find.text()
            repl = edit_replace.text()
            if not pattern:
                self._set_status("Find string is empty")
                return
            flags = QtGui.QTextDocument.FindFlags()
            if chk_case.isChecked():
                flags |= QtGui.QTextDocument.FindCaseSensitively
            found = self.text_edit.find(pattern, flags)
            if not found:
                # wrap-around
                self.text_edit.moveCursor(QtGui.QTextCursor.Start)
                found = self.text_edit.find(pattern, flags)
                if not found:
                    self._set_status("Not found")
                    return
            cur = self.text_edit.textCursor()
            cur.insertText(repl)
            # after replace, cursor is after inserted text; mark as current
            cur = self.text_edit.textCursor()
            self._finder.highlight_current(cur)
            self._set_status("Replaced one occurrence")

        def on_replace_all() -> None:
            pattern = edit_find.text()
            repl = edit_replace.text()
            if not pattern:
                self._set_status("Find string is empty")
                return
            # Implement case-insensitive replace while preserving simple behavior:
            # If case-sensitive: direct replace
            # If case-insensitive: perform a case-insensitive replacement that does not attempt to preserve original case.
            full_text = self.text_edit.toPlainText()
            if chk_case.isChecked():
                new_text = full_text.replace(pattern, repl)
            else:
                # Case-insensitive replacement: iterate matches to avoid catastrophic memory usage;
                # use Python's re with IGNORECASE to perform replacement.
                import re
                # Use a callable replacement that returns repl (no case-preserving).
                new_text = re.sub(re.escape(pattern), repl, full_text, flags=re.IGNORECASE)
            self.text_edit.setPlainText(new_text)
            self._finder.clear()
            self._set_status("Replaced all occurrences")
        def on_clear() -> None:
            self._finder.clear()
            self._set_status("Highlights cleared")
        btn_highlight_all.clicked.connect(on_highlight_all)
        btn_find_next.clicked.connect(on_find_next)
        btn_replace_one.clicked.connect(on_replace_one)
        btn_replace_all.clicked.connect(on_replace_all)
        btn_clear.clicked.connect(on_clear)
        edit_find.setFocus()
        dialog.resize(520, 160)
        dialog.exec_()
    # Cursor change handling ---------------------------------------
    def _on_cursor_change(self) -> None:
        """
        When user moves the cursor, if there is a selection mark it as current match.
        Otherwise remove prior 'current' marker and keep other highlights.
        """
        cur = self.text_edit.textCursor()
        if cur.hasSelection():
            self._finder.highlight_current(cur)
        else:
            # remove any current marker entries from extraSelections
            existing = self.text_edit.extraSelections()
            remaining = [s for s in existing if not getattr(s, "_is_current_marker", False)]
            self.text_edit.setExtraSelections(remaining)
    # Startup dialog -----------------------------------------------
    def _show_startup_dialog(self) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Start")
        dlg.setModal(True)
        layout = QtWidgets.QVBoxLayout(dlg)
        layout.addWidget(QtWidgets.QLabel("Choose an action:"))
        btn_new = QtWidgets.QPushButton("New blank", dlg)
        btn_open = QtWidgets.QPushButton("Open existing file", dlg)
        btn_cancel = QtWidgets.QPushButton("Cancel", dlg)
        layout.addWidget(btn_new)
        layout.addWidget(btn_open)
        layout.addWidget(btn_cancel)
        btn_new.clicked.connect(dlg.accept)
        btn_open.clicked.connect(lambda: (dlg.accept(), self.open_file()))
        btn_cancel.clicked.connect(dlg.reject)
        dlg.exec_()
# -----------------------------
# Application entrypoint
# -----------------------------
def main() -> int:
    """Start application main loop."""
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()
if __name__ == "__main__":
    sys.exit(main())
