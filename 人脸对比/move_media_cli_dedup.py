#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
move_media_cli_dedup.py
在终端交互式菜单基础上增加文件内容去重功能（按哈希只保留一份）。
重构：改善变量与参数命名以提高可维护性，保留原有行为。
"""
from __future__ import annotations
import os
import shutil
from pathlib import Path
import sys
import hashlib
from collections import defaultdict
# 支持的扩展名（小写）
VIDEO_EXTS = {
    "mp4", "mkv", "mov", "avi", "m4v", "flv", "webm", "mpg", "mpeg", "wmv", "ts"
}
IMAGE_EXTS = {
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "heic"
}
# ---------- 媒体判断与移动 ----------
def get_media_type(file_path: Path) -> str | None:
    """判断文件类型：返回 'video' / 'image' / None"""
    try:
        if not file_path.is_file() and not file_path.is_symlink():
            return None
    except OSError:
        return None
    extension = file_path.suffix.lower().lstrip(".")
    if extension in VIDEO_EXTS:
        return "video"
    if extension in IMAGE_EXTS:
        return "image"
    return None
def make_unique_path(target_path: Path) -> Path:
    """若目标已存在，返回带 ' (n)' 的可用路径"""
    if not target_path.exists():
        return target_path
    parent_dir = target_path.parent
    base_name = target_path.stem
    suffix = target_path.suffix
    index = 1
    while True:
        candidate = parent_dir / f"{base_name} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1
def move_atomically(source_path: Path, destination_path: Path):
    """尝试使用 os.replace（同文件系统为原子），失败则使用 shutil.move"""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source_path, destination_path)
    except Exception:
        shutil.move(str(source_path), str(destination_path))
# ---------- 去重相关 ----------
def sha256_of_file(file_path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    """计算文件的 SHA-256 哈希（分块读取）"""
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
def find_duplicate_hash_groups(file_paths: list[Path], *, follow_symlinks: bool = False) -> dict[str, list[Path]]:
    """
    在给定路径列表中查找重复文件。
    返回：hash -> [paths...]
    优化：先按文件大小分组，只对大小相同组计算哈希。
    """
    size_to_paths: dict[int, list[Path]] = defaultdict(list)
    for path in file_paths:
        try:
            if not path.is_file():
                continue
            size_to_paths[path.stat().st_size].append(path)
        except OSError:
            continue
    hash_to_paths: dict[str, list[Path]] = defaultdict(list)
    for size, paths_with_same_size in size_to_paths.items():
        if len(paths_with_same_size) == 1:
            # 单文件不需要哈希比较（不是重复）
            continue
        for path in paths_with_same_size:
            try:
                file_hash = sha256_of_file(path)
                hash_to_paths[file_hash].append(path)
            except Exception:
                # 跳过无法读取的文件
                continue
    # 只保留重复组（至少两个路径）
    return {file_hash: paths for file_hash, paths in hash_to_paths.items() if len(paths) > 1}
def deduplicate_paths(target_paths: list[Path], *, keep_policy: str = "first", dry_run: bool = True, logger = print) -> tuple[int, int]:
    """
    对给定路径集合执行去重。
    keep_policy: 'first' 保留每组的第一个（按路径排序），'largest' 保留最大文件（等大小组无效），'newest' 保留最新修改时间
    dry_run: True 只模拟不删除
    返回 (duplicate_group_count, files_marked_or_removed_count)
    """
    # 收集所有文件
    collected_files: list[Path] = []
    for entry in target_paths:
        if entry.is_file():
            collected_files.append(entry)
        elif entry.is_dir():
            for root, dirs, files in os.walk(entry, followlinks=False):
                for filename in files:
                    file_path = Path(root) / filename
                    if file_path.is_file():
                        collected_files.append(file_path)

    # 找重复
    duplicate_groups = find_duplicate_hash_groups(collected_files)
    duplicate_group_count = 0
    files_removed_or_counted = 0
    for file_hash, group in duplicate_groups.items():
        # 对组内文件按可预测顺序排序
        group_sorted = sorted(group, key=lambda p: str(p))
        # 根据保留策略选择保留者
        if keep_policy == "first":
            keeper = group_sorted[0]
        elif keep_policy == "largest":
            keeper = max(group_sorted, key=lambda p: p.stat().st_size)
        elif keep_policy == "newest":
            keeper = max(group_sorted, key=lambda p: p.stat().st_mtime)
        else:
            keeper = group_sorted[0]
        logger(f"Duplicate group (hash={file_hash}):")
        for path in group_sorted:
            marker = "KEEP" if path == keeper else "DEL "
            logger(f"  {marker} {path}")
        duplicate_group_count += 1
        for path in group_sorted:
            if path == keeper:
                continue
            if not dry_run:
                try:
                    path.unlink()
                    files_removed_or_counted += 1
                except Exception as e:
                    logger(f"  Failed to delete {path}: {e}")
            else:
                files_removed_or_counted += 1
    return duplicate_group_count, files_removed_or_counted
# ---------- 扫描与迁移 ----------
def scan_and_move(source_dir: Path, video_directory: Path, image_directory: Path, preserve_structure: bool, log_file_path: Path | None = None):
    """扫描 source_dir 并移动媒体文件到对应目的地；打印并可记录日志"""
    logs: list[str] = []
    total_files_scanned = 0
    files_moved = 0
    move_errors = 0
    source_dir = source_dir.resolve()
    for root, dirs, files in os.walk(source_dir, followlinks=False):
        current_dir = Path(root)
        for filename in files:
            total_files_scanned += 1
            source_file = current_dir / filename
            media_type = get_media_type(source_file)
            if media_type is None:
                continue
            if preserve_structure:
                try:
                    relative_path = source_file.relative_to(source_dir)
                except Exception:
                    relative_path = Path(filename)
                subdir = relative_path.parent
                if media_type == "video":
                    destination_candidate = video_directory / subdir / source_file.name
                else:
                    destination_candidate = image_directory / subdir / source_file.name
            else:
                destination_candidate = (video_directory if media_type == "video" else image_directory) / source_file.name
            destination_unique = make_unique_path(destination_candidate)
            try:
                move_atomically(source_file, destination_unique)
                message = f"MOVED: {source_file} -> {destination_unique}"
                print(message)
                logs.append(message)
                files_moved += 1
            except Exception as e:
                error_message = f"ERROR: {source_file} -> {destination_unique}: {e}"
                print(error_message)
                logs.append(error_message)
                move_errors += 1
    summary = f"完成：扫描文件 {total_files_scanned} 个，移动 {files_moved} 个，错误 {move_errors} 个。"
    print(summary)
    logs.append(summary)
    if log_file_path:
        try:
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            with log_file_path.open("a", encoding="utf-8") as f:
                for line in logs:
                    f.write(line + "\n")
            print(f"日志已追加到：{log_file_path}")
        except Exception as e:
            print(f"写入日志失败：{e}")
# ---------- 菜单与交互 ----------
def prompt_directory(prompt_text: str, default: str | None = None) -> Path | None:
    """提示输入目录路径，允许输入空以取消"""
    while True:
        entry = input(f"{prompt_text}{' ['+default+']' if default else ''}: ").strip()
        if not entry:
            if default:
                entry = default
            else:
                print("已取消输入。")
                return None
        directory = Path(entry).expanduser().resolve()
        if directory.exists() and directory.is_dir():
            return directory
        else:
            print("路径不存在或不是目录，请重试，或按回车取消。")
def prompt_yes_no(prompt_text: str, default: bool = False) -> bool:
    """简单的是/否提示"""
    yes_no_hint = "Y/n" if default else "y/N"
    resp = input(f"{prompt_text} ({yes_no_hint}): ").strip().lower()
    if resp == "":
        return default
    return resp.startswith("y")
def show_menu():
    """主交互菜单循环"""
    source_directory: Path | None = None
    video_target_directory: Path | None = None
    image_target_directory: Path | None = None
    preserve_subdirs = False
    log_file_path: Path | None = None
    while True:
        print("\n====== 媒体迁移与去重（终端菜单） ======")
        print(f"1) 选择源目录（当前：{source_directory if source_directory else '未设置'})")
        print(f"2) 选择视频目标目录（当前：{video_target_directory if video_target_directory else '未设置'})")
        print(f"3) 选择图片目标目录（当前：{image_target_directory if image_target_directory else '未设置'})")
        print(f"4) 切换保留子目录结构（当前：{'是' if preserve_subdirs else '否'})")
        print(f"5) 设置日志文件（当前：{log_file_path if log_file_path else '不保存'})")
        print("6) 开始迁移")
        print("7) 迁移后去重（按哈希只保留一份）")
        print("8) 直接对指定目录去重（不迁移）")
        print("9) 帮助（显示支持的扩展名）")
        print("0) 退出")
        choice = input("选择操作编号: ").strip()
        if choice == "1":
            selected = prompt_directory("输入源目录路径（按回车取消）")
            if selected:
                source_directory = selected
        elif choice == "2":
            selected = prompt_directory("输入视频目标目录路径（按回车取消）")
            if selected:
                video_target_directory = selected
        elif choice == "3":
            selected = prompt_directory("输入图片目标目录路径（按回车取消）")
            if selected:
                image_target_directory = selected
        elif choice == "4":
            preserve_subdirs = not preserve_subdirs
            print(f"保留子目录结构已设置为：{'是' if preserve_subdirs else '否'}")
        elif choice == "5":
            entry = input("输入日志文件路径（空为不保存）: ").strip()
            if entry == "":
                log_file_path = None
            else:
                log_file_path = Path(entry).expanduser().resolve()
                print(f"日志将保存到：{log_file_path}")
        elif choice == "6":
            if not source_directory or not video_target_directory or not image_target_directory:
                print("请先设置源目录、视频目标目录和图片目标目录。")
                continue
            confirm = prompt_yes_no(
                f"确认开始迁移？\n源: {source_directory}\n视频目标: {video_target_directory}\n图片目标: {image_target_directory}\n保留子目录: {'是' if preserve_subdirs else '否'}",
                default=False
            )
            if not confirm:
                print("已取消迁移。")
                continue
            video_target_directory.mkdir(parents=True, exist_ok=True)
            image_target_directory.mkdir(parents=True, exist_ok=True)
            scan_and_move(source_directory, video_target_directory, image_target_directory, preserve_subdirs, log_file_path)
        elif choice == "7":
            # 去重选项，默认对视频目标和图片目标执行
            if not video_target_directory or not image_target_directory:
                print("请先设置视频目标和图片目标目录。")
                continue
            dry_run = prompt_yes_no("先进行模拟删除（dry-run）？选择 Yes 将不会实际删除文件", default=True)
            keep_choice = input("保留策略: 1) first (默认) 2) largest 3) newest. 选择 1/2/3: ").strip()
            keep_policy = {"1":"first","2":"largest","3":"newest"}.get(keep_choice, "first")
            print(f"将对以下目录去重：\n  {video_target_directory}\n  {image_target_directory}")
            confirm = prompt_yes_no("确认继续？", default=False)
            if not confirm:
                print("已取消去重。")
                continue
            print("开始去重（按哈希）…… 这可能需要一些时间。")
            duplicate_groups, files_count = deduplicate_paths([video_target_directory, image_target_directory], keep_policy=keep_policy, dry_run=dry_run, logger=print)
            print(f"去重完成：找到 {duplicate_groups} 个重复组，涉及文件将被标记或删除 {files_count} 个（dry_run={dry_run}）。")
        elif choice == "8":
            entry = input("输入要去重的目录（可多次输入多个，用逗号分隔），或直接输入单个路径: ").strip()
            if not entry:
                print("取消。")
                continue
            directories = [Path(p.strip()).expanduser().resolve() for p in entry.split(",") if p.strip()]
            directories = [d for d in directories if d.exists() and d.is_dir()]
            if not directories:
                print("没有有效目录。")
                continue
            dry_run = prompt_yes_no("先进行模拟删除（dry-run）？选择 Yes 将不会实际删除文件", default=True)
            keep_choice = input("保留策略: 1) first (默认) 2) largest 3) newest. 选择 1/2/3: ").strip()
            keep_policy = {"1":"first","2":"largest","3":"newest"}.get(keep_choice, "first")
            print("将对以下目录去重：")
            for d in directories:
                print(" ", d)
            confirm = prompt_yes_no("确认继续？", default=False)
            if not confirm:
                print("已取消去重。")
                continue
            duplicate_groups, files_count = deduplicate_paths(directories, keep_policy=keep_policy, dry_run=dry_run, logger=print)
            print(f"去重完成：找到 {duplicate_groups} 个重复组，涉及文件将被标记或删除 {files_count} 个（dry_run={dry_run}）。")
        elif choice == "9":
            print("支持的视频扩展名：", ", ".join(sorted(VIDEO_EXTS)))
            print("支持的图片扩展名：", ", ".join(sorted(IMAGE_EXTS)))
        elif choice == "0":
            print("退出。")
            break
        else:
            print("无效选择，请重试。")
if __name__ == "__main__":
    try:
        show_menu()
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(0)
