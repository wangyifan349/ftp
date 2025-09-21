import sys
import os
import struct
from typing import Optional, List
from PyQt5 import QtWidgets, QtGui, QtCore
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes
import base58

PBKDF2_ITERATIONS = 5000
SALT_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16
MAGIC_HEADER = b'SNOTE1.0'
FORMAT_VERSION = 1
DEFAULT_FONT_SIZE = 16
DEFAULT_EXTENSION = ".snoteb58"
STATUS_MSG_DURATION_MS = 5000

def derive_key(password: str, salt: bytes, key_len: int = 32) -> bytes:
    return PBKDF2(password.encode("utf-8"), salt, dkLen=key_len, count=PBKDF2_ITERATIONS)

def encrypt_bytes_to_base58(plaintext: bytes, password: str) -> bytes:
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
    raw = base58.b58decode(b58data)
    offset = 0
    if raw[0: len(MAGIC_HEADER)] != MAGIC_HEADER:
        raise ValueError("Unsupported file format")
    offset += len(MAGIC_HEADER)
    version = raw[offset]
    offset += 1
    if version != FORMAT_VERSION:
        raise ValueError("Unsupported version")
    salt = raw[offset: offset + SALT_BYTES]
    offset += SALT_BYTES
    nonce = raw[offset: offset + NONCE_BYTES]
    offset += NONCE_BYTES
    (ciphertext_length,) = struct.unpack(">Q", raw[offset: offset + 8])
    offset += 8
    ciphertext = raw[offset: offset + ciphertext_length]
    offset += ciphertext_length
    tag = raw[offset: offset + TAG_BYTES]
    key = derive_key(password, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)

class FileLoadResult(QtCore.QObject):
    finished = QtCore.pyqtSignal(bytes)
    error = QtCore.pyqtSignal(Exception)

class FileLoadWorker(QtCore.QRunnable):
    def __init__(self, file_path: str, password: str, result_emitter: FileLoadResult):
        super().__init__()
        self.file_path = file_path
        self.password = password
        self.emitter = result_emitter

    @QtCore.pyqtSlot()
    def run(self):
        try:
            with open(self.file_path, "rb") as file_handle:
                data = file_handle.read()
            plaintext = decrypt_base58_to_bytes(data, self.password)
            self.emitter.finished.emit(plaintext)
        except Exception as exception:
            self.emitter.error.emit(exception)

class FileSaveResult(QtCore.QObject):
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(Exception)

class FileSaveWorker(QtCore.QRunnable):
    def __init__(self, file_path: str, password: str, plaintext: bytes, result_emitter: FileSaveResult):
        super().__init__()
        self.file_path = file_path
        self.password = password
        self.plaintext = plaintext
        self.emitter = result_emitter

    @QtCore.pyqtSlot()
    def run(self):
        try:
            b58 = encrypt_bytes_to_base58(self.plaintext, self.password)
            with open(self.file_path, "wb") as file_handle:
                file_handle.write(b58)
            self.emitter.finished.emit()
        except Exception as exception:
            self.emitter.error.emit(exception)

class PasswordDialog(QtWidgets.QDialog):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, require_confirmation: bool = False,
                 dialog_title: str = "Password", prompt_text: str = "Enter password:"):
        super().__init__(parent)
        self.setWindowTitle(dialog_title)
        self.setModal(True)
        self._value: Optional[str] = None
        self._require_confirmation = require_confirmation
        self._build_ui(prompt_text)

    def _build_ui(self, prompt_text: str):
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(prompt_text, self)
        layout.addWidget(label)
        self.password_edit = QtWidgets.QLineEdit(self)
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        layout.addWidget(self.password_edit)
        self.confirm_edit = None
        if self._require_confirmation:
            self.confirm_edit = QtWidgets.QLineEdit(self)
            self.confirm_edit.setEchoMode(QtWidgets.QLineEdit.Password)
            self.confirm_edit.setPlaceholderText("Confirm password")
            layout.addWidget(self.confirm_edit)
        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
                                                parent=self)
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        self.resize(420, 120)

    def _on_accept(self):
        password_value = self.password_edit.text()
        if self._require_confirmation:
            confirm_value = self.confirm_edit.text() if self.confirm_edit else ""
            if password_value == "":
                QtWidgets.QMessageBox.critical(self, "Error", "Password cannot be empty")
                return
            if password_value != confirm_value:
                QtWidgets.QMessageBox.critical(self, "Error", "Passwords do not match")
                return
        self._value = password_value
        self.accept()

    def value(self) -> Optional[str]:
        return self._value

