#!/usr/bin/env python3
"""
face_search_interactive.py

交互式人脸检索（高精度，线程池并行）。
运行后会显示菜单提示用户输入查询图片路径、图库目录、top_k、线程数等，并校验路径后开始检索。
仅依赖: face_recognition, opencv-python, numpy
"""

import os
import glob
import cv2
import sys
import numpy as np
import face_recognition
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

# 可调参数
FACE_DETECT_MODEL = "cnn"   # "cnn" 更高精度；若太慢可改为 "hog"
MAX_DISTANCE = 1.2

def prompt_input(prompt: str, default: str = None) -> str:
    if default:
        resp = input(f"{prompt} [{default}]: ").strip()
        return resp if resp else default
    else:
        return input(f"{prompt}: ").strip()

def load_image_rgb(path: str) -> np.ndarray:
    img_bgr = cv2.imread(path)
    if img_bgr is None:
        raise IOError(f"无法读取图片: {path}")
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

def compute_encodings_and_locations(image_rgb: np.ndarray):
    locations = face_recognition.face_locations(image_rgb, model=FACE_DETECT_MODEL)
    encodings = face_recognition.face_encodings(image_rgb, locations)
    return encodings, locations

def distance_to_similarity(distance: float, max_dist: float = MAX_DISTANCE) -> float:
    if distance <= 0:
        return 1.0
    sim = 1.0 - (distance / max_dist)
    return max(0.0, min(1.0, sim))

def gather_image_paths(folder: str) -> List[str]:
    exts = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp")
    paths = []
    for e in exts:
        paths.extend(glob.glob(os.path.join(folder, e)))
    return sorted(set(paths))

def single_image_best_match(img_path: str, query_encoding: np.ndarray):
    img_rgb = load_image_rgb(img_path)
    encs, locs = compute_encodings_and_locations(img_rgb)
    if not encs:
        return None
    dists = np.linalg.norm(np.asarray(encs) - query_encoding, axis=1)
    idx = int(np.argmin(dists))
    best_dist = float(dists[idx])
    best_sim = float(distance_to_similarity(best_dist))
    best_loc = tuple(locs[idx])
    return {
        "image_path": img_path,
        "face_location": best_loc,
        "distance": best_dist,
        "similarity": best_sim
    }

def search_similar_faces_interactive(query_img_path: str, images_folder: str, top_k: int, num_workers: int):
    q_img = load_image_rgb(query_img_path)
    q_encs, q_locs = compute_encodings_and_locations(q_img)
    if not q_encs:
        raise RuntimeError("查询图片中未检测到人脸。")
    query_encoding = q_encs[0]

    image_paths = gather_image_paths(images_folder)
    if not image_paths:
        raise RuntimeError("目标文件夹未找到支持的图片文件。")

    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=num_workers) as exe:
        futures = {exe.submit(single_image_best_match, p, query_encoding): p for p in image_paths}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                res = fut.result()
                if res:
                    results.append(res)
            except Exception as e:
                errors.append(f"{p}: {e}")

    results_sorted = sorted(results, key=lambda x: x["similarity"], reverse=True)
    return results_sorted[:top_k], errors

def draw_and_save_results(results: List[Dict], query_image_path: str = None, out_folder: str = "results"):
    os.makedirs(out_folder, exist_ok=True)
    if query_image_path:
        try:
            q_rgb = load_image_rgb(query_image_path)
            q_bgr = cv2.cvtColor(q_rgb, cv2.COLOR_RGB2BGR)
            q_encs, q_locs = compute_encodings_and_locations(q_rgb)
            for loc in q_locs:
                top, right, bottom, left = loc
                cv2.rectangle(q_bgr, (left, top), (right, bottom), (0,255,0), 2)
            cv2.imwrite(os.path.join(out_folder, "query_boxed.jpg"), q_bgr)
        except Exception:
            pass

    for i, item in enumerate(results, start=1):
        try:
            img_rgb = load_image_rgb(item["image_path"])
            img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
            top, right, bottom, left = item["face_location"]
            cv2.rectangle(img_bgr, (left, top), (right, bottom), (255,0,0), 2)
            label = f"{i}: sim={item['similarity']:.4f} dist={item['distance']:.4f}"
            cv2.putText(img_bgr, label, (left, max(10, top-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2)
            out_path = os.path.join(out_folder, f"rank_{i:02d}_" + os.path.basename(item["image_path"]))
            cv2.imwrite(out_path, img_bgr)
        except Exception:
            continue

def print_results(results: List[Dict]):
    print("\n检索结果（按相似度降序）")
    print("排名\t相似度\t距离\t图片路径")
    for idx, m in enumerate(results, start=1):
        print(f"{idx}\t{m['similarity']:.4f}\t{m['distance']:.4f}\t{m['image_path']}")

def interactive_menu():
    print("=== 人脸相似度检索（交互式）===\n")

    while True:
        query = prompt_input("请输入查询图片路径（或输入 q 退出）")
        if query.lower() == 'q':
            print("退出。")
            return

        if not os.path.isfile(query):
            print("错误：查询图片不存在，请重新输入。")
            continue

        folder = prompt_input("请输入图库文件夹路径")
        if not os.path.isdir(folder):
            print("错误：图库文件夹不存在，请重新输入。")
            continue

        top_k_str = prompt_input("要返回的结果数量 top_k", "10")
        try:
            top_k = int(top_k_str)
            if top_k <= 0:
                raise ValueError()
        except ValueError:
            print("错误：top_k 必须为正整数。")
            continue

        workers_str = prompt_input("线程数（建议与 CPU 核心数相近）", "8")
        try:
            workers = int(workers_str)
            if workers <= 0:
                raise ValueError()
        except ValueError:
            print("错误：线程数必须为正整数。")
            continue

        print("\n配置确认：")
        print(f" - 查询图片: {query}")
        print(f" - 图库文件夹: {folder}")
        print(f" - top_k: {top_k}")
        print(f" - 线程数: {workers}")
        ok = prompt_input("确认开始检索？(y/n)", "y")
        if ok.lower() != 'y':
            print("已取消，回到主菜单。\n")
            continue

        try:
            results, errors = search_similar_faces_interactive(query, folder, top_k, workers)
        except Exception as e:
            print(f"检索失败: {e}")
            continue

        if not results:
            print("未找到匹配人脸。")
        else:
            print_results(results)
            draw_and_save_results(results, query_image_path=query, out_folder="results")
            print(f"\n已将带标注的前 {len(results)} 个结果保存到 ./results 文件夹。")

        if errors:
            print("\n部分文件处理时出现错误并被跳过：")
            for e in errors:
                print(" -", e)

        again = prompt_input("\n是否继续进行新的检索？(y/n)", "n")
        if again.lower() != 'y':
            print("退出。")
            return
        print("\n")  # 循环返回主菜单

if __name__ == "__main__":
    try:
        interactive_menu()
    except KeyboardInterrupt:
        print("\n用户中断，退出。")
        sys.exit(0)
