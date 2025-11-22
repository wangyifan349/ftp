# app_no_disk_bootstrap_auth.py
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Tuple
from flask import Flask, request, jsonify, render_template_string
import numpy as np
from sentence_transformers import SentenceTransformer
import faiss
from flask_httpauth import HTTPBasicAuth
# ---------- 配置 ----------
QA_STORE: Dict[str, str] = {
    "What is deep learning?": '''Deep learning is a machine learning method using multi-layer neural networks to learn feature representations from data.''',
    "What is machine learning?": '''Machine learning is the field that enables computers to learn from data and make predictions or decisions.''',
    "How to train a neural network?": '''Training usually uses backpropagation and gradient descent; prepare data, choose loss and optimizer.''',
    "What is overfitting?": '''Overfitting is when a model performs well on training data but poorly on unseen data.''',
    "What do activation functions do?": '''Activation functions introduce non-linearity, e.g., ReLU, sigmoid, tanh.'''
}
AVAILABLE_ENCODERS: List[str] = [
    "sentence-transformers/all-mpnet-base-v2",
    "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    "sentence-transformers/all-distilroberta-v1",
    "sentence-transformers/all-mpnet-base-v2"
]
MAX_WORKERS = 4
# 简单用户表（示例）。生产请改为安全哈希存储。
USERS: Dict[str, str] = {
    "alice": "alicepassword",
    "bob": "bobpassword"
}
# ---------- 全局状态 ----------
app = Flask(__name__)
auth = HTTPBasicAuth()
encoder_models: Dict[str, SentenceTransformer] = {}
faiss_indexes: Dict[str, faiss.Index] = {}
index_metadata: Dict[str, List[Dict[str, Any]]] = {}
encoder_dimensions: Dict[str, int] = {}
encoder_locks: Dict[str, threading.Lock] = {}
# ---------- 认证回调（中文注释） ----------
@auth.verify_password
def verify_password(username: str, password: str) -> bool:
    """
    验证用户名和密码。
    简单示例：与内存 USERS 比较明文密码。实际请使用安全哈希。
    """
    if not username or not password:
        return False
    stored = USERS.get(username)
    if stored is None:
        return False
    return password == stored
@auth.get_user_roles
def get_user_roles(username: str) -> List[str]:
    """示例：按用户名返回角色列表（未使用，但留作扩展）"""
    if username == "alice":
        return ["admin"]
    return ["user"]
# ---------- 保持其余工具函数与之前版本一致（中文注释） ----------
def prompt_operator_for_models() -> List[str]:
    print("Available encoder models:")
    i = 0
    while i < len(AVAILABLE_ENCODERS):
        print(f"{i+1}. {AVAILABLE_ENCODERS[i]}")
        i += 1
    print("Enter comma-separated numbers to select models (e.g. 1,2) or press Enter to select the first model:")
    selection = input("Selection: ").strip()
    if selection == "":
        return [AVAILABLE_ENCODERS[0]]
    parts = selection.split(",")
    chosen: List[str] = []
    j = 0
    while j < len(parts):
        part_strip = parts[j].strip()
        if part_strip == "":
            j += 1
            continue
        try:
            idx = int(part_strip) - 1
            if 0 <= idx < len(AVAILABLE_ENCODERS):
                chosen.append(AVAILABLE_ENCODERS[idx])
        except Exception:
            if part_strip in AVAILABLE_ENCODERS:
                chosen.append(part_strip)
        j += 1
    if not chosen:
        return [AVAILABLE_ENCODERS[0]]
    return chosen
def build_in_memory_index_for_model(model_key: str, questions: List[str]) -> Tuple[faiss.Index, List[Dict[str, Any]]]:
    model = encoder_models[model_key]
    dimension = model.get_sentence_embedding_dimension()
    encoder_dimensions[model_key] = dimension
    batch_size = 64
    embeddings_parts: List[np.ndarray] = []
    i = 0
    while i < len(questions):
        batch_questions = questions[i:i + batch_size]
        batch_embeddings = model.encode(batch_questions, convert_to_numpy=True, show_progress_bar=False)
        embeddings_parts.append(batch_embeddings)
        i += batch_size
    embeddings = np.vstack(embeddings_parts).astype("float32")
    faiss.normalize_L2(embeddings)
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)
    metadata_list: List[Dict[str, Any]] = []
    j = 0
    while j < len(questions):
        metadata_list.append({
            "id": j,
            "question": questions[j],
            "answer": QA_STORE[questions[j]]
        })
        j += 1
    return index, metadata_list
