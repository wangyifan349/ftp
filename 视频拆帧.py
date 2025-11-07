import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import cv2
import os
from pathlib import Path
import threading
import time
import json
from PIL import Image, ImageTk
CONFIG_FILE = Path.home() / ".frame_extractor_config.json"
RECENT_MAX = 6
# ---------- 核心拆帧函数 ----------
def video_to_frames(video_path: Path,
                    output_dir: Path,
                    fmt: str = "jpg",
                    start_idx: int = 0,
                    step: int = 1,
                    overwrite: bool = True,
                    progress_callback=None,
                    stop_flag=None):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频文件: {video_path}")
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    os.makedirs(output_dir, exist_ok=True)
    if not overwrite:
        existing = list(output_dir.glob(f"frame_*.{fmt}"))
        if existing:
            max_idx = -1
            for p in existing:
                name = p.stem
                try:
                    idx = int(name.split("_")[-1])
                    if idx > max_idx:
                        max_idx = idx
                except Exception:
                    pass
            start_idx = max_idx + 1
    idx = start_idx
    read_idx = 0
    written = 0
    start_time = time.time()
    while True:
        if stop_flag and stop_flag.is_set():
            break
        ret, frame = cap.read()
        if not ret:
            break
        if (read_idx % step) == 0:
            filename = f"frame_{idx:06d}.{fmt}"
            out_path = output_dir / filename
            ok = cv2.imwrite(str(out_path), frame)
            if not ok:
                cap.release()
                raise RuntimeError(f"无法写入帧文件: {out_path}")
            idx += 1
            written += 1
            elapsed = time.time() - start_time
            if progress_callback:
                progress_callback(written, total_frames, elapsed)
        read_idx += 1
    cap.release()
    return written
