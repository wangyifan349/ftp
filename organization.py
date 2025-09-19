import os
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import json
import math
from pathlib import Path
from typing import List, Callable, Optional
CONFIG_FILE = Path.home() / ".media_organizer_config.json"
# 可扩展的媒体扩展名集合
VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.heic'}
MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS
# 用户决定覆盖策略
class OverwriteChoice:
    ASK = "ask"
    OVERWRITE_ALL = "overwrite_all"
    SKIP_ALL = "skip_all"
def is_media_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in MEDIA_EXTS
def get_unique_filename(directory: str, filename: str) -> str:
    directory_path = Path(directory)
    name = Path(filename).stem
    ext = Path(filename).suffix
    candidate = directory_path / (name + ext)
    counter = 1
    while candidate.exists():
        candidate = directory_path / f"{name}_{counter}{ext}"
        counter += 1
    return str(candidate.name)
def path_is_excluded(path: str, exclude_list: List[str]) -> bool:
    # 基于路径分段匹配，避免 "notebook" 匹配到 "book"
    p = Path(path).resolve()
    parts = set(p.parts)
    for excl in exclude_list:
        if not excl:
            continue
        # 支持相对或绝对排除路径；仅按名称或子路径匹配
        excl_path = Path(excl)
        if excl_path.is_absolute():
            try:
                if excl_path.resolve() in p.parents or excl_path.resolve() == p:
                    return True
            except Exception:
                pass
        else:
            if excl in parts:
                return True
    return False
def ensure_free_space_for_file(dest_dir: str, file_size: int) -> bool:
    """检查目标分区是否有足够空间（以字节为单位）。在某些平台上可能不精确。"""
    try:
        stat = os.statvfs(dest_dir)
        free = stat.f_bavail * stat.f_frsize
        return free >= file_size
    except Exception:
        # 如果无法检测，返回 True 以避免误阻止（但后续操作会捕获写入错误）
        return True
def organize_media_files(
    source_dirs: List[str],
    target_dir: str,
    exclude_dirs: List[str],
    operation: str,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    error_callback: Optional[Callable[[str], None]] = None,
    ask_overwrite_callback: Optional[Callable[[str], str]] = None,
    stop_event: Optional[threading.Event] = None
):
    """
    progress_callback(message, processed_count, total_count)
    ask_overwrite_callback(target_path) -> OverwriteChoice
    error_callback(message)
    stop_event 用于中止操作
    """
    os.makedirs(target_dir, exist_ok=True)
    # 收集所有媒体文件（先遍历以便显示总量）
    all_files = []
    for source_dir in source_dirs:
        for root, dirs, files in os.walk(source_dir):
            if stop_event and stop_event.is_set():
                return
            # 如果当前目录或上级被排除，则跳过
            if path_is_excluded(root, exclude_dirs):
                dirs[:] = []
                continue
            for file in files:
                if is_media_file(file):
                    all_files.append(os.path.join(root, file))
    total = len(all_files)
    processed = 0
    overwrite_mode = OverwriteChoice.ASK
    for source_file in all_files:
        if stop_event and stop_event.is_set():
            break
        try:
            processed += 1
            filename = os.path.basename(source_file)
            target_name = get_unique_filename(target_dir, filename)
            target_file = os.path.join(target_dir, target_name)
            # 如果目标已存在（极少数情况下 get_unique_filename 仍会与 race 冲突），再次检测
            if os.path.exists(target_file):
                if overwrite_mode == OverwriteChoice.ASK and ask_overwrite_callback:
                    choice = ask_overwrite_callback(target_file)
                    if choice == OverwriteChoice.OVERWRITE_ALL:
                        overwrite_mode = OverwriteChoice.OVERWRITE_ALL
                    elif choice == OverwriteChoice.SKIP_ALL:
                        overwrite_mode = OverwriteChoice.SKIP_ALL
                else:
                    choice = overwrite_mode

                if overwrite_mode == OverwriteChoice.SKIP_ALL:
                    if progress_callback:
                        progress_callback(f"Skipped (exists): {source_file}", processed, total)
                    continue
            # 检查目标分区空间（仅在复制时有意义）
            try:
                file_size = os.path.getsize(source_file)
            except OSError:
                file_size = 0
            if not ensure_free_space_for_file(target_dir, file_size):
                msg = f"Not enough free space for {source_file} -> {target_file}"
                if error_callback:
                    error_callback(msg)
                # 停止或跳过取决于实现，这里选择停止
                break
            if operation == 'move':
                # move 可能会失败（跨分区 move 会做 copy+delete）
                try:
                    shutil.move(source_file, target_file)
                except Exception as e:
                    # 在 move 失败时尝试 copy2 + remove
                    try:
                        shutil.copy2(source_file, target_file)
                        os.remove(source_file)
                    except Exception as e2:
                        if error_callback:
                            error_callback(f"Failed to move {source_file}: {e2}")
                        continue
            else:
                try:
                    shutil.copy2(source_file, target_file)
                except Exception as e:
                    if error_callback:
                        error_callback(f"Failed to copy {source_file}: {e}")
                    continue
            if progress_callback:
                progress_callback(f"Processed: {source_file}", processed, total)

        except Exception as e:
            if error_callback:
                error_callback(f"Unexpected error for {source_file}: {e}")