def ensure_model_loaded_and_indexed(model_name: str) -> None:
    if model_name in encoder_models and model_name in faiss_indexes:
        return
    encoder_models[model_name] = SentenceTransformer(model_name)
    encoder_locks[model_name] = threading.Lock()
    questions_ordered: List[str] = []
    for key in QA_STORE:
        questions_ordered.append(key)
    index, metadata_list = build_in_memory_index_for_model(model_name, questions_ordered)
    faiss_indexes[model_name] = index
    index_metadata[model_name] = metadata_list
def encode_query_with_model(model_name: str, query_text: str) -> np.ndarray:
    model = encoder_models[model_name]
    emb = model.encode([query_text], convert_to_numpy=True, show_progress_bar=False).astype("float32")
    return emb
def search_index_for_model(model_name: str, query_embedding: np.ndarray, top_k: int) -> List[Dict[str, Any]]:
    index = faiss_indexes[model_name]
    metadata = index_metadata[model_name]
    faiss.normalize_L2(query_embedding)
    distances, indices = index.search(query_embedding, top_k)
    results: List[Dict[str, Any]] = []
    row = 0
    while row < distances.shape[0]:
        col = 0
        while col < distances.shape[1]:
            matched_index = int(indices[row, col])
            score_value = float(distances[row, col])
            if matched_index >= 0:
                meta_item = metadata[matched_index]
                results.append({
                    "model": model_name,
                    "query_index": row,
                    "matched_id": meta_item["id"],
                    "question": meta_item["question"],
                    "answer": meta_item["answer"],
                    "score": score_value
                })
            col += 1
        row += 1
    return results
