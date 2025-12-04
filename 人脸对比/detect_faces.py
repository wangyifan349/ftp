# -------------------------------------------------
# 运行示例： python detect_faces.py [图片路径] [可选: 保存路径]
# -------------------------------------------------
import face_recognition
import cv2
import sys
import os
# ---------- 1️⃣ 参数处理 ----------
if len(sys.argv) < 2:
    sys.exit("用法: python detect_faces.py <image_path> [output_path]")
img_path = sys.argv[1]
output_path = sys.argv[2] if len(sys.argv) > 2 else None
if not os.path.isfile(img_path):
    sys.exit(f"错误: 找不到文件 {img_path}")
# ---------- 2️⃣ 读取图片 ----------
# face_recognition 读取为 RGB numpy 数组
image = face_recognition.load_image_file(img_path)
# ---------- 3️⃣ 人脸检测 ----------
# 返回 (top, right, bottom, left) 的坐标列表
face_locations = face_recognition.face_locations(image)
if not face_locations:
    sys.exit("未检测到任何人脸")
# ---------- 4️⃣ 为了在大图上绘制，先把图片转为 BGR（OpenCV 使用的格式） ----------
bgr_image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
# ---------- 5️⃣ 绘制矩形 & 标注序号 ----------
for idx, (top, right, bottom, left) in enumerate(face_locations, start=1):
    # 画绿色矩形
    cv2.rectangle(bgr_image, (left, top), (right, bottom), (0, 255, 0), 2)
    # 在左上角写上人脸编号，便于后续定位
    label = f"Face {idx}"
    cv2.putText(
        bgr_image,
        label,
        (left, top - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
# ---------- 6️⃣ 显示或保存 ----------
cv2.imshow("Detected faces", bgr_image)
cv2.waitKey(0)          # 按任意键关闭窗口
cv2.destroyAllWindows()
if output_path:
    # 确保目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, bgr_image)
    print(f"标注后的图片已保存至: {output_path}")
