import tkinter as tk
from tkinter import filedialog, messagebox
import cv2
import os
from pathlib import Path
def video_to_frames(video_path: Path, output_dir: Path):
    """把 video_path 拆成帧，保存到 output_dir（已存在则覆盖）"""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频文件: {video_path}")
    os.makedirs(output_dir, exist_ok=True)
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        filename = f"frame_{idx:06d}.jpg"
        cv2.imwrite(str(output_dir / filename), frame)
        idx += 1
    cap.release()
    return idx
def browse_video():
    """打开文件选择对话框，返回选中的视频路径"""
    filetypes = [("视频文件", "*.mp4 *.avi *.mov *.mkv"), ("所有文件", "*.*")]
    path = filedialog.askopenfilename(title="选择视频文件", filetypes=filetypes)
    if path:
        video_path_var.set(path)
def start_extraction():
    video_path = Path(video_path_var.get())
    if not video_path.is_file():
        messagebox.showerror("错误", "请先选择有效的视频文件")
        return
    # 自动创建同名文件夹
    output_dir = video_path.parent / video_path.stem
    try:
        frame_count = video_to_frames(video_path, output_dir)
        messagebox.showinfo(
            "完成",
            f"已成功提取 {frame_count} 帧\n保存至:\n{output_dir}"
        )
    except Exception as e:
        messagebox.showerror("异常", str(e))
# ------------------- GUI -------------------
root = tk.Tk()
root.title("视频拆帧工具")
root.geometry("460x150")
root.resizable(False, False)
video_path_var = tk.StringVar()
# 视频路径输入框 + 浏览按钮
frame_path = tk.Frame(root, padx=10, pady=10)
frame_path.pack(fill="x")
tk.Label(frame_path, text="视频文件:").grid(row=0, column=0, sticky="e")
entry = tk.Entry(frame_path, textvariable=video_path_var, width=40)
entry.grid(row=0, column=1, padx=5)
tk.Button(frame_path, text="浏览…", command=browse_video).grid(row=0, column=2)
# 开始按钮
frame_btn = tk.Frame(root, pady=10)
frame_btn.pack()
tk.Button(frame_btn, text="开始拆帧", width=20, command=start_extraction).pack()
root.mainloop()