def create_text_format(background_color: QtGui.QColor, foreground_color: QtGui.QColor) -> QtGui.QTextCharFormat:
    text_format = QtGui.QTextCharFormat()
    text_format.setBackground(QtGui.QBrush(background_color))
    text_format.setForeground(QtGui.QBrush(foreground_color))
    return text_format

class FinderHighlighter:
    def __init__(self, text_edit_widget: QtWidgets.QTextEdit):
        self._text_edit_widget = text_edit_widget
        # All matches: gold background, red foreground
        self._all_match_format = create_text_format(QtGui.QColor("#FFF59D"), QtGui.QColor("#FF0000"))
        # Current match: same as all matches but bold to make it slightly distinct
        self._current_match_format = create_text_format(QtGui.QColor("#FFF59D"), QtGui.QColor("#FF0000"))
        bold_font = QtGui.QFont()
        bold_font.setBold(True)
        self._current_match_format.setFont(bold_font)

    def clear(self) -> None:
        self._text_edit_widget.setExtraSelections([])

    def highlight_all(self, pattern: str, case_sensitive: bool = False) -> int:
        self.clear()
        if not pattern:
            return 0
        document = self._text_edit_widget.document()
        flags = QtGui.QTextDocument.FindFlags()
        if case_sensitive:
            flags |= QtGui.QTextDocument.FindCaseSensitively

        cursor = document.find(pattern, 0, flags)
        selections: List[QtWidgets.QTextEdit.ExtraSelection] = []
        match_count = 0
        while not cursor.isNull():
            selection = QtWidgets.QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = self._all_match_format
            selections.append(selection)
            match_count += 1
            cursor = document.find(pattern, cursor.selectionEnd(), flags)
        self._text_edit_widget.setExtraSelections(selections)
        return match_count

    def highlight_current(self, text_cursor: QtGui.QTextCursor) -> None:
        existing_selections = self._text_edit_widget.extraSelections()
        remaining_selections = [selection for selection in existing_selections if not getattr(selection, "_is_current_marker", False)]
        current_selection = QtWidgets.QTextEdit.ExtraSelection()
        current_selection.cursor = text_cursor
        current_selection.format = self._current_match_format
        setattr(current_selection, "_is_current_marker", True)
        remaining_selections.append(current_selection)
        self._text_edit_widget.setExtraSelections(remaining_selections)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self._current_file_path: Optional[str] = None

        families = QtGui.QFontDatabase().families()
        default_family = "Consolas" if "Consolas" in families else ("Courier" if "Courier" in families else QtWidgets.QApplication.font().family())
        self._font_family = default_family
        self._font_size = DEFAULT_FONT_SIZE
        self._thread_pool = QtCore.QThreadPool.globalInstance()

        self._init_ui()
        self._finder = FinderHighlighter(self.text_edit)
        self.text_edit.cursorPositionChanged.connect(self._on_cursor_position_changed)
        QtCore.QTimer.singleShot(0, self._show_startup_dialog)

    def _init_ui(self) -> None:
        self.setWindowTitle("Secure Notepad (PyQt5 Improved)")
        self.resize(1000, 700)

        self.text_edit = QtWidgets.QTextEdit(self)
        self.text_edit.setAcceptRichText(False)
        self.setCentralWidget(self.text_edit)
        self._apply_default_font()
        self._apply_stylesheet()

        toolbar = QtWidgets.QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        action_open = QtWidgets.QAction("Open", self)
        action_open.triggered.connect(self.open_file)
        toolbar.addAction(action_open)

        action_save = QtWidgets.QAction("Save", self)
        action_save.triggered.connect(self.save_file)
        toolbar.addAction(action_save)

        toolbar.addSeparator()
        toolbar.addAction(QtWidgets.QAction("A+", self, triggered=self.increase_font))
        toolbar.addAction(QtWidgets.QAction("A-", self, triggered=self.decrease_font))
        toolbar.addAction(QtWidgets.QAction("Reset Font", self, triggered=self.reset_font))
        toolbar.addSeparator()
        toolbar.addAction(QtWidgets.QAction("Find/Replace", self, triggered=self.open_find_replace))

        self.status_bar = self.statusBar()
        self._set_status("Ready")

    def _apply_default_font(self) -> None:
        font = QtGui.QFont(self._font_family, self._font_size)
        self.text_edit.setFont(font)

    def _apply_stylesheet(self) -> None:
        stylesheet = """
        QWidget { background: #121212; color: #E0E0E0; }
        QTextEdit { background: #0F1720; color: #FF6B6B; padding: 8px; border: none; }
        QToolBar { background: #0B0B0B; border: none; spacing:6px; padding:4px; }
        QStatusBar { background: #0B0B0B; color: #CFCFCF; }
        QPushButton { background: #1E1E1E; color: #E0E0E0; border: 1px solid #2A2A2A; padding:4px 8px; }
        QPushButton:hover { background: #2A2A2A; }
        QLineEdit { background: #1A1A1A; color: #E0E0E0; border: 1px solid #2A2A2A; padding:4px; }
        /* Selection: green background, gold (FFF59D) foreground */
        QTextEdit { selection-background-color: #00FF00; selection-color: #FFF59D; }
        """
        self.setStyleSheet(stylesheet)

    def _set_status(self, message: str, timeout_ms: int = STATUS_MSG_DURATION_MS) -> None:
        self.status_bar.showMessage(message, timeout_ms)

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

    def save_file(self) -> None:
        if not self._current_file_path:
            return self.save_file_as()
        self._perform_save(self._current_file_path)

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
        self._current_file_path = path
        self._perform_save(path)

    def _perform_save(self, file_path: str) -> None:
        password_dialog = PasswordDialog(self, require_confirmation=True, dialog_title="Set Save Password", prompt_text="Enter password to encrypt file:")
        if password_dialog.exec_() != QtWidgets.QDialog.Accepted:
            self._set_status("Save canceled")
            return
        password_value = password_dialog.value()
        if password_value is None:
            self._set_status("Save canceled")
            return

        plaintext_bytes = self.text_edit.toPlainText().encode("utf-8")
        result_emitter = FileSaveResult()
        result_emitter.finished.connect(lambda: self._on_save_success(file_path))
        result_emitter.error.connect(self._on_save_error)
        worker = FileSaveWorker(file_path, password_value, plaintext_bytes, result_emitter)
        self._thread_pool.start(worker)
        self._set_status("Saving...")

    def _on_save_success(self, file_path: str) -> None:
        self._set_status(f"Saved: {os.path.basename(file_path)}")
        QtWidgets.QMessageBox.information(self, "Save", "File encrypted and saved successfully.")

    def _on_save_error(self, exception: Exception) -> None:
        QtWidgets.QMessageBox.critical(self, "Save Error", str(exception))
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
        password_dialog = PasswordDialog(self, require_confirmation=False, dialog_title="Enter Open Password", prompt_text="Enter password to decrypt file:")
        if password_dialog.exec_() != QtWidgets.QDialog.Accepted:
            self._set_status("Open canceled")
            return
        password_value = password_dialog.value()
        if password_value is None:
            self._set_status("Open canceled")
            return

        result_emitter = FileLoadResult()
        result_emitter.finished.connect(lambda data: self._on_open_success(path, data))
        result_emitter.error.connect(self._on_open_error)
        worker = FileLoadWorker(path, password_value, result_emitter)
        self._thread_pool.start(worker)
        self._set_status("Opening...")

    def _on_open_success(self, file_path: str, plaintext: bytes) -> None:
        try:
            text = plaintext.decode("utf-8")
        except Exception:
            text = plaintext.decode("latin-1")
        self.text_edit.setPlainText(text)
        self._current_file_path = file_path
        self._set_status(f"Opened: {os.path.basename(file_path)}")
        QtWidgets.QMessageBox.information(self, "Open", "File decrypted and loaded successfully.")

    def _on_open_error(self, exception: Exception) -> None:
        QtWidgets.QMessageBox.critical(self, "Open/Decrypt Error", str(exception))
        self._set_status("Open failed")

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
        for button in (btn_find_next, btn_highlight_all, btn_replace_one, btn_replace_all, btn_clear):
            button_row.addWidget(button)

        btn_highlight_all.clicked.connect(lambda: self._handle_highlight_all(edit_find.text(), chk_case.isChecked()))
        btn_find_next.clicked.connect(lambda: self._handle_find_next(edit_find.text(), chk_case.isChecked()))
        btn_replace_one.clicked.connect(lambda: self._handle_replace_one(edit_find.text(), edit_replace.text(), chk_case.isChecked()))
        btn_replace_all.clicked.connect(lambda: self._handle_replace_all(edit_find.text(), edit_replace.text(), chk_case.isChecked()))
        btn_clear.clicked.connect(self._handle_clear_highlights)

        edit_find.setFocus()
        dialog.resize(520, 160)
        dialog.exec_()

    def _handle_highlight_all(self, pattern: str, case_sensitive: bool) -> None:
        count = self._finder.highlight_all(pattern, case_sensitive=case_sensitive)
        self._set_status(f"Highlighted {count} matches")

    def _handle_find_next(self, pattern: str, case_sensitive: bool) -> None:
        if not pattern:
            self._set_status("Find string is empty")
            return
        flags = QtGui.QTextDocument.FindFlags()
        if case_sensitive:
            flags |= QtGui.QTextDocument.FindCaseSensitively
        found = self.text_edit.find(pattern, flags)
        if not found:
            self.text_edit.moveCursor(QtGui.QTextCursor.Start)
            found = self.text_edit.find(pattern, flags)
            if not found:
                self._set_status("Not found")
                return
        cursor = self.text_edit.textCursor()
        self._finder.highlight_current(cursor)
        self._set_status(f"Found at {cursor.selectionStart()}")

    def _handle_replace_one(self, pattern: str, replacement: str, case_sensitive: bool) -> None:
        if not pattern:
            self._set_status("Find string is empty")
            return
        flags = QtGui.QTextDocument.FindFlags()
        if case_sensitive:
            flags |= QtGui.QTextDocument.FindCaseSensitively
        found = self.text_edit.find(pattern, flags)
        if not found:
            self.text_edit.moveCursor(QtGui.QTextCursor.Start)
            found = self.text_edit.find(pattern, flags)
            if not found:
                self._set_status("Not found")
                return
        cursor = self.text_edit.textCursor()
        cursor.insertText(replacement)
        cursor = self.text_edit.textCursor()
        self._finder.highlight_current(cursor)
        self._set_status("Replaced one occurrence")

    def _handle_replace_all(self, pattern: str, replacement: str, case_sensitive: bool) -> None:
        if not pattern:
            self._set_status("Find string is empty")
            return
        full_text = self.text_edit.toPlainText()
        if case_sensitive:
            new_text = full_text.replace(pattern, replacement)
        else:
            import re
            new_text = re.sub(re.escape(pattern), replacement, full_text, flags=re.IGNORECASE)
        self.text_edit.setPlainText(new_text)
        self._finder.clear()
        self._set_status("Replaced all occurrences")

    def _handle_clear_highlights(self) -> None:
        self._finder.clear()
        self._set_status("Highlights cleared")

    def _on_cursor_position_changed(self) -> None:
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            self._finder.highlight_current(cursor)
        else:
            existing_selections = self.text_edit.extraSelections()
            remaining_selections = [s for s in existing_selections if not getattr(s, "_is_current_marker", False)]
            self.text_edit.setExtraSelections(remaining_selections)

    def _show_startup_dialog(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Start")
        dialog.setModal(True)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel("Choose an action:"))
        button_new = QtWidgets.QPushButton("New blank", dialog)
        button_open = QtWidgets.QPushButton("Open existing file", dialog)
        button_cancel = QtWidgets.QPushButton("Cancel", dialog)
        layout.addWidget(button_new)
        layout.addWidget(button_open)
        layout.addWidget(button_cancel)
        button_new.clicked.connect(dialog.accept)
        button_open.clicked.connect(lambda: (dialog.accept(), self.open_file()))
        button_cancel.clicked.connect(dialog.reject)
        dialog.exec_()

def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()

if __name__ == "__main__":
    sys.exit(main())
