import os
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

def is_media_file(filename):
    # 定义视频和图片的扩展名
    video_extensions = ['.mp4', '.avi', '.mov', '.mkv']
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
    # 获取文件的扩展名
    _, ext = os.path.splitext(filename)
    # 判断是否是视频或图片文件
    return ext.lower() in video_extensions + image_extensions

def get_unique_filename(directory, filename):
    # 获取文件名和扩展名
    name, ext = os.path.splitext(filename)
    # 初始化计数器
    counter = 1
    # 生成唯一的文件名
    unique_filename = filename
    while os.path.exists(os.path.join(directory, unique_filename)):
        unique_filename = f"{name}_{counter}{ext}"
        counter += 1
    return unique_filename

def organize_media_files(source_dirs, target_dir, exclude_dirs, operation):
    # 确保目标目录存在
    os.makedirs(target_dir, exist_ok=True)
    # 遍历每个源目录
    for source_dir in source_dirs:
        for root, dirs, files in os.walk(source_dir):
            # 检查当前目录是否在排除列表中
            if any(excluded in root for excluded in exclude_dirs):
                # 如果当前目录在排除列表中，则跳过该目录及其子目录
                dirs[:] = []
                continue
            for file in files:
                if is_media_file(file):
                    # 获取源文件的完整路径
                    source_file = os.path.join(root, file)
                    # 获取目标文件的唯一名称
                    unique_filename = get_unique_filename(target_dir, file)
                    # 获取目标文件的完整路径
                    target_file = os.path.join(target_dir, unique_filename)
                    # 根据用户选择执行复制或移动操作
                    if operation == 'move':
                        shutil.move(source_file, target_file)
                    else:
                        shutil.copy2(source_file, target_file)

def start_organizing_thread():
    # 获取用户输入的源目录列表、目标目录、排除目录和操作选项
    source_dirs = list(source_dirs_listbox.get(0, tk.END))
    target_dir = target_dir_var.get()
    exclude_dirs = exclude_dirs_var.get().split(',')
    operation = operation_var.get()

    # 检查是否选择了源目录和目标目录
    if not source_dirs or not target_dir:
        messagebox.showwarning("Warning", "Please select at least one source directory and a target directory.")
        return

    # 在单独的线程中运行文件整理功能
    threading.Thread(target=organize_and_notify, args=(source_dirs, target_dir, exclude_dirs, operation)).start()

def organize_and_notify(source_dirs, target_dir, exclude_dirs, operation):
    # 执行文件整理操作
    organize_media_files(source_dirs, target_dir, exclude_dirs, operation)
    # 显示成功消息
    messagebox.showinfo("Success", "Files have been organized successfully.")

def add_source_directory():
    # 打开目录选择对话框并添加源目录到列表
    directory = filedialog.askdirectory()
    if directory:
        source_dirs_listbox.insert(tk.END, directory)

def remove_selected_source_directory():
    # 移除选中的源目录
    selected_indices = source_dirs_listbox.curselection()
    for index in reversed(selected_indices):
        source_dirs_listbox.delete(index)

def select_target_directory():
    # 打开目录选择对话框并设置目标目录
    directory = filedialog.askdirectory()
    target_dir_var.set(directory)

# 创建主窗口
root = tk.Tk()
root.title("Media Organizer")
root.geometry("500x400")

# 创建并放置组件
source_dirs_listbox = tk.Listbox(root, selectmode=tk.MULTIPLE, width=50, height=10)
source_dirs_listbox.pack(pady=5)

tk.Button(root, text="Add Source Directory", command=add_source_directory).pack(pady=5)
tk.Button(root, text="Remove Selected", command=remove_selected_source_directory).pack(pady=5)

target_dir_var = tk.StringVar()
exclude_dirs_var = tk.StringVar()
operation_var = tk.StringVar(value='copy')  # 默认选择复制操作

tk.Label(root, text="Target Directory:").pack(pady=5)
tk.Entry(root, textvariable=target_dir_var, width=50).pack(pady=5)
tk.Button(root, text="Browse", command=select_target_directory).pack(pady=5)

tk.Label(root, text="Exclude Folders (comma separated):").pack(pady=5)
tk.Entry(root, textvariable=exclude_dirs_var, width=50).pack(pady=5)

# 添加操作选项的单选按钮
tk.Label(root, text="Operation:").pack(pady=5)
tk.Radiobutton(root, text="Copy Files", variable=operation_var, value='copy').pack()
tk.Radiobutton(root, text="Move Files", variable=operation_var, value='move').pack()

tk.Button(root, text="Start Organizing", command=start_organizing_thread).pack(pady=20)

# 运行主循环
root.mainloop()