# ---------- 应用类 ----------
class FrameExtractorApp:
    def __init__(self, master):
        self.master = master
        master.title("视频拆帧工具")
        master.geometry("820x520")
        master.minsize(780, 480)

        # 状态变量
        self.video_path_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.format_var = tk.StringVar(value="jpg")
        self.step_var = tk.IntVar(value=1)
        self.start_idx_var = tk.IntVar(value=0)
        self.overwrite_var = tk.BooleanVar(value=True)
        self.use_auto_folder_var = tk.BooleanVar(value=True)
        self.recent_files = []
        self.stop_event = None
        self.worker_thread = None
        # UI
        self._build_menu()
        self._build_left_panel()
        self._build_right_panel()
        self._load_config()
        # 支持简单拖放（Windows: 注册到 root），跨平台行为有限
        master.bind("<Drop>", lambda e: None)  # 保留占位，实际拖放用 OS 文件管理器的“打开方式”更可靠
    # ---------- 菜单 ----------
    def _build_menu(self):
        menubar = tk.Menu(self.master)
        # 文件菜单
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="打开视频...", command=self.browse_video, accelerator="Ctrl+O")
        file_menu.add_command(label="打开输出文件夹...", command=self.open_output_folder)
        file_menu.add_separator()
        file_menu.add_command(label="导出日志...", command=self.export_log)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.master.quit)
        menubar.add_cascade(label="文件", menu=file_menu)
        # 配置菜单
        cfg_menu = tk.Menu(menubar, tearoff=0)
        cfg_menu.add_command(label="保存当前配置", command=self.save_config)
        cfg_menu.add_command(label="加载默认配置", command=self.load_default_config)
        menubar.add_cascade(label="配置", menu=cfg_menu)
        # 帮助菜单
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="关于", command=self.show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.master.config(menu=menubar)
        # 快捷键
        self.master.bind_all("<Control-o>", lambda e: self.browse_video())

    # ---------- 左侧（设置、预览） ----------
    def _build_left_panel(self):
        left = tk.Frame(self.master)
        left.place(x=10, y=10, width=520, height=500)

        # 输入行
        f = tk.LabelFrame(left, text="文件与输出", padx=6, pady=6)
        f.pack(fill="x", padx=6, pady=6)
        tk.Label(f, text="视频文件:").grid(row=0, column=0, sticky="e")
        entry = tk.Entry(f, textvariable=self.video_path_var, width=60)
        entry.grid(row=0, column=1, padx=6)
        tk.Button(f, text="浏览…", command=self.browse_video).grid(row=0, column=2, padx=6)
        tk.Checkbutton(f, text="自动创建同名文件夹", variable=self.use_auto_folder_var, command=self._toggle_output).grid(row=1, column=1, sticky="w", pady=6)
        tk.Label(f, text="输出目录:").grid(row=2, column=0, sticky="e")
        self.output_entry = tk.Entry(f, textvariable=self.output_dir_var, width=48)
        self.output_entry.grid(row=2, column=1, sticky="w", padx=6)
        tk.Button(f, text="选择…", command=self.browse_output).grid(row=2, column=2, padx=6)
        self._toggle_output()

        # 选项
        opt = tk.LabelFrame(left, text="选项", padx=6, pady=6)
        opt.pack(fill="x", padx=6, pady=6)
        tk.Label(opt, text="保存格式:").grid(row=0, column=0, sticky="e")
        tk.OptionMenu(opt, self.format_var, "jpg", "png").grid(row=0, column=1, sticky="w")
        tk.Label(opt, text="起始编号:").grid(row=0, column=2, sticky="e")
        tk.Spinbox(opt, from_=0, to=999999, textvariable=self.start_idx_var, width=8).grid(row=0, column=3, sticky="w", padx=6)
        tk.Label(opt, text="帧间隔 (每隔 N 帧保存):").grid(row=1, column=0, sticky="e")
        tk.Spinbox(opt, from_=1, to=1000, textvariable=self.step_var, width=8).grid(row=1, column=1, sticky="w")
        tk.Checkbutton(opt, text="覆盖已存在文件（否则在已有后继续）", variable=self.overwrite_var).grid(row=1, column=2, columnspan=2, sticky="w")

        # 开始/停止/最近文件
        btnf = tk.Frame(left)
        btnf.pack(fill="x", padx=6, pady=6)
        self.start_btn = tk.Button(btnf, text="开始拆帧", width=16, command=self.start_extraction)
        self.start_btn.pack(side="left", padx=6)
        self.stop_btn = tk.Button(btnf, text="停止", width=12, command=self.stop_extraction, state="disabled")
        self.stop_btn.pack(side="left")
        tk.Button(btnf, text="打开输出", command=self.open_output_folder).pack(side="left", padx=6)

        recentf = tk.LabelFrame(left, text="最近文件", padx=6, pady=6)
        recentf.pack(fill="x", padx=6, pady=6)
        self.recent_box = tk.Listbox(recentf, height=4)
        self.recent_box.pack(fill="x")
        self.recent_box.bind("<Double-Button-1>", self._open_selected_recent)

        # 预览缩略图
        pv = tk.LabelFrame(left, text="首帧预览", padx=6, pady=6)
        pv.pack(fill="both", expand=True, padx=6, pady=6)
        self.preview_label = tk.Label(pv, text="无预览", anchor="center")
        self.preview_label.pack(expand=True, fill="both")

    # ---------- 右侧（进度、日志、操作） ----------
    def _build_right_panel(self):
        right = tk.Frame(self.master)
        right.place(x=540, y=10, width=260, height=500)

        pg = tk.LabelFrame(right, text="进度", padx=6, pady=6)
        pg.pack(fill="x", padx=6, pady=6)
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progressbar = ttk.Progressbar(pg, variable=self.progress_var, maximum=100)
        self.progressbar.pack(fill="x", padx=6, pady=4)
        self.status_label = tk.Label(pg, text="准备就绪")
        self.status_label.pack(anchor="w", padx=6)

        lg = tk.LabelFrame(right, text="日志", padx=6, pady=6)
        lg.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text = tk.Text(lg, height=12, width=30, state="disabled")
        self.log_text.pack(fill="both", expand=True)

        opf = tk.Frame(right)
        opf.pack(fill="x", padx=6, pady=6)
        tk.Button(opf, text="导出日志", command=self.export_log).pack(side="left", padx=4)
        tk.Button(opf, text="清空日志", command=self.clear_log).pack(side="left", padx=4)
        tk.Button(opf, text="预览首帧", command=self.generate_preview).pack(side="left", padx=4)

    # ---------- 文件与配置操作 ----------
    def browse_video(self):
        filetypes = [("视频文件", "*.mp4 *.avi *.mov *.mkv *.flv *.wmv"), ("所有文件", "*.*")]
        path = filedialog.askopenfilename(title="选择视频文件", filetypes=filetypes)
        if path:
            self.video_path_var.set(path)
            if self.use_auto_folder_var.get():
                p = Path(path)
                self.output_dir_var.set(str(p.parent / p.stem))
            self._add_recent(path)
            self.generate_preview()

    def browse_output(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.output_dir_var.set(d)

    def open_output_folder(self):
        out = self._get_output_dir()
        if out and out.exists():
            try:
                if os.name == "nt":
                    os.startfile(str(out))
                elif sys.platform == "darwin":
                    os.system(f'open "{out}"')
                else:
                    os.system(f'xdg-open "{out}"')
            except Exception as e:
                messagebox.showerror("错误", f"无法打开目录: {e}")
        else:
            messagebox.showinfo("提示", "输出目录不存在")

    def _get_output_dir(self):
        vid = self.video_path_var.get().strip()
        if self.use_auto_folder_var.get() and vid:
            return Path(vid).parent / Path(vid).stem
        outp = self.output_dir_var.get().strip()
        return Path(outp) if outp else None

    def _toggle_output(self):
        if self.use_auto_folder_var.get():
            self.output_entry.configure(state="disabled")
        else:
            self.output_entry.configure(state="normal")

    def _add_recent(self, path):
        p = str(path)
        if p in self.recent_files:
            self.recent_files.remove(p)
        self.recent_files.insert(0, p)
        self.recent_files = self.recent_files[:RECENT_MAX]
        self._refresh_recent_box()

    def _refresh_recent_box(self):
        self.recent_box.delete(0, "end")
        for p in self.recent_files:
            self.recent_box.insert("end", p)

    def _open_selected_recent(self, _evt=None):
        sel = self.recent_box.curselection()
        if sel:
            p = self.recent_box.get(sel[0])
            self.video_path_var.set(p)
            if self.use_auto_folder_var.get():
                self.output_dir_var.set(str(Path(p).parent / Path(p).stem))
            self.generate_preview()

    def save_config(self):
        cfg = {
            "format": self.format_var.get(),
            "step": int(self.step_var.get()),
            "start_idx": int(self.start_idx_var.get()),
            "overwrite": bool(self.overwrite_var.get()),
            "use_auto_folder": bool(self.use_auto_folder_var.get()),
            "output_dir": self.output_dir_var.get(),
            "recent": self.recent_files
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("已保存", f"配置已保存至 {CONFIG_FILE}")
        except Exception as e:
            messagebox.showerror("错误", f"无法保存配置: {e}")

    def _load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.format_var.set(cfg.get("format", "jpg"))
                self.step_var.set(cfg.get("step", 1))
                self.start_idx_var.set(cfg.get("start_idx", 0))
                self.overwrite_var.set(cfg.get("overwrite", True))
                self.use_auto_folder_var.set(cfg.get("use_auto_folder", True))
                self.output_dir_var.set(cfg.get("output_dir", ""))
                self.recent_files = cfg.get("recent", [])
                self._refresh_recent_box()
            except Exception:
                pass

    def load_default_config(self):
        self.format_var.set("jpg")
        self.step_var.set(1)
        self.start_idx_var.set(0)
        self.overwrite_var.set(True)
        self.use_auto_folder_var.set(True)
        self.output_dir_var.set("")
        messagebox.showinfo("已恢复", "已恢复默认配置")

    def show_about(self):
        messagebox.showinfo("关于", "视频拆帧工具 - 改进版\n功能：拆帧、预览、保存配置、最近文件、导出日志\n（基于 OpenCV + Tkinter + Pillow）")

    # ---------- 预览 ----------
    def generate_preview(self):
        path = self.video_path_var.get().strip()
        if not path:
            self._set_preview(None, "无预览")
            return
        p = Path(path)
        if not p.is_file():
            self._set_preview(None, "无预览")
            return
        try:
            cap = cv2.VideoCapture(str(p))
            ret, frame = cap.read()
            cap.release()
            if not ret:
                self._set_preview(None, "读取首帧失败")
                return
            # 将 BGR -> RGB 转换并用 Pillow 显示缩略
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(img)
            pil.thumbnail((480, 320))
            self._set_preview(pil, None)
        except Exception as e:
            self._set_preview(None, f"预览错误: {e}")

    def _set_preview(self, pil_img: Image.Image or None, text: str or None):
        if pil_img:
            self.preview_img = ImageTk.PhotoImage(pil_img)
            self.preview_label.configure(image=self.preview_img, text="")
        else:
            self.preview_label.configure(image="", text=text or "无预览")

    # ---------- 日志 ----------
    def log(self, s: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", s + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def export_log(self):
        txt = self.log_text.get("1.0", "end").strip()
        if not txt:
            messagebox.showinfo("提示", "日志为空")
            return
        f = filedialog.asksaveasfilename(title="保存日志为", defaultextension=".txt", filetypes=[("文本文件", "*.txt")])
        if f:
            try:
                with open(f, "w", encoding="utf-8") as fh:
                    fh.write(txt)
                messagebox.showinfo("已保存", f"日志已保存到:\n{f}")
            except Exception as e:
                messagebox.showerror("错误", f"无法保存日志: {e}")

    # ---------- 启动/停止 拆帧 ----------
    def start_extraction(self):
        vid = self.video_path_var.get().strip()
        if not vid:
            messagebox.showerror("错误", "请先选择视频文件")
            return
        video_path = Path(vid)
        if not video_path.is_file():
            messagebox.showerror("错误", "视频文件不存在")
            return
        output_dir = self._get_output_dir()
        if not output_dir:
            messagebox.showerror("错误", "请先选择输出目录或启用自动创建")
            return
        fmt = self.format_var.get()
        step = int(self.step_var.get())
        start_idx = int(self.start_idx_var.get())
        overwrite = bool(self.overwrite_var.get())
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress_var.set(0.0)
        self.status_label.configure(text="准备中…")
        self.log(f"开始拆帧: {video_path} -> {output_dir} 格式={fmt} step={step} start={start_idx} overwrite={overwrite}")
        self.stop_event = threading.Event()
        def progress_cb(written, total, elapsed):
            def ui_update():
                percent = 0.0
                if total and total > 0:
                    expected_saves = max(1, (total + step - 1) // step)
                    percent = min(100.0, written / expected_saves * 100.0)
                else:
                    percent = min(100.0, written / 1000.0 * 100.0)
                self.progress_var.set(percent)
                if elapsed > 0 and written > 0:
                    per_frame = elapsed / written
                    est_remaining = 0
                    if total and total > 0:
                        expected_saves = max(1, (total + step - 1) // step)
                        remaining = max(0, expected_saves - written)
                        est_remaining = remaining * per_frame
                    self.status_label.configure(text=f"已写 {written} 帧，耗时 {elapsed:.1f}s，估计剩余 {est_remaining:.1f}s")
                else:
                    self.status_label.configure(text=f"已写 {written} 帧，耗时 {elapsed:.1f}s")
            self.master.after(0, ui_update)

        def worker():
            try:
                written = video_to_frames(
                    video_path,
                    output_dir,
                    fmt=fmt,
                    start_idx=start_idx,
                    step=step,
                    overwrite=overwrite,
                    progress_callback=progress_cb,
                    stop_flag=self.stop_event
                )
                self.master.after(0, lambda: self._on_finish(success=True, written=written, output_dir=output_dir))
            except Exception as e:
                self.master.after(0, lambda: self._on_finish(success=False, error=str(e)))

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def stop_extraction(self):
        if self.stop_event and not self.stop_event.is_set():
            self.stop_event.set()
            self.log("收到停止请求，正在终止…")
            self.stop_btn.configure(state="disabled")

    def _on_finish(self, success: bool, written: int = 0, output_dir: Path = None, error: str = ""):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        if success:
            self.progress_var.set(100.0)
            self.status_label.configure(text=f"完成，写入 {written} 帧")
            self.log(f"完成：写入 {written} 帧，保存至 {output_dir}")
            messagebox.showinfo("完成", f"已成功提取 {written} 帧\n保存至:\n{output_dir}")
        else:
            self.status_label.configure(text="发生错误")
            self.log(f"错误：{error}")
            messagebox.showerror("异常", error)
# ---------- 主入口 ----------
def main():
    root = tk.Tk()
    app = FrameExtractorApp(root)
    root.mainloop()
if __name__ == "__main__":
    main()
