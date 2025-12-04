# pip install face_recognition opencv-python numpy
import face_recognition
import numpy as np
from numpy.linalg import norm
import sys
img_a = "face1.jpg"
img_b = "face2.jpg"
# 加载并提取特征向量
enc_a = face_recognition.face_encodings(face_recognition.load_image_file(img_a))
enc_b = face_recognition.face_encodings(face_recognition.load_image_file(img_b))
if not enc_a or not enc_b:
    sys.exit("任意一张图片未检测到人脸")
vec_a = enc_a[0]
vec_b = enc_b[0]
# 余弦相似度
cos_sim = np.dot(vec_a, vec_b) / (norm(vec_a) * norm(vec_b))
# 欧氏距离（距离越小越相似）
euclid = np.linalg.norm(vec_a - vec_b)
print(f"余弦相似度: {cos_sim:.4f}")
print(f"欧氏距离: {euclid:.4f}")
if cos_sim > 0.8:
    print("余弦阈值判断：同一人")
else:
    print("余弦阈值判断：不同人")