def save_config(data: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
# ---------------------------
# GUI 部分
# ---------------------------
class MediaOrganizerGUI:
    def __init__(self, root):
        self.root = root
        root.title("Media Organizer")
        root.geometry("600x520")
        # 状态
        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        # UI 组件
        self.source_dirs_listbox = tk.Listbox(root, selectmode=tk.MULTIPLE, width=70, height=8)
        self.source_dirs_listbox.pack(pady=6)
        tk.Button(root, text="Add Source Directory", command=self.add_source_directory).pack(pady=3)
        tk.Button(root, text="Remove Selected", command=self.remove_selected_source_directory).pack(pady=3)
        self.target_dir_var = tk.StringVar()
        self.exclude_dirs_var = tk.StringVar()
        self.operation_var = tk.StringVar(value='copy')
        tk.Label(root, text="Target Directory:").pack(pady=4)
        tk.Entry(root, textvariable=self.target_dir_var, width=70).pack(pady=2)
        tk.Button(root, text="Browse", command=self.select_target_directory).pack(pady=2)
        tk.Label(root, text="Exclude Folders (comma separated names or absolute paths):").pack(pady=4)
        tk.Entry(root, textvariable=self.exclude_dirs_var, width=70).pack(pady=2)
        tk.Label(root, text="Operation:").pack(pady=4)
        tk.Radiobutton(root, text="Copy Files", variable=self.operation_var, value='copy').pack()
        tk.Radiobutton(root, text="Move Files", variable=self.operation_var, value='move').pack()
        self.start_button = tk.Button(root, text="Start Organizing", command=self.on_start)
        self.start_button.pack(pady=10)
        self.stop_button = tk.Button(root, text="Stop", command=self.on_stop, state=tk.DISABLED)
        self.stop_button.pack(pady=2)
        # 进度文本框
        self.progress_text = tk.Text(root, height=10, width=80, state=tk.DISABLED)
        self.progress_text.pack(pady=6)
        # 加载配置
        cfg = load_config()
        for s in cfg.get("source_dirs", []):
            self.source_dirs_listbox.insert(tk.END, s)
        self.target_dir_var.set(cfg.get("target_dir", ""))
        self.exclude_dirs_var.set(cfg.get("exclude_dirs", ""))
        self.operation_var.set(cfg.get("operation", "copy"))
    # UI 操作
    def add_source_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.source_dirs_listbox.insert(tk.END, directory)
    def remove_selected_source_directory(self):
        selected_indices = self.source_dirs_listbox.curselection()
        for index in reversed(selected_indices):
            self.source_dirs_listbox.delete(index)
    def select_target_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.target_dir_var.set(directory)
    def append_progress(self, message: str):
        # 在主线程中更新文本框
        def _append():
            self.progress_text['state'] = tk.NORMAL
            self.progress_text.insert(tk.END, message + "\n")
            self.progress_text.see(tk.END)
            self.progress_text['state'] = tk.DISABLED
        self.root.after(0, _append)
    def on_start(self):
        # 防止重复启动
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Info", "Organizer is already running.")
            return
        source_dirs = list(self.source_dirs_listbox.get(0, tk.END))
        target_dir = self.target_dir_var.get().strip()
        exclude_dirs = [s.strip() for s in self.exclude_dirs_var.get().split(',') if s.strip()]
        operation = self.operation_var.get()
        if not source_dirs or not target_dir:
            messagebox.showwarning("Warning", "Please select at least one source directory and a target directory.")
            return
        # 保存设置
        save_config({
            "source_dirs": source_dirs,
            "target_dir": target_dir,
            "exclude_dirs": ",".join(exclude_dirs),
            "operation": operation
        })
        # 确认长时间操作（如果文件很多）
        if messagebox.askyesno("Confirm", f"Start {operation} of media files from {len(source_dirs)} source(s) to:\n{target_dir}?"):
            self.progress_text['state'] = tk.NORMAL
            self.progress_text.delete(1.0, tk.END)
            self.progress_text['state'] = tk.DISABLED
            self.start_button['state'] = tk.DISABLED
            self.stop_button['state'] = tk.NORMAL
            self.stop_event.clear()
            self.worker_thread = threading.Thread(target=self._worker_thread_target, args=(source_dirs, target_dir, exclude_dirs, operation), daemon=True)
            self.worker_thread.start()
    def on_stop(self):
        if messagebox.askyesno("Stop", "Are you sure you want to stop the current operation?"):
            self.stop_event.set()
            self.append_progress("Stop requested; finishing up...")
    def ask_overwrite(self, target_path: str) -> str:
        # 在主线程弹窗询问（阻塞式），并提供覆盖全部/跳过全部选项
        result = {"choice": OverwriteChoice.ASK}
        def _ask():
            resp = messagebox.askquestion("File Exists", f"Target already exists:\n{target_path}\n\nOverwrite this file?", icon='warning')
            if resp == 'yes':
                # 询问是否全部覆盖
                more = messagebox.askyesnocancel("Overwrite Options", "Overwrite all subsequent conflicts?\nYes = Overwrite all, No = Only this file, Cancel = Skip all")
                if more is None:
                    result["choice"] = OverwriteChoice.SKIP_ALL
                elif more:
                    result["choice"] = OverwriteChoice.OVERWRITE_ALL
                else:
                    result["choice"] = OverwriteChoice.ASK
                # If more is False we just overwrite this single file (i.e., ASK resolves to overwrite this one)
                if result["choice"] == OverwriteChoice.ASK:
                    # represent 'this file' by temporarily returning OVERWRITE_ALL and then reset in caller if needed
                    result["choice"] = OverwriteChoice.OVERWRITE_ALL
            else:
                # 用户选择 No => 跳过并询问是否跳过所有
                more = messagebox.askyesno("Skip Options", "Skip all subsequent conflicts?")
                if more:
                    result["choice"] = OverwriteChoice.SKIP_ALL
                else:
                    # skip this file only
                    result["choice"] = OverwriteChoice.SKIP_ALL
        # 调用主线程
        self.root.after(0, _ask)
        # 等待用户选择（轮询）
        while result["choice"] == OverwriteChoice.ASK:
            self.root.update()
        return result["choice"]
    def _worker_thread_target(self, source_dirs, target_dir, exclude_dirs, operation):
        # 包装回调以跨线程安全更新 UI
        def progress_cb(message, processed, total):
            self.append_progress(f"[{processed}/{total}] {message}")
        def error_cb(message):
            self.append_progress("ERROR: " + message)
        def ask_cb(target_path):
            # 使用一个简单阻塞询问（在 GUI 线程）
            choice = self._blocking_ask_overwrite(target_path)
            return choice
        try:
            organize_media_files(
                source_dirs=source_dirs,
                target_dir=target_dir,
                exclude_dirs=exclude_dirs,
                operation=operation,
                progress_callback=progress_cb,
                error_callback=error_cb,
                ask_overwrite_callback=ask_cb,
                stop_event=self.stop_event
            )
            if not self.stop_event.is_set():
                self.append_progress("All done.")
                messagebox.showinfo("Success", "Files have been organized successfully.")
            else:
                self.append_progress("Operation stopped by user.")
                messagebox.showinfo("Stopped", "Operation was stopped.")
        except Exception as e:
            self.append_progress("FATAL ERROR: " + str(e))
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
        finally:
            self.start_button['state'] = tk.NORMAL
            self.stop_button['state'] = tk.DISABLED
    def _blocking_ask_overwrite(self, target_path: str) -> str:
        # 由于 messagebox 是主线程安全的，这里直接询问用户（阻塞式）
        resp = messagebox.askyesno("File Exists", f"Target already exists:\n{target_path}\n\nOverwrite this file?")
        if resp:
            # 询问是否全部覆盖
            all_resp = messagebox.askyesno("Overwrite Options", "Overwrite all subsequent conflicts?")
            return OverwriteChoice.OVERWRITE_ALL if all_resp else OverwriteChoice.OVERWRITE_ALL
        else:
            skip_all = messagebox.askyesno("Skip Options", "Skip all subsequent conflicts?")
            return OverwriteChoice.SKIP_ALL if skip_all else OverwriteChoice.SKIP_ALL
# 启动 GUI
if __name__ == "__main__":
    root = tk.Tk()
    app = MediaOrganizerGUI(root)
    root.mainloop()