def merge_and_deduplicate_results(result_list: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    best_by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
    i = 0
    while i < len(result_list):
        item = result_list[i]
        key = (item["question"], item["answer"])
        existing = best_by_pair.get(key)
        if existing is None or item["score"] > existing["score"]:
            best_by_pair[key] = item
        i += 1
    merged_list: List[Dict[str, Any]] = []
    for pair in best_by_pair:
        merged_list.append(best_by_pair[pair])
    merged_list.sort(key=lambda x: x["score"], reverse=True)
    result_top: List[Dict[str, Any]] = merged_list[:top_k]
    return result_top
# ---------- 前端模板（Bootstrap，淡绿色主题） ----------
INDEX_PAGE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Semantic QA Search</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      :root {
        --bg-green: #e8f8f0;
        --card-green: #dff3e8;
        --accent-green: #2e8b57;
      }
      body {
        background-color: var(--bg-green);
      }
      .brand {
        color: var(--accent-green);
        font-weight: 700;
      }
      .card-custom {
        background-color: var(--card-green);
        border: 1px solid rgba(46,139,87,0.15);
      }
      .btn-accent {
        background-color: var(--accent-green);
        color: white;
        border: none;
      }
      .btn-accent:hover {
        background-color: #276b46;
      }
      pre.answer-box {
        white-space: pre-wrap;
        word-wrap: break-word;
        background: rgba(255,255,255,0.6);
        padding: 12px;
        border-radius: 6px;
      }
    </style>
  </head>
  <body>
    <div class="container py-5">
      <div class="row justify-content-center">
        <div class="col-md-8">
          <div class="text-center mb-4">
            <h1 class="brand">Semantic QA Search</h1>
            <p class="text-muted">In-memory semantic search with multiple sentence encoders</p>
          </div>
          <div class="card card-custom mb-4">
            <div class="card-body">
              <form id="searchForm" method="post" action="/api/search">
                <div class="mb-3">
                  <label class="form-label">Query</label>
                  <input name="query" class="form-control" placeholder="Enter your question" required>
                </div>
                <div class="row g-2">
                  <div class="col-md-4">
                    <label class="form-label">Top K</label>
                    <input name="top_k" class="form-control" value="5">
                  </div>
                  <div class="col-md-8">
                    <label class="form-label">Models (optional, comma-separated)</label>
                    <input name="models" class="form-control" placeholder="e.g. sentence-transformers/all-mpnet-base-v2">
                    <div class="form-text">Available: {{available_models}}</div>
                  </div>
                </div>
                <div class="mt-3 text-end">
                  <button type="submit" class="btn btn-accent">Search (JSON)</button>
                </div>
              </form>
            </div>
          </div>

          <div class="card card-custom">
            <div class="card-body">
              <h5 class="card-title">How to use</h5>
              <p class="card-text">Submit a query to get detailed JSON response including per-model hits and merged results.</p>
              <p class="card-text"><small class="text-muted">Model selection is chosen by server operator at startup but you may override with model keys above.</small></p>
            </div>
          </div>

          <footer class="text-center text-muted mt-4">
            <small>UI theme: soft green • Bootstrap</small>
          </footer>
        </div>
      </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""
# ---------- 路由（/api/search 受保护） ----------
@app.route("/", methods=["GET"])
def route_index():
    return render_template_string(INDEX_PAGE, available_models=", ".join(AVAILABLE_ENCODERS))
@app.route("/api/search", methods=["POST"])
@auth.login_required
def route_api_search():
    """
    受保护的搜索接口。需要 HTTP Basic 认证。
    POST JSON:
    {
      "query": "text",
      "top_k": 5,
      "models": ["sentence-transformers/all-mpnet-base-v2"]  # optional
    }
    """
    request_json = None
    if request.is_json:
        request_json = request.get_json()
    else:
        request_json = {
            "query": request.form.get("query", ""),
            "top_k": int(request.form.get("top_k", 5)),
            "models": None
        }
        models_field = request.form.get("models", "")
        if models_field:
            model_names: List[str] = []
            parts = models_field.split(",")
            k = 0
            while k < len(parts):
                part_strip = parts[k].strip()
                if part_strip:
                    model_names.append(part_strip)
                k += 1
            if model_names:
                request_json["models"] = model_names
    query_text = request_json.get("query", "")
    if not query_text:
        return jsonify({"error": "query is required"}), 400
    top_k_value = int(request_json.get("top_k", 5))
    requested_models = request_json.get("models", None)
    if requested_models is None:
        requested_models = list(encoder_models.keys())
    models_to_use: List[str] = []
    i = 0
    while i < len(requested_models):
        name = requested_models[i]
        if name in encoder_models:
            models_to_use.append(name)
        i += 1
    if not models_to_use:
        return jsonify({"error": "no valid models available"}), 400
    all_hits: List[Dict[str, Any]] = []
    def worker(model_name: str) -> List[Dict[str, Any]]:
        emb = encode_query_with_model(model_name, query_text)
        hits = search_index_for_model(model_name, emb, top_k_value)
        return hits
    executor = ThreadPoolExecutor(max_workers=min(len(models_to_use), MAX_WORKERS))
    futures = []
    j = 0
    while j < len(models_to_use):
        future = executor.submit(worker, models_to_use[j])
        futures.append(future)
        j += 1
    k = 0
    while k < len(futures):
        future = futures[k]
        try:
            hits = future.result()
            m = 0
            while m < len(hits):
                all_hits.append(hits[m])
                m += 1
        except Exception:
            pass
        k += 1
    merged_results = merge_and_deduplicate_results(all_hits, top_k_value)
    response_payload: Dict[str, Any] = {
        "query": query_text,
        "requested_top_k": top_k_value,
        "used_models": models_to_use,
        "authenticated_user": auth.current_user(),
        "per_model_hits": all_hits,
        "merged_results": merged_results
    }
    return jsonify(response_payload)
# ---------- 启动 ----------
def main():
    chosen_models = prompt_operator_for_models()
    print("Loading and encoding QA store into memory for chosen models...")
    questions_ordered: List[str] = []
    for q in QA_STORE:
        questions_ordered.append(q)
    i = 0
    while i < len(chosen_models):
        model_name = chosen_models[i]
        try:
            ensure_model_loaded_and_indexed(model_name)
            print(f"Loaded and indexed model: {model_name}")
        except Exception as e:
            print(f"Failed to load model {model_name}: {e}")
        i += 1
    if not encoder_models:
        print("No models loaded. Exiting.")
        sys.exit(1)
    app.run(host="0.0.0.0", port=5000, debug=False)
if __name__ == "__main__":
    main()
