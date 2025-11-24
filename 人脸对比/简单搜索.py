#!/usr/bin/env python3
import json, os, numpy as np, cv2, dlib
# -------------------- 配置 --------------------
gallery_dir = "gallery"                     # 包含所有已知人脸的目录
query_path = "query.jpg"                    # 待搜索的人脸图片
shape_predictor_path = "shape_predictor_5_face_landmarks.dat"
face_rec_model_path = "dlib_face_recognition_resnet_model_v1.dat"
threshold = 0.6                             # 判定为同一人的距离阈值（可选）
# -------------------- 初始化模型 --------------------
detector = dlib.get_frontal_face_detector()
shape_predictor = dlib.shape_predictor(shape_predictor_path)
face_rec_model = dlib.face_recognition_model_v1(face_rec_model_path)
def get_descriptor(img_path):
    """读取图片 → 检测第一张人脸 → 返回 128‑D 特征向量"""
    img = cv2.cvtColor(cv2.imread(img_path), cv2.COLOR_BGR2RGB)
    rect = detector(img, 1)[0]               # 只取第一张检测到的人脸
    shape = shape_predictor(img, rect)
    return np.asarray(face_rec_model.compute_face_descriptor(img, shape), float)
# -------------------- 预计算库中所有图片的特征 --------------------
gallery_desc = {}
for fname in os.listdir(gallery_dir):
    fpath = os.path.join(gallery_dir, fname)
    if not fpath.lower().endswith(('.png', '.jpg', '.jpeg')):
        continue
    try:
        gallery_desc[fname] = get_descriptor(fpath)
    except Exception:
        # 未检测到人脸或读取错误，直接跳过
        continue
# -------------------- 对查询图片进行全库比对 --------------------
query_desc = get_descriptor(query_path)
# 保存每张库图的距离信息
comparisons = []
for name, desc in gallery_desc.items():
    dist = float(np.linalg.norm(query_desc - desc))
    comparisons.append({
        "file": name,
        "distance": dist,
        "match": dist <= threshold   # 可根据阈值标记是否匹配
    })
# -------------------- 降序排序（距离从大到小） --------------------
comparisons.sort(key=lambda x: x["distance"], reverse=True)
# -------------------- 输出结果 --------------------
result = {
    "query": query_path,
    "threshold": threshold,
    "comparisons": comparisons
}
print(json.dumps(result, ensure_ascii=False, indent=2))
