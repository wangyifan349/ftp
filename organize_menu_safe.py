#!/usr/bin/env python3
import os
import shutil
import hashlib
import sys
import traceback
from pathlib import Path
from datetime import datetime
# ---------- 配置 ----------
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.heic'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.hevc', '.3gp'}
HASH_BUFFER_SIZE = 65536
LOG_FILE_NAME = "organized_actions.log"
# ---------- 工具函数 ----------
def log_message(message):
    timestamp = datetime.now().isoformat(sep=' ', timespec='seconds')
    line = f"{timestamp} - {message}"
    try:
        with open(LOG_FILE_NAME, 'a', encoding='utf-8') as log_file:
            log_file.write(line + "\n")
    except Exception:
        pass
    print(line)
def clear_screen():
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')
def prompt_input(prompt_text):
    sys.stdout.write(prompt_text)
    sys.stdout.flush()
    return sys.stdin.readline().strip()

def prompt_choice(prompt_text):
    sys.stdout.write(prompt_text + " ")
    sys.stdout.flush()
    return sys.stdin.readline().strip()

def is_image_suffix(suffix):
    return suffix.lower() in IMAGE_EXTENSIONS

def is_video_suffix(suffix):
    return suffix.lower() in VIDEO_EXTENSIONS

def get_type_folder_from_suffix(suffix):
    if is_image_suffix(suffix):
        return 'Images'
    if is_video_suffix(suffix):
        return 'Videos'
    return 'Others'

