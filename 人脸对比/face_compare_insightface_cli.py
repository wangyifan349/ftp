# face_compare_insightface_cli.py
# 双击运行后在控制台以菜单交互方式使用 InsightFace 进行人脸比对
import sys, os, json
import numpy as np
import cv2
import insightface
from insightface.app import FaceAnalysis
# --------------- 辅助函数（尽量少封装，但保留必要步骤） ---------------
def print_menu():
    print("\n=== InsightFace 人脸比对（交互式菜单） ===")
    print("1) 选择模型（默认: antelope）")
    print("2) 设置余弦相似度阈值（默认: 0.45）")
    print("3) 设置 L2 阈值（默认: 1.0）")
    print("4) 设置图片 A 路径（当前: {})".format(img_a if 'img_a' in globals() else "未设置"))
    print("5) 设置图片 B 路径（当前: {})".format(img_b if 'img_b' in globals() else "未设置"))
    print("6) 开始比对（需要已设置图片 A 和 B）")
    print("7) 将上次结果保存为 JSON 文件（需先比对）")
    print("0) 退出")
    print("=========================================\n")
def input_path(prompt):
    p = input(prompt).strip().strip('"').strip("'")
    return p
def load_bgr(path):
    img = cv2.imread(path)
    return img
def prepare_app(model_name):
    ctx_id = 0 if insightface.utils.has_cuda() else -1
    app = FaceAnalysis(name=model_name)
    app.prepare(ctx_id=ctx_id, det_size=(640,640))
    return app
# --------------- 默认参数 ---------------
model_name = "antelope"   # 推荐 antelope -> 512-d
threshold_cosine = 0.45
threshold_l2 = 1.0
img_a = None
img_b = None
last_result = None
app = None
# --------------- 主循环 ---------------
while True:
    print_menu()
    choice = input("输入选项编号: ").strip()
    if choice == "0":
        print("退出。")
        sys.exit(0)
    elif choice == "1":
        print("可选模型示例: antelope (推荐), r50, r34, buffalo")
        m = input("输入模型名（回车保持 {}）: ".format(model_name)).strip()
        if m:
            model_name = m
            app = None
            print("模型设为:", model_name)
    elif choice == "2":
        v = input("输入余弦相似度阈值（当前 {}）: ".format(threshold_cosine)).strip()
        try:
            if v:
                threshold_cosine = float(v)
        except:
            print("无效输入，保持原值。")
        print("当前余弦阈值:", threshold_cosine)
    elif choice == "3":
        v = input("输入 L2 阈值（当前 {}）: ".format(threshold_l2)).strip()
        try:
            if v:
                threshold_l2 = float(v)
        except:
            print("无效输入，保持原值。")
        print("当前 L2 阈值:", threshold_l2)
    elif choice == "4":
        p = input_path("输入图片 A 的完整路径: ")
        img_a = p
        print("图片 A 设置为:", img_a)
    elif choice == "5":
        p = input_path("输入图片 B 的完整路径: ")
        img_b = p
        print("图片 B 设置为:", img_b)
    elif choice == "6":
        if not img_a or not img_b:
            print("请先设置图片 A 和 B 的路径（选项 4 与 5）。")
            continue
        if not os.path.isfile(img_a):
            print("找不到图片 A:", img_a); continue
        if not os.path.isfile(img_b):
            print("找不到图片 B:", img_b); continue
        print("准备模型（如需首次下载模型请耐心等待）... 模型:", model_name)
        app = prepare_app(model_name)
        img1 = load_bgr(img_a)
        img2 = load_bgr(img_b)
        if img1 is None:
            print("无法读取图片 A:", img_a); continue
        if img2 is None:
            print("无法读取图片 B:", img_b); continue
        faces1 = app.get(img1)
        faces2 = app.get(img2)
        if len(faces1) == 0 or len(faces2) == 0:
            print("至少一张图片未检测到人脸。请确保图片有人脸且清晰。")
            continue
        emb1 = faces1[0].embedding.astype(np.float64)
        emb2 = faces2[0].embedding.astype(np.float64)
        l2 = float(np.linalg.norm(emb1 - emb2))
        n1 = np.linalg.norm(emb1); n2 = np.linalg.norm(emb2)
        if n1 == 0 or n2 == 0:
            print("embedding 为零向量，无法计算余弦相似度。")
            continue
        cos_sim = float(np.dot(emb1, emb2) / (n1 * n2))
        cos_dist = 1.0 - cos_sim
        verdicts = {
            "cosine_match": cos_sim >= threshold_cosine,
            "l2_match": l2 <= threshold_l2
        }
        last_result = {
            "image1": img_a,
            "image2": img_b,
            "model": model_name,
            "embedding_dim": len(emb1),
            "cosine_similarity": cos_sim,
            "cosine_distance": cos_dist,
            "l2_distance": l2,
            "thresholds": {"cosine": threshold_cosine, "l2": threshold_l2},
            "verdicts": verdicts
        }
        print("\n--- 比对结果 ---")
        print("模型:", model_name)
        print("cosine_similarity: {:.6f}".format(cos_sim))
        print("cosine_distance: {:.6f}".format(cos_dist))
        print("l2_distance: {:.6f}".format(l2))
        print("判定 -> cosine_match: {}, l2_match: {}".format(verdicts["cosine_match"], verdicts["l2_match"]))
        print("-----------------\n")
    elif choice == "7":
        if last_result is None:
            print("暂无比对结果，请先执行比对（选项 6）。")
            continue
        outp = input("输入要保存的 JSON 文件名（回车使用 last_result.json）: ").strip()
        if not outp:
            outp = "last_result.json"
        with open(outp, "w", encoding="utf-8") as f:
            json.dump(last_result, f, ensure_ascii=False, indent=2)
        print("已保存到:", outp)
    else:
        print("无效选项，请重试。")
