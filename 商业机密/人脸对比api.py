import face_recognition
import sys
if len(sys.argv) != 3:
    print("用法: python compare_faces.py known.jpg unknown.jpg")
    sys.exit(1)
known_path, unknown_path = sys.argv[1], sys.argv[2]
known_image = face_recognition.load_image_file(known_path)
unknown_image = face_recognition.load_image_file(unknown_path)
known_encs = face_recognition.face_encodings(known_image)
unknown_encs = face_recognition.face_encodings(unknown_image)
if not known_encs:
    print("找不到已知图片中的人脸")
    sys.exit(1)
if not unknown_encs:
    print("找不到待测图片中的人脸")
    sys.exit(1)
# 只取每张图的第一张脸编码
known_enc = known_encs[0]
unknown_enc = unknown_encs[0]
# 比较，tolerance 越小越严格（默认 0.6）
result = face_recognition.compare_faces([known_enc], unknown_enc, tolerance=0.6)[0]
print(result)  # True 表示匹配，False 表示不匹配