def ensure_directory_exists(directory_path):
    try:
        Path(directory_path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as exc:
        log_message(f"无法创建目录 {directory_path}: {exc}")
        return False

def has_read_permission(path_str):
    try:
        return os.access(path_str, os.R_OK)
    except Exception:
        return False

def has_write_permission(path_str):
    try:
        return os.access(path_str, os.W_OK)
    except Exception:
        return False

def compute_sha256_safe(file_path_str):
    try:
        hasher = hashlib.sha256()
        with open(file_path_str, 'rb') as f:
            while True:
                chunk = f.read(HASH_BUFFER_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as exc:
        log_message(f"无法计算哈希 {file_path_str}: {exc}")
        return None

def generate_unique_path_no_conflict(target_dir_str, file_name):
    target_dir = Path(target_dir_str)
    candidate = target_dir / file_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while True:
        new_name = f"{stem}_{counter}{suffix}"
        new_candidate = target_dir / new_name
        if not new_candidate.exists():
            return new_candidate
        counter += 1

def safe_move_or_copy(src_path_obj, dst_path_obj, do_copy, dry_run):
    src_str = str(src_path_obj)
    dst_str = str(dst_path_obj)
    if not has_read_permission(src_str):
        log_message(f"跳过（无读取权限）: {src_str}")
        return
    parent_dir = dst_path_obj.parent
    if not ensure_directory_exists(parent_dir):
        log_message(f"跳过（无法创建目标目录）: {dst_str}")
        return
    if not has_write_permission(str(parent_dir)):
        log_message(f"跳过（目标目录无写权限）: {parent_dir}")
        return
    if dry_run:
        action_label = "COPY" if do_copy else "MOVE"
        log_message(f"[DRY RUN] {action_label}: {src_str} -> {dst_str}")
        return
    try:
        if do_copy:
            shutil.copy2(src_str, dst_str)
            log_message(f"已复制: {src_str} -> {dst_str}")
        else:
            shutil.move(src_str, dst_str)
            log_message(f"已移动: {src_str} -> {dst_str}")
    except PermissionError as perm_err:
        log_message(f"权限错误: {src_str} -> {dst_str}: {perm_err}")
    except Exception as exc:
        log_message(f"操作失败: {src_str} -> {dst_str}: {exc}")

def safe_remove_file(path_obj, dry_run):
    path_str = str(path_obj)
    if not path_obj.exists():
        log_message(f"删除跳过（不存在）: {path_str}")
        return
    if not has_write_permission(path_str):
        log_message(f"删除跳过（无写权限）: {path_str}")
        return
    if dry_run:
        log_message(f"[DRY RUN] 删除: {path_str}")
        return
    try:
        path_obj.unlink()
        log_message(f"已删除: {path_str}")
    except PermissionError as perm_err:
        log_message(f"删除权限错误: {path_str}: {perm_err}")
    except Exception as exc:
        log_message(f"删除失败: {path_str}: {exc}")

def collect_all_files_recursively(source_root_str):
    accumulator = []
    for root, _, files in os.walk(source_root_str):
        for fname in files:
            accumulator.append((root, fname))
    return accumulator

def collect_all_files_recursively_in_destination(destination_root_str):
    accumulator = []
    for root, _, files in os.walk(destination_root_str):
        for fname in files:
            accumulator.append((root, fname))
    return accumulator
# ---------- 主要组织逻辑 ----------
def perform_organization(source_root_path, destination_root_path, do_copy_flag, do_rename_flag, dry_run_flag):
    file_entries = collect_all_files_recursively(str(source_root_path))
    index = 0
    total_files = len(file_entries)
    while index < total_files:
        root_dir, file_name = file_entries[index]
        source_file_path = Path(root_dir) / file_name
        folder_name = get_type_folder_from_suffix(source_file_path.suffix)
        destination_subdir = Path(destination_root_path) / folder_name
        if do_rename_flag:
            destination_file_path = generate_unique_path_no_conflict(str(destination_subdir), file_name)
        else:
            destination_file_path = destination_subdir / file_name
            if destination_file_path.exists():
                destination_file_path = generate_unique_path_no_conflict(str(destination_subdir), file_name)
        safe_move_or_copy(source_file_path, destination_file_path, do_copy_flag, dry_run_flag)
        index += 1
    hash_map = {}
    dst_entries = collect_all_files_recursively_in_destination(str(destination_root_path))
    j = 0
    total_dst = len(dst_entries)
    while j < total_dst:
        root_dir, file_name = dst_entries[j]
        candidate_path = Path(root_dir) / file_name
        candidate_str = str(candidate_path)
        file_hash = compute_sha256_safe(candidate_str)
        if file_hash is None:
            log_message(f"跳过去重（无法哈希）: {candidate_str}")
        else:
            if file_hash in hash_map:
                existing_path_obj = hash_map[file_hash]
                safe_remove_file(candidate_path, dry_run_flag)
                log_message(f"重复文件: {candidate_str} 与 {existing_path_obj} 相同，已处理")
            else:
                hash_map[file_hash] = candidate_str
        j += 1
# ---------- 菜单界面 ----------
def print_menu_status(source_root_path, destination_root_path, do_copy_flag, do_rename_flag, dry_run_flag):
    clear_screen()
    print("=== 文件整理工具（按扩展名归类，安全模式） ===")
    print("源目录: " + str(source_root_path))
    print("目标目录: " + str(destination_root_path))
    print("复制而非移动: " + ("是" if do_copy_flag else "否"))
    print("冲突时重命名: " + ("是" if do_rename_flag else "否"))
    print("模拟运行 (dry-run): " + ("是" if dry_run_flag else "否"))
    print("")
    print("1) 设置源目录")
    print("2) 设置目标目录")
    print("3) 切换复制/移动")
    print("4) 切换冲突重命名")
    print("5) 切换 dry-run")
    print("6) 开始整理（含权限检查与去重）")
    print("7) 查看日志文件（最近 20 行）")
    print("8) 退出")
def show_recent_logs(max_lines):
    try:
        lines = []
        with open(LOG_FILE_NAME, 'r', encoding='utf-8') as logf:
            for line in logf:
                lines.append(line.rstrip('\n'))
        total = len(lines)
        start = total - max_lines
        if start < 0:
            start = 0
        i = start
        while i < total:
            print(lines[i])
            i += 1
    except FileNotFoundError:
        print("日志文件不存在。")
    except Exception as exc:
        print(f"读取日志失败: {exc}")

def main_loop():
    source_root = Path.cwd()
    destination_root = Path.cwd() / "organized"
    copy_flag = False
    rename_flag = True
    dry_run_flag = True
    running_flag = True
    while running_flag:
        print_menu_status(source_root, destination_root, copy_flag, rename_flag, dry_run_flag)
        user_choice = prompt_choice("输入选项编号并回车:")
        if user_choice == "1":
            val = prompt_input("输入源目录完整路径: ")
            if val != "":
                candidate = Path(val).expanduser().resolve()
                if candidate.exists() and candidate.is_dir():
                    source_root = candidate
                else:
                    print("无效目录，请确认路径存在且为目录。")
                    prompt_input("按回车继续。")
        elif user_choice == "2":
            val = prompt_input("输入目标目录完整路径: ")
            if val != "":
                candidate = Path(val).expanduser().resolve()
                if candidate.exists() and candidate.is_dir():
                    destination_root = candidate
                else:
                    try:
                        candidate.mkdir(parents=True, exist_ok=True)
                        destination_root = candidate
                    except Exception as exc:
                        print(f"无法创建目标目录: {exc}")
                        prompt_input("按回车继续。")
        elif user_choice == "3":
            copy_flag = not copy_flag
        elif user_choice == "4":
            rename_flag = not rename_flag
        elif user_choice == "5":
            dry_run_flag = not dry_run_flag
        elif user_choice == "6":
            print("")
            print("风险提示:")
            print(" - 脚本仅根据扩展名分类，不解析文件内容。")
            print(" - 当不使用 dry-run 且选择移动时，源文件将被移动，可能不可恢复。")
            print(" - 将检查读/写权限并在无法操作时跳过。")
            confirm = prompt_input("确认继续执行？输入 YES 以继续: ")
            if confirm == "YES":
                perform_organization(source_root, destination_root, copy_flag, rename_flag, dry_run_flag)
                prompt_input("整理完成。按回车返回菜单。")
        elif user_choice == "7":
            show_recent_logs(20)
            prompt_input("按回车返回菜单。")
        elif user_choice == "8":
            running_flag = False
        else:
            prompt_input("无效选项，按回车继续。")
    print("退出。")
if __name__ == "__main__":
    main_loop()
