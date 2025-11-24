#!/usr/bin/env python3
import json
import numpy as np
import cv2
import dlib
image_a_path = "a.jpg"
image_b_path = "b.jpg"
shape_predictor_path = "shape_predictor_5_face_landmarks.dat"
face_rec_model_path = "dlib_face_recognition_resnet_model_v1.dat"
threshold = 0.6
detector = dlib.get_frontal_face_detector()
shape_predictor = dlib.shape_predictor(shape_predictor_path)
face_rec_model = dlib.face_recognition_model_v1(face_rec_model_path)
def get_dlib_descriptor(image_path):
    img_bgr = cv2.imread(image_path)
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    dets = detector(img_rgb, 1)
    rect = dets[0]
    shape = shape_predictor(img_rgb, rect)
    descriptor = face_rec_model.compute_face_descriptor(img_rgb, shape)
    desc_np = np.asarray(descriptor, dtype=float)
    return desc_np
desc_a = get_dlib_descriptor(image_a_path)
desc_b = get_dlib_descriptor(image_b_path)
raw_l2 = float(np.linalg.norm(desc_a - desc_b))
match = raw_l2 <= threshold
result = {
  "match": bool(match),
  "distance": float(raw_l2),
  "threshold": float(threshold)
}
print(json.dumps(result, ensure_ascii=False, indent=2))  # 输出 JSON 结果
