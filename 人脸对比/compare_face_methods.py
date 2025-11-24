#!/usr/bin/env python3
# face_compare_euclidean.py
# 使用 face_recognition 的 face_distance（欧氏距离）比较两张图片
# 注：直接指定图片路径，输出 JSON

import os
import json
import numpy as np
import face_recognition

# 配置：修改为你的图片路径与阈值
image_a_path = "a.jpg"
image_b_path = "b.jpg"
threshold = 0.6  # 距离阈值，越小越严格

# 检查文件存在性
if not os.path.exists(image_a_path):
    raise FileNotFoundError("File not found: " + image_a_path)
if not os.path.exists(image_b_path):
    raise FileNotFoundError("File not found: " + image_b_path)

# 加载并计算编码（逐步写，避免列表表达式）
image_a = face_recognition.load_image_file(image_a_path)
encodings_a = face_recognition.face_encodings(image_a)
if len(encodings_a) == 0:
    raise RuntimeError("No face encoding found in image: " + image_a_path)
encoding_a = encodings_a[0]

image_b = face_recognition.load_image_file(image_b_path)
encodings_b = face_recognition.face_encodings(image_b)
if len(encodings_b) == 0:
    raise RuntimeError("No face encoding found in image: " + image_b_path)
encoding_b = encodings_b[0]

# 计算欧氏距离（face_recognition 提供）
distances = face_recognition.face_distance([encoding_a], encoding_b)
euclidean_distance = float(distances[0])

# 判断是否匹配
match = euclidean_distance <= threshold
best_match_index = 0

# 输出 JSON
result = {
  "match": bool(match),
  "distance": euclidean_distance,
  "threshold": float(threshold),
  "best_match_index": int(best_match_index)
}
print(json.dumps(result, ensure_ascii=False, indent=2))






#!/usr/bin/env python3
# face_compare_cosine.py
# 使用 face_recognition 提取编码，然后用 Cosine 相似度比较
# 注：直接指定图片路径，输出 JSON

import os
import json
import numpy as np
import face_recognition
# 配置：修改为你的图片路径与阈值
image_a_path = "a.jpg"
image_b_path = "b.jpg"
threshold = 0.5  # cosine 相似度阈值，越大越严格（接近 1 表示相似）
# 检查文件存在性
if not os.path.exists(image_a_path):
    raise FileNotFoundError("File not found: " + image_a_path)
if not os.path.exists(image_b_path):
    raise FileNotFoundError("File not found: " + image_b_path)
# 加载并计算编码
image_a = face_recognition.load_image_file(image_a_path)
encodings_a = face_recognition.face_encodings(image_a)
if len(encodings_a) == 0:
    raise RuntimeError("No face encoding found in image: " + image_a_path)
encoding_a = encodings_a[0]

image_b = face_recognition.load_image_file(image_b_path)
encodings_b = face_recognition.face_encodings(image_b)
if len(encodings_b) == 0:
    raise RuntimeError("No face encoding found in image: " + image_b_path)
encoding_b = encodings_b[0]
# 转为 numpy 并计算 dot 与 norms
vec_a = np.asarray(encoding_a, dtype=float)
vec_b = np.asarray(encoding_b, dtype=float)
dot_product = float(np.dot(vec_a, vec_b))
norm_a = float(np.linalg.norm(vec_a))
norm_b = float(np.linalg.norm(vec_b))
norm_product = norm_a * norm_b
# 保护除零
if norm_product == 0.0:
    cosine_similarity = 0.0
else:
    cosine_similarity = dot_product / norm_product
# 判断是否匹配，并生成“距离类”指标（1 - cosine）
match = cosine_similarity >= threshold
distance_like = 1.0 - cosine_similarity
# 输出 JSON
result = {
  "match": bool(match),
  "cosine_similarity": float(cosine_similarity),
  "distance_like": float(distance_like),
  "threshold": float(threshold)
}
print(json.dumps(result, ensure_ascii=False, indent=2))









#!/usr/bin/env python3
# face_compare_l2_normalized.py
# 使用 face_recognition 提取编码，计算 raw L2 距离并按经验最大值归一化
# 注：直接指定图片路径，输出 JSON
import os
import json
import numpy as np
import face_recognition
# 配置：修改为你的图片路径与阈值
image_a_path = "a.jpg"
image_b_path = "b.jpg"
threshold = 0.5      # 归一化距离阈值（越小越相似）
empirical_max = 1.2  # 用于将 raw L2 归一化到 [0,1] 的经验最大距离
# 检查文件存在性
if not os.path.exists(image_a_path):
    raise FileNotFoundError("File not found: " + image_a_path)
if not os.path.exists(image_b_path):
    raise FileNotFoundError("File not found: " + image_b_path)
# 加载并计算编码
image_a = face_recognition.load_image_file(image_a_path)
encodings_a = face_recognition.face_encodings(image_a)
if len(encodings_a) == 0:
    raise RuntimeError("No face encoding found in image: " + image_a_path)
encoding_a = encodings_a[0]
image_b = face_recognition.load_image_file(image_b_path)
encodings_b = face_recognition.face_encodings(image_b)
if len(encodings_b) == 0:
    raise RuntimeError("No face encoding found in image: " + image_b_path)
encoding_b = encodings_b[0]
# 计算 raw L2
vec_a = np.asarray(encoding_a, dtype=float)
vec_b = np.asarray(encoding_b, dtype=float)
raw_l2 = float(np.linalg.norm(vec_a - vec_b))
# 归一化（保护 empirical_max 非正值）
if empirical_max <= 0.0:
    normalized = float(raw_l2)
else:
    normalized = float(min(raw_l2 / empirical_max, 1.0))
# 判断是否匹配
match = normalized <= threshold
# 输出 JSON
result = {
  "match": bool(match),
  "raw_l2": float(raw_l2),
  "normalized_distance": float(normalized),
  "threshold": float(threshold),
  "empirical_max_used": float(empirical_max)
}
print(json.dumps(result, ensure_ascii=False, indent=2))



