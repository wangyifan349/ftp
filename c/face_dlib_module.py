# face_dlib_module.py
"""
无命令行版 dlib 人脸处理模块

提供函数：
- init_models(predictor_path, recg_model_path)
- get_face_data(image_path) -> list[(rect, shape, face_chip_rgb, descriptor)]
- compare_descriptors(desc1, desc2, method='euclidean') -> dict
- annotate_image(image_path, face_datas) -> BGR numpy image
- save_annotations(image_path, out_path) -> 保存标注图像

示例见文件末尾（if __name__ == '__main__' 块）展示如何在程序中直接调用。
"""

import os
import cv2
import dlib
import numpy as np

# 全局模型句柄（在 init_models 调用后设置）
_detector = None
_shape_predictor = None
_face_rec_model = None

def init_models(predictor_path='shape_predictor_68_face_landmarks.dat',
                recg_model_path='dlib_face_recognition_resnet_model_v1.dat'):
    """初始化并加载 dlib 模型（必须先调用），返回 True/False"""
    global _detector, _shape_predictor, _face_rec_model
    if not os.path.exists(predictor_path):
        raise FileNotFoundError(f"缺少关键点模型: {predictor_path}")
    if not os.path.exists(recg_model_path):
        raise FileNotFoundError(f"缺少人脸识别模型: {recg_model_path}")
    _detector = dlib.get_frontal_face_detector()
    _shape_predictor = dlib.shape_predictor(predictor_path)
    _face_rec_model = dlib.face_recognition_model_v1(recg_model_path)
    return True

def _ensure_models():
    if _detector is None or _shape_predictor is None or _face_rec_model is None:
        raise RuntimeError("模型未初始化。请先调用 init_models(...)")

def load_image_bgr_rgb(path):
    img_bgr = cv2.imread(path)
    if img_bgr is None:
        raise FileNotFoundError(f"无法加载图片: {path}")
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    return img_bgr, img_rgb

def get_face_data(image_path):
    """
    对图片进行检测/关键点/对齐/特征提取。
    返回列表，每项为 dict:
      {
        'rect': dlib.rectangle,
        'shape': dlib.full_object_detection,
        'face_chip_rgb': np.uint8 HxWx3 (RGB),
        'descriptor': np.float32 (128,)
      }
    """
    _ensure_models()
    img_bgr, img_rgb = load_image_bgr_rgb(image_path)
    dets = _detector(img_rgb, 1)
    results = []
    for det in dets:
        shape = _shape_predictor(img_rgb, det)
        chip = dlib.get_face_chip(img_rgb, shape, size=150)  # RGB
        desc = np.array(_face_rec_model.compute_face_descriptor(chip), dtype=np.float32)
        results.append({
            'rect': det,
            'shape': shape,
            'face_chip_rgb': chip,
            'descriptor': desc,
        })
    return results

def euclidean_distance(a, b):
    return float(np.linalg.norm(a - b))

def cosine_similarity(a, b):
    a_n = a / np.linalg.norm(a)
    b_n = b / np.linalg.norm(b)
    return float(np.dot(a_n, b_n))

def compare_descriptors(desc1, desc2, method='euclidean'):
    """
    比对两个 descriptor，method: 'euclidean' 或 'cosine'
    返回 dict:
      { 'method':..., 'value':..., 'match':bool }
    对于欧氏距离，默认阈值 0.6；对于余弦，默认阈值 0.5
    """
    if method not in ('euclidean', 'cosine'):
        raise ValueError("method must be 'euclidean' or 'cosine'")
    if method == 'euclidean':
        val = euclidean_distance(desc1, desc2)
        match = val < 0.6
    else:
        val = cosine_similarity(desc1, desc2)
        match = val > 0.5
    return {'method': method, 'value': val, 'match': match}

def annotate_image_bgr(image_bgr, face_datas, label_prefix=''):
    """
    在 BGR 图像上绘制检测框、关键点与编号，返回带标注的 BGR 图像副本。
    face_datas 为 get_face_data 返回的列表（或相同结构）。
    """
    out = image_bgr.copy()
    for i, fd in enumerate(face_datas):
        rect = fd['rect']
        shape = fd['shape']
        x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()
        cv2.rectangle(out, (x1, y1), (x2, y2), (0,255,0), 2)
        for p in range(68):
            px = shape.part(p).x
            py = shape.part(p).y
            cv2.circle(out, (px, py), 1, (0,0,255), -1)
        cv2.putText(out, f"{label_prefix}{i}", (x1, max(y1-10,0)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,0,0), 1)
    return out

def save_annotations(input_image_path, out_path, label_prefix=''):
    """加载 image，检测并保存带标注的图像"""
    img_bgr, img_rgb = load_image_bgr_rgb(input_image_path)
    faces = get_face_data(input_image_path)
    vis = annotate_image_bgr(img_bgr, faces, label_prefix=label_prefix)
    cv2.imwrite(out_path, vis)
    return len(faces)

# ---------------- 示例调用（在脚本直接运行或在 REPL 中调用） ----------------
if __name__ == '__main__':
    # 请先将模型文件放在脚本同目录或修改路径
    init_models('shape_predictor_68_face_landmarks.dat', 'dlib_face_recognition_resnet_model_v1.dat')

    # 单张图片示例
    img_path = 'a.jpg'
    faces = get_face_data(img_path)
    print(f"在 {img_path} 检测到 {len(faces)} 张人脸")
    if faces:
        # 将第一张人脸特征保存到变量或文件中
        desc_a = faces[0]['descriptor']
        # 保存带注释的图像
        vis = annotate_image_bgr(cv2.imread(img_path), faces, label_prefix='A')
        cv2.imwrite('a_annot.jpg', vis)

    # 两张图片比对示例
    img2 = 'b.jpg'
    faces_b = get_face_data(img2)
    if faces and faces_b:
        desc_b = faces_b[0]['descriptor']
        res = compare_descriptors(desc_a, desc_b, method='euclidean')
        print('比对结果:', res)
        # 保存并拼接可视化（如果大小相同）
        vis_b = annotate_image_bgr(cv2.imread(img2), faces_b, label_prefix='B')
        if vis.shape == vis_b.shape:
            cv2.imwrite('compare_concat.jpg', cv2.hconcat([vis, vis_b]))
        else:
            cv2.imwrite('a_annot.jpg', vis)
            cv2.imwrite('b_annot.jpg', vis_b)
