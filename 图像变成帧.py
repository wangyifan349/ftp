#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path

import cv2               # OpenCV
from PIL import Image    # Pillow


def safe_folder_name(name: str) -> str:
    """把文件系统不允许的字符替换为下划线，返回合法文件夹名。"""
    illegal = r'<>:"/\\|?*'
    for ch in illegal:
        name = name.replace(ch, "_")
    return name.strip()


def make_unique_path(base_path: Path) -> Path:
    """若文件夹已存在则追加 (1)、(2)… 直至得到唯一路径。"""
    if not base_path.exists():
        return base_path

    counter = 1
    while True:
        candidate = base_path.with_name(f"{base_path.name} ({counter})")
        if not candidate.exists():
            return candidate
        counter += 1


def extract_frames(video_path: Path, out_dir: Path, overwrite: bool = False) -> None:
    """使用 OpenCV 读取视频，Pillow 保存每帧为 PNG。"""
    out_dir.mkdir(parents=True, exist_ok=True)

    if not overwrite and any(out_dir.iterdir()):
        print(f"⚠️ 目标文件夹已有内容，已跳过 {video_path.name}")
        return

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"❌ 无法打开视频文件: {video_path}")
        return

    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        out_path = out_dir / f"frame_{idx:05d}.png"
        img.save(out_path, format="PNG")
        idx += 1

    cap.release()
    print(f"✅ 完成: {video_path.name} → {out_dir} ({idx} 帧)")


def process_videos(input_dir: Path, output_root: Path, overwrite: bool = False) -> None:
    """遍历目录下所有常见视频文件并拆分为帧。"""
    video_exts = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm"}

    for video_path in input_dir.rglob("*"):
        if video_path.suffix.lower() not in video_exts:
            continue

        folder_name = safe_folder_name(video_path.stem)
        target_dir = make_unique_path(output_root / folder_name)
        extract_frames(video_path, target_dir, overwrite=overwrite)


def main() -> None:
    # ------------------- 交互式获取路径 -------------------
    input_dir_str = input("请输入包含视频的目录路径： ").strip()
    output_dir_str = input("请输入要保存帧图片的根目录路径： ").strip()
    overwrite_str = input("如果目标文件夹已存在，是否强制覆盖？(y/N)： ").strip().lower()

    input_dir = Path(input_dir_str).expanduser().resolve()
    output_dir = Path(output_dir_str).expanduser().resolve()
    overwrite = overwrite_str == "y"

    if not input_dir.is_dir():
        sys.exit("❗ 输入路径不是有效目录，请重新运行并提供正确路径。")

    output_dir.mkdir(parents=True, exist_ok=True)

    process_videos(input_dir, output_dir, overwrite=overwrite)


if __name__ == "__main__":
    main()
