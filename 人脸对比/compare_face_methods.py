#!/usr/bin/env python3
# compare_face_methods.py
# 三种人脸比对实现（face_recognition 欧氏距离、cosine 相似度、L2 归一化）

import os
import json
import numpy as np
import face_recognition

# ----- 配置：在此处修改图片路径与阈值 -----
image_a_path = "a.jpg"
image_b_path = "b.jpg"
threshold_euclidean = 0.6        # face_recognition 欧氏距离阈值（越小越严格）
threshold_cosine = 0.5           # cosine 相似度阈值（越大越相似）
threshold_normalized_l2 = 0.5    # 归一化 L2 阈值（越小越相似）
empirical_max = 1.2              # 用于将 L2 归一化到 [0,1] 的经验最大值
# -----------------------------------------
# 检查文件是否存在
if not os.path.exists(image_a_path):
    raise FileNotFoundError("File not found: " + image_a_path)
if not os.path.exists(image_b_path):
    raise FileNotFoundError("File not found: " + image_b_path)

# 加载图片并计算人脸编码（逐步写，不用列表表达式）
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

# 确保为 numpy 数组
encoding_a = np.asarray(encoding_a, dtype=float)
encoding_b = np.asarray(encoding_b, dtype=float)

# 1) face_recognition 欧氏距离（与原始行为一致）
dist_array = face_recognition.face_distance([encoding_a], encoding_b)
# face_distance 返回数组，取第一个元素
euclidean_distance = float(dist_array[0])
euclidean_match = euclidean_distance <= threshold_euclidean
euclidean_result = {}
euclidean_result["match"] = bool(euclidean_match)
euclidean_result["distance"] = euclidean_distance
euclidean_result["threshold"] = float(threshold_euclidean)
euclidean_result["best_match_index"] = 0

# 2) cosine 相似度（手动计算）
dot_product = float(np.dot(encoding_a, encoding_b))
norm_a = float(np.linalg.norm(encoding_a))
norm_b = float(np.linalg.norm(encoding_b))
norm_product = norm_a * norm_b
if norm_product == 0.0:
    cosine_similarity = 0.0
else:
    cosine_similarity = dot_product / norm_product
cosine_match = cosine_similarity >= threshold_cosine
distance_like = 1.0 - cosine_similarity
cosine_result = {}
cosine_result["match"] = bool(cosine_match)
cosine_result["cosine_similarity"] = float(cosine_similarity)
cosine_result["distance_like"] = float(distance_like)
cosine_result["threshold"] = float(threshold_cosine)

# 3) 原始 L2 与归一化 L2
raw_l2 = float(np.linalg.norm(encoding_a - encoding_b))
if empirical_max <= 0:
    normalized_l2 = float(raw_l2)  # 如果配置错误，退回未归一化值
else:
    normalized_l2 = float(min(raw_l2 / empirical_max, 1.0))
normalized_l2_match = normalized_l2 <= threshold_normalized_l2
l2_result = {}
l2_result["match"] = bool(normalized_l2_match)
l2_result["raw_l2"] = raw_l2
l2_result["normalized_distance"] = normalized_l2
l2_result["threshold"] = float(threshold_normalized_l2)
l2_result["empirical_max_used"] = float(empirical_max)

# 汇总（简单多数投票）
vote_count = 0
if euclidean_result["match"]:
    vote_count = vote_count + 1
if cosine_result["match"]:
    vote_count = vote_count + 1
if l2_result["match"]:
    vote_count = vote_count + 1
majority_match = vote_count >= 2
summary = {}
summary["majority_match"] = bool(majority_match)
summary["votes_for_match"] = int(vote_count)
summary["votes_total"] = 3

# 组织最终输出（平铺，不嵌套复杂结构，只跟你要求的字段一致）
output = {}
output["euclidean"] = euclidean_result
output["cosine"] = cosine_result
output["l2_normalized"] = l2_result
output["summary"] = summary

# 打印 JSON 到 stdout
print(json.dumps(output, ensure_ascii=False, indent=2))
