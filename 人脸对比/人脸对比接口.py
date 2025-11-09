"""
This Flask app pre-indexes all images in a local IMAGE_STORE folder at startup by extracting 128-D face embeddings (stored in a SQLite DB) and exposes endpoints to compare two uploaded images, compare uploads with indexed images by id, index new images (saved into IMAGE_STORE), search the DB for top-K nearest faces asynchronously, trigger or check background reindexing, list indexed entries, and serve stored images; dependencies: Flask, face_recognition, Pillow, numpy.
"""

# app.py
import os
import io
import json
import sqlite3
import threading
import uuid
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import List, Tuple
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from PIL import Image
import numpy as np
import face_recognition
DB_PATH = "face_db.sqlite"
IMAGE_STORE = "db_files"
ALLOWED_EXT = {"png", "jpg", "jpeg"}
EMBEDDING_DIM = 128
os.makedirs(IMAGE_STORE, exist_ok=True)
app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=4)
tasks = {}
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS faces (
        id TEXT PRIMARY KEY,
        filename TEXT,
        img_path TEXT,
        embedding TEXT,
        mtime REAL
    )
    """)
    conn.commit()
    conn.close()
def upsert_face(record_id: str, filename: str, img_path: str, embedding: List[float], mtime: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    INSERT INTO faces (id, filename, img_path, embedding, mtime)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
      filename=excluded.filename,
      img_path=excluded.img_path,
      embedding=excluded.embedding,
      mtime=excluded.mtime
    """, (record_id, filename, img_path, json.dumps(embedding), mtime))
    conn.commit()
    conn.close()
def get_face_by_id(record_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, filename, img_path, embedding, mtime FROM faces WHERE id=?", (record_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return (row[0], row[1], row[2], json.loads(row[3]), row[4])
def load_all_rows():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, filename, img_path, embedding, mtime FROM faces")
    rows = c.fetchall()
    conn.close()
    results = []
    for r in rows:
        try:
            results.append((r[0], r[1], r[2], json.loads(r[3]), r[4]))
        except Exception:
            continue
    return results
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT
def pil_to_rgb_array(file_stream) -> np.ndarray:
    image = Image.open(file_stream).convert("RGB")
    return np.array(image)
def extract_embedding_from_array(arr: np.ndarray) -> np.ndarray:
    locations = face_recognition.face_locations(arr)
    if not locations:
        raise ValueError("No face detected")
    encodings = face_recognition.face_encodings(arr, known_face_locations=locations)
    if not encodings:
        raise ValueError("Failed to extract embedding")
    return np.asarray(encodings[0], dtype=np.float64)

def compute_metrics(emb1: np.ndarray, emb2: np.ndarray):
    l2 = float(np.linalg.norm(emb1 - emb2))
    norm1 = np.linalg.norm(emb1)
    norm2 = np.linalg.norm(emb2)
    if norm1 == 0 or norm2 == 0:
        raise ValueError("Zero-vector embedding")
    cosine_similarity = float(np.dot(emb1, emb2) / (norm1 * norm2))
    cosine_distance = 1.0 - cosine_similarity
    return {"l2": l2, "cosine_similarity": cosine_similarity, "cosine_distance": cosine_distance}

def index_image_file(path: str, filename: str = None):
    if not filename:
        filename = os.path.basename(path)
    mtime = os.path.getmtime(path)
    with open(path, "rb") as f:
        arr = pil_to_rgb_array(f)
    emb = extract_embedding_from_array(arr)
    record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, path))
    upsert_face(record_id, filename, path, emb.tolist(), mtime)
    return record_id

def initial_index_scan():
    existing = {r[2]: r for r in load_all_rows()}
    for fname in os.listdir(IMAGE_STORE):
        if not allowed_file(fname):
            continue
        full_path = os.path.join(IMAGE_STORE, fname)
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            continue
        row = existing.get(full_path)
        if row is None or (row and row[4] != mtime):
            try:
                index_image_file(full_path, fname)
                app.logger.info(f"Indexed: {full_path}")
            except Exception as e:
                app.logger.warning(f"Failed to index {full_path}: {e}")

INDEX_HTML = """
<!doctype html>
<title>Face Compare & DB (preindex)</title>
<h2>Compare two images (upload)</h2>
<form method=post enctype=multipart/form-data action="/compare">
  <input type=file name=image1 required>
  <input type=file name=image2 required>
  <input type=submit value=Compare>
</form>

<h2>Compare uploaded to indexed (use image_id param)</h2>
<p>先 /index 上传图片再调用 /compare_with_db?image_id=&lt;id&gt;</p>

<h2>Index an image (copy into store and index)</h2>
<form method=post enctype=multipart/form-data action="/index">
  <input type=file name=image required>
  <input type=text name=label placeholder="optional label">
  <input type=submit value=Index>
</form>

<h2>Search (upload and search DB)</h2>
<form method=post enctype=multipart/form-data action="/search">
  <input type=file name=image required>
  Top-K: <input type=number name=topk value=5 min=1>
  <input type=submit value=Search>
</form>

<form method=post action="/reindex">
  <input type=submit value="Trigger full reindex (background)">
</form>
"""
@app.route("/")
def index():
    return render_template_string(INDEX_HTML)
