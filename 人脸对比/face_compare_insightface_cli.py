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
    print("4) 设置图片 A 路径（当前: {})".format(image_path_a if 'image_path_a' in globals() else "未设置"))
    print("5) 设置图片 B 路径（当前: {})".format(image_path_b if 'image_path_b' in globals() else "未设置"))
    print("6) 开始比对（需要已设置图片 A 和 B）")
    print("7) 将上次结果保存为 JSON 文件（需先比对）")
    print("0) 退出")
    print("=========================================\n")
def input_path(prompt):
    path_input = input(prompt).strip().strip('"').strip("'")
    return path_input
def load_bgr(path):
    image_bgr = cv2.imread(path)
    return image_bgr
def prepare_app(model_name):
    ctx_id = 0 if insightface.utils.has_cuda() else -1
    face_app = FaceAnalysis(name=model_name)
    face_app.prepare(ctx_id=ctx_id, det_size=(640,640))
    return face_app
# --------------- 默认参数 ---------------
selected_model = "antelope"   # 推荐 antelope -> 512-d
threshold_cosine = 0.45
threshold_l2 = 1.0
image_path_a = None
image_path_b = None
last_result = None
face_app = None
# --------------- 主循环 ---------------
while True:
    print_menu()
    menu_choice = input("输入选项编号: ").strip()
    if menu_choice == "0":
        print("退出。")
        sys.exit(0)
    elif menu_choice == "1":
        print("可选模型示例: antelope (推荐), r50, r34, buffalo")
        model_input = input("输入模型名（回车保持 {}）: ".format(selected_model)).strip()
        if model_input:
            selected_model = model_input
            face_app = None
            print("模型设为:", selected_model)
    elif menu_choice == "2":
        value_input = input("输入余弦相似度阈值（当前 {}）: ".format(threshold_cosine)).strip()
        try:
            if value_input:
                threshold_cosine = float(value_input)
        except:
            print("无效输入，保持原值。")
        print("当前余弦阈值:", threshold_cosine)
    elif menu_choice == "3":
        value_input = input("输入 L2 阈值（当前 {}）: ".format(threshold_l2)).strip()
        try:
            if value_input:
                threshold_l2 = float(value_input)
        except:
            print("无效输入，保持原值。")
        print("当前 L2 阈值:", threshold_l2)
    elif menu_choice == "4":
        path_value = input_path("输入图片 A 的完整路径: ")
        image_path_a = path_value
        print("图片 A 设置为:", image_path_a)
    elif menu_choice == "5":
        path_value = input_path("输入图片 B 的完整路径: ")
        image_path_b = path_value
        print("图片 B 设置为:", image_path_b)
    elif menu_choice == "6":
        if not image_path_a or not image_path_b:
            print("请先设置图片 A 和 B 的路径（选项 4 与 5）。")
            continue
        if not os.path.isfile(image_path_a):
            print("找不到图片 A:", image_path_a); continue
        if not os.path.isfile(image_path_b):
            print("找不到图片 B:", image_path_b); continue
        print("准备模型（如需首次下载模型请耐心等待）... 模型:", selected_model)
        face_app = prepare_app(selected_model)
        image_a = load_bgr(image_path_a)
        image_b = load_bgr(image_path_b)
        if image_a is None:
            print("无法读取图片 A:", image_path_a); continue
        if image_b is None:
            print("无法读取图片 B:", image_path_b); continue
        faces_a = face_app.get(image_a)
        faces_b = face_app.get(image_b)
        if len(faces_a) == 0 or len(faces_b) == 0:
            print("至少一张图片未检测到人脸。请确保图片有人脸且清晰。")
            continue
        embedding_a = faces_a[0].embedding.astype(np.float64)
        embedding_b = faces_b[0].embedding.astype(np.float64)
        l2_distance = float(np.linalg.norm(embedding_a - embedding_b))
        norm_a = np.linalg.norm(embedding_a); norm_b = np.linalg.norm(embedding_b)
        if norm_a == 0 or norm_b == 0:
            print("embedding 为零向量，无法计算余弦相似度。")
            continue
        cosine_similarity = float(np.dot(embedding_a, embedding_b) / (norm_a * norm_b))
        cosine_distance = 1.0 - cosine_similarity
        verdicts = {
            "cosine_match": cosine_similarity >= threshold_cosine,
            "l2_match": l2_distance <= threshold_l2
        }
        last_result = {
            "image1": image_path_a,
            "image2": image_path_b,
            "model": selected_model,
            "embedding_dim": len(embedding_a),
            "cosine_similarity": cosine_similarity,
            "cosine_distance": cosine_distance,
            "l2_distance": l2_distance,
            "thresholds": {"cosine": threshold_cosine, "l2": threshold_l2},
            "verdicts": verdicts
        }
        print("\n--- 比对结果 ---")
        print("模型:", selected_model)
        print("cosine_similarity: {:.6f}".format(cosine_similarity))
        print("cosine_distance: {:.6f}".format(cosine_distance))
        print("l2_distance: {:.6f}".format(l2_distance))
        print("判定 -> cosine_match: {}, l2_match: {}".format(verdicts["cosine_match"], verdicts["l2_match"]))
        print("-----------------\n")
    elif menu_choice == "7":
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
