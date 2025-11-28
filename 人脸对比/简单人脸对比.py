# min_face_compare_no_funcs.py
import numpy as np
import face_recognition

# 本地图片路径，替换为你的图片文件
IMG1 = "person1.jpg"
IMG2 = "person2.jpg"

img1 = face_recognition.load_image_file(IMG1)
encs1 = face_recognition.face_encodings(img1)
if not encs1:
    raise ValueError(f"No face found in {IMG1}")
emb1 = encs1[0]  # 128-d

img2 = face_recognition.load_image_file(IMG2)
encs2 = face_recognition.face_encodings(img2)
if not encs2:
    raise ValueError(f"No face found in {IMG2}")
emb2 = encs2[0]  # 128-d

sim = float(np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2)))
threshold = 0.6  # 根据需求调整
print(f"Cosine similarity: {sim:.4f}")
print("Same person:", sim >= threshold)