@app.route("/compare", methods=["POST"])
def compare():
    if "image1" not in request.files or "image2" not in request.files:
        return jsonify({"error": "Please upload image1 and image2"}), 400
    f1 = request.files["image1"]
    f2 = request.files["image2"]
    if not (f1 and allowed_file(f1.filename) and f2 and allowed_file(f2.filename)):
        return jsonify({"error": "Unsupported file type"}), 400
    try:
        arr1 = pil_to_rgb_array(f1.stream)
        arr2 = pil_to_rgb_array(f2.stream)
        emb1 = extract_embedding_from_array(arr1)
        emb2 = extract_embedding_from_array(arr2)
        metrics = compute_metrics(emb1, emb2)
        threshold_cosine = float(request.form.get("threshold_cosine", 0.5))
        threshold_l2 = float(request.form.get("threshold_l2", 0.6))
        return jsonify({
            "cosine_similarity": metrics["cosine_similarity"],
            "cosine_distance": metrics["cosine_distance"],
            "l2_distance": metrics["l2"],
            "verdicts": {
                "cosine_match": metrics["cosine_similarity"] >= threshold_cosine,
                "l2_match": metrics["l2"] <= threshold_l2
            },
            "emb_length": len(emb1)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/compare_with_db", methods=["POST", "GET"])
def compare_with_db():
    try:
        id1 = request.values.get("id1")
        id2 = request.values.get("id2")
        if id1 and id2:
            r1 = get_face_by_id(id1)
            r2 = get_face_by_id(id2)
            if not r1 or not r2:
                return jsonify({"error": "id not found"}), 404
            emb1 = np.asarray(r1[3], dtype=np.float64)
            emb2 = np.asarray(r2[3], dtype=np.float64)
            metrics = compute_metrics(emb1, emb2)
            return jsonify({"from_db": True, "metrics": metrics, "id1": id1, "id2": id2})
        image_id = request.values.get("image_id")
        if image_id:
            r = get_face_by_id(image_id)
            if not r:
                return jsonify({"error": "image_id not found"}), 404
            if "image" not in request.files:
                return jsonify({"error": "Please upload an image to compare with DB image_id"}), 400
            f = request.files["image"]
            if not allowed_file(f.filename):
                return jsonify({"error": "Unsupported file type"}), 400
            arr = pil_to_rgb_array(f.stream)
            emb_query = extract_embedding_from_array(arr)
            emb_db = np.asarray(r[3], dtype=np.float64)
            metrics = compute_metrics(emb_query, emb_db)
            return jsonify({"from_db": True, "metrics": metrics, "db_id": image_id})
        return jsonify({"error": "Provide id1/id2 or image_id + uploaded image"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/index", methods=["POST"])
def index_image():
    if "image" not in request.files:
        return jsonify({"error": "Please upload image"}), 400
    f = request.files["image"]
    if not f or not allowed_file(f.filename):
        return jsonify({"error": "Unsupported file type"}), 400
    label = request.form.get("label") or ""
    try:
        ext = f.filename.rsplit(".", 1)[1].lower()
        record_id = str(uuid.uuid4())
        save_name = f"{record_id}.{ext}"
        save_path = os.path.join(IMAGE_STORE, save_name)
        f.stream.seek(0)
        with open(save_path, "wb") as out_f:
            out_f.write(f.stream.read())
        mtime = os.path.getmtime(save_path)
        arr = pil_to_rgb_array(open(save_path, "rb"))
        emb = extract_embedding_from_array(arr)
        filename_field = (label + "|" + save_name) if label else save_name
        upsert_face(record_id, filename_field, save_path, emb.tolist(), mtime)
        return jsonify({"id": record_id, "img_path": save_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
def search_worker(query_emb: np.ndarray, topk: int):
    rows = load_all_rows()
    results = []
    q = np.asarray(query_emb, dtype=np.float64)
    for rid, filename, path, emb, mtime in rows:
        try:
            emb_arr = np.asarray(emb, dtype=np.float64)
            metrics = compute_metrics(q, emb_arr)
            results.append({
                "id": rid,
                "filename": filename,
                "img_path": path,
                "l2": metrics["l2"],
                "cosine_similarity": metrics["cosine_similarity"]
            })
        except Exception:
            continue
    results.sort(key=lambda x: x["cosine_similarity"], reverse=True)
    return results[:topk]
@app.route("/search", methods=["POST"])
def search():
    if "image" not in request.files:
        return jsonify({"error": "Please upload image"}), 400
    try:
        topk = int(request.form.get("topk", 5))
    except Exception:
        topk = 5
    f = request.files["image"]
    if not f or not allowed_file(f.filename):
        return jsonify({"error": "Unsupported file type"}), 400
    try:
        arr = pil_to_rgb_array(f.stream)
        query_emb = extract_embedding_from_array(arr)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    task_id = str(uuid.uuid4())
    future: Future = executor.submit(search_worker, query_emb, topk)
    tasks[task_id] = {"future": future}
    return jsonify({"task_id": task_id})
@app.route("/search_status/<task_id>", methods=["GET"])
def search_status(task_id):
    t = tasks.get(task_id)
    if not t:
        return jsonify({"error": "task_id not found"}), 404
    future: Future = t["future"]
    if future.done():
        try:
            res = future.result()
            del tasks[task_id]
            return jsonify({"status": "done", "results": res})
        except Exception as e:
            del tasks[task_id]
            return jsonify({"status": "error", "error": str(e)}), 500
    else:
        return jsonify({"status": "running"})
@app.route("/reindex", methods=["POST"])
def reindex():
    task_id = str(uuid.uuid4())
    def worker():
        initial_index_scan()
        return {"status": "ok"}
    future = executor.submit(worker)
    tasks[task_id] = {"future": future}
    return jsonify({"reindex_task_id": task_id})
@app.route("/list_indexed", methods=["GET"])
def list_indexed():
    rows = load_all_rows()
    items = [{"id": r[0], "filename": r[1], "img_path": r[2], "mtime": r[4]} for r in rows]
    return jsonify({"count": len(rows), "items": items})
@app.route("/get_image/<path:filename>")
def get_image(filename):
    return send_from_directory(IMAGE_STORE, filename)
init_db()
bg_thread = threading.Thread(target=initial_index_scan, daemon=True)
bg_thread.start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
