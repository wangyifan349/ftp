#!/usr/bin/env python3
# single_app.py
# 单文件 Flask QA 服务（embedding + FAISS 检索 + seq2seq 生成）
# 前端为单页 Bootstrap，后端含 API /api/qa
# 运行: python single_app.py
# 配置可通过环境变量调整（见 DEFAULTS 字典）
import os
import json
import threading
import logging
from typing import List
from flask import Flask, request, jsonify, render_template_string, send_from_directory
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline
# ---------- 配置 ----------
DEFAULTS = {
    "EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
    "GEN_MODEL": "t5-small",
    "TOP_K": "4",
    "DEVICE": "cpu",
    "INDEX_PATH": "faiss_index.bin",
    "DOCS_PATH": "documents.jsonl",
    "MAX_GEN_LENGTH": "200",
    "PORT": "8000",
}
CONFIG = {k: os.getenv(k, v) for k, v in DEFAULTS.items()}
CONFIG["TOP_K"] = int(CONFIG["TOP_K"])
CONFIG["MAX_GEN_LENGTH"] = int(CONFIG["MAX_GEN_LENGTH"])
CONFIG["PORT"] = int(CONFIG["PORT"])
# ---------- 日志 ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("single_app")
# ---------- Flask app ----------
app = Flask(__name__, static_folder=None)
# ---------- 全局资源（单例） ----------
_embed_model = None
_gen_pipeline = None
_faiss_index = None
_id_list = []
_docs = []
_index_lock = threading.Lock()
# ---------- 辅助函数 ----------
def safe_load_documents(path: str) -> List[dict]:
    docs = []
    if not os.path.exists(path):
        sample = [
            {"id":"doc1_p1","text":"Flask 是一个轻量级的 Python Web 框架，常用于构建 API。","meta":{"source":"sample"}},
            {"id":"doc1_p2","text":"Flask 使用 Werkzeug 作为底层 WSGI 工具，Jinja2 作为模板引擎。","meta":{"source":"sample"}},
            {"id":"doc2_p1","text":"sentence-transformers 提供便捷的句子嵌入接口，适合语义检索。","meta":{"source":"sample"}},
            {"id":"doc2_p2","text":"FAISS 是高效的向量检索库，适用于大规模相似度搜索。","meta":{"source":"sample"}},
        ]
        with open(path, "w", encoding="utf-8") as f:
            for d in sample:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        docs = sample
    else:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    docs.append(json.loads(line))
                except Exception:
                    logger.warning("跳过 documents 文件中的格式错误行 #%d", i+1)
    return docs
def init_embedding_model():
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    try:
        logger.info("加载嵌入模型：%s", CONFIG["EMBEDDING_MODEL"])
        _embed_model = SentenceTransformer(CONFIG["EMBEDDING_MODEL"], device=CONFIG["DEVICE"])
        return _embed_model
    except Exception as e:
        logger.exception("嵌入模型加载失败")
        raise
def init_generation_pipeline():
    global _gen_pipeline
    if _gen_pipeline is not None:
        return _gen_pipeline
    try:
        logger.info("加载生成模型：%s", CONFIG["GEN_MODEL"])
        tokenizer = AutoTokenizer.from_pretrained(CONFIG["GEN_MODEL"], use_fast=True)
        model = AutoModelForSeq2SeqLM.from_pretrained(CONFIG["GEN_MODEL"])
        if CONFIG["DEVICE"] == "cuda":
            model = model.to("cuda")
            device_id = 0
        else:
            device_id = -1
        _gen_pipeline = pipeline("text2text-generation", model=model, tokenizer=tokenizer, device=device_id)
        return _gen_pipeline
    except Exception as e:
        logger.exception("生成模型加载失败")
        raise
def build_faiss_index(docs: List[dict], index_path: str):
    global _faiss_index, _id_list
    embedder = init_embedding_model()
    texts = [d["text"] for d in docs]
    ids = [d["id"] for d in docs]
    logger.info("计算 %d 条文档的嵌入向量", len(texts))
    embeddings = embedder.encode(texts, convert_to_numpy=True, show_progress_bar=True)
    # 归一化以便用内积（cosine）
    faiss.normalize_L2(embeddings)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    try:
        faiss.write_index(index, index_path)
        with open(index_path + ".ids", "w", encoding="utf-8") as f:
            for _id in ids:
                f.write(_id + "\n")
        logger.info("FAISS 索引写入：%s", index_path)
    except Exception:
        logger.warning("写入索引文件失败（可能无权限），但内存中索引可用")
    _faiss_index = index
    _id_list = ids
    return index
def load_or_build_index():
    global _faiss_index, _id_list, _docs
    with _index_lock:
        if _faiss_index is not None:
            return _faiss_index
        logger.info("加载文档：%s", CONFIG["DOCS_PATH"])
        _docs = safe_load_documents(CONFIG["DOCS_PATH"])
        # 尝试读取已存在的索引
        try:
            if os.path.exists(CONFIG["INDEX_PATH"]):
                logger.info("尝试加载 FAISS 索引：%s", CONFIG["INDEX_PATH"])
                idx = faiss.read_index(CONFIG["INDEX_PATH"])
                # 读 ids
                ids_path = CONFIG["INDEX_PATH"] + ".ids"
                if os.path.exists(ids_path):
                    with open(ids_path, "r", encoding="utf-8") as f:
                        _id_list = [line.strip() for line in f if line.strip()]
                else:
                    # 如果没有 ids 文件，重建索引以保证对齐
                    logger.warning("未找到 ids 文件，重建索引以保证 id 对齐")
                    idx = build_faiss_index(_docs, CONFIG["INDEX_PATH"])
                _faiss_index = idx
                logger.info("FAISS 索引加载成功")
                return _faiss_index
        except Exception:
            logger.exception("加载现有 FAISS 索引失败，将重建")
        # 若加载失败或无索引则构建
        return build_faiss_index(_docs, CONFIG["INDEX_PATH"])
def retrieve_top_k(query: str, k: int = None):
    global _faiss_index, _id_list, _docs
    if k is None:
        k = CONFIG["TOP_K"]
    idx = load_or_build_index()
    embedder = init_embedding_model()
    q_emb = embedder.encode([query], convert_to_numpy=True)
    faiss.normalize_L2(q_emb)
    k = min(k, idx.ntotal) if idx.ntotal > 0 else 0
    if k == 0:
        return []
    D, I = idx.search(q_emb, k)
    results = []
    for score, i in zip(D[0], I[0]):
        if i < 0 or i >= len(_id_list):
            continue
        doc_id = _id_list[i]
        # 找到对应文档
        doc = next((d for d in _docs if d.get("id") == doc_id), None)
        if doc:
            results.append({"id": doc_id, "score": float(score), "text": doc.get("text"), "meta": doc.get("meta")})
    return results
def build_prompt(question: str, contexts: List[dict]):
    if not contexts:
        return f"Question: {question}\nAnswer:"
    ctx_text = "\n\n".join([f"Context {i+1}: {c['text']}" for i, c in enumerate(contexts)])
    prompt = (
        "请根据下面的上下文回答问题。如果上下文中没有相关信息，请回答：无法从提供的内容中得出结论。\n\n"
        f"{ctx_text}\n\nQuestion: {question}\nAnswer:"
    )
    return prompt
# ---------- API 路由 ----------
@app.route("/api/qa", methods=["POST"])
def api_qa():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "请求体必须为 JSON"}), 400
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "字段 'question' 不能为空"}), 400
    top_k = int(data.get("top_k", CONFIG["TOP_K"]))
    max_len = int(data.get("max_length", CONFIG["MAX_GEN_LENGTH"]))
    try:
        contexts = retrieve_top_k(question, k=top_k)
    except Exception:
        logger.exception("检索阶段出错")
        return jsonify({"error": "检索失败"}), 500
    prompt = build_prompt(question, contexts)
    try:
        gen = init_generation_pipeline()
        outputs = gen(prompt, max_length=max_len, num_return_sequences=1)
        answer = outputs[0]["generated_text"].strip() if outputs else ""
    except Exception:
        logger.exception("生成阶段出错")
        answer = "模型生成失败"
    return jsonify({
        "answer": answer,
        "contexts": contexts,
        "meta": {"embed_model": CONFIG["EMBEDDING_MODEL"], "gen_model": CONFIG["GEN_MODEL"]}
    })
# ---------- 简单前端（Bootstrap 单页） ----------
INDEX_HTML = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>QA 服务 - 单文件示例</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { padding-top: 40px; background:#f8f9fa; }
      .card { margin-bottom: 1rem; }
      pre { white-space: pre-wrap; word-break: break-word; }
    </style>
  </head>
  <body>
    <div class="container">
      <h1 class="mb-3">问答服务（单文件示例）</h1>
      <div class="card">
        <div class="card-body">
          <form id="qaForm">
            <div class="mb-3">
              <label for="question" class="form-label">问题</label>
              <input type="text" class="form-control" id="question" placeholder="输入你的问题..." required>
            </div>
            <div class="row g-2 mb-3">
              <div class="col-auto">
                <label class="form-label">Top K</label>
                <input type="number" class="form-control" id="top_k" value="{{top_k}}" min="1" max="20">
              </div>
              <div class="col-auto">
                <label class="form-label">Max Length</label>
                <input type="number" class="form-control" id="max_length" value="{{max_len}}" min="20" max="1024">
              </div>
              <div class="col-auto align-self-end">
                <button type="submit" class="btn btn-primary">提交</button>
              </div>
            </div>
          </form>

          <div id="resultArea" style="display:none;">
            <div class="card">
              <div class="card-header">回答</div>
              <div class="card-body">
                <pre id="answerText"></pre>
              </div>
            </div>

            <div class="card">
              <div class="card-header">检索到的上下文（来源）</div>
              <div class="card-body" id="contextsArea"></div>
            </div>
          </div>

          <div id="statusArea" class="mt-2"></div>

        </div>
      </div>

      <footer class="text-muted small">Embed: {{embed_model}} • Gen: {{gen_model}}</footer>
    </div>

    <script>
      const form = document.getElementById('qaForm');
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const q = document.getElementById('question').value.trim();
        const topk = parseInt(document.getElementById('top_k').value || {{top_k}});
        const maxlen = parseInt(document.getElementById('max_length').value || {{max_len}});
        if (!q) return;
        document.getElementById('statusArea').innerText = '请求中...';
        document.getElementById('resultArea').style.display = 'none';
        try {
          const resp = await fetch('/api/qa', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({question: q, top_k: topk, max_length: maxlen})
          });
          const data = await resp.json();
          if (!resp.ok) {
            document.getElementById('statusArea').innerText = '错误: ' + (data.error || JSON.stringify(data));
            return;
          }
          document.getElementById('answerText').innerText = data.answer || '';
          const ctxArea = document.getElementById('contextsArea');
          ctxArea.innerHTML = '';
          (data.contexts || []).forEach((c, i) => {
            const el = document.createElement('div');
            el.className = 'mb-2';
            el.innerHTML = '<strong>Context ' + (i+1) + ' (score:' + (c.score||0).toFixed(3) + ')</strong><div><pre>' + (c.text||'') + '</pre></div>';
            ctxArea.appendChild(el);
          });
          document.getElementById('resultArea').style.display = '';
          document.getElementById('statusArea').innerText = '完成';
        } catch (err) {
          document.getElementById('statusArea').innerText = '请求失败';
          console.error(err);
        }
      });
    </script>

  </body>
</html>
"""
@app.route("/", methods=["GET"])
def index():
    # 在渲染前把配置写入模板占位
    rendered = render_template_string(INDEX_HTML,
                                      top_k=CONFIG["TOP_K"],
                                      max_len=CONFIG["MAX_GEN_LENGTH"],
                                      embed_model=CONFIG["EMBEDDING_MODEL"],
                                      gen_model=CONFIG["GEN_MODEL"])
    return rendered
# ---------- 启动前预热（可选） ----------
def warm_up():
    try:
        logger.info("预热：初始化模型与索引（仅首次）")
        init_embedding_model()
        init_generation_pipeline()
        load_or_build_index()
        logger.info("预热完成")
    except Exception:
        logger.exception("预热过程中发生错误")
if __name__ == "__main__":
    # 在主线程中预热，避免首个请求大幅延迟
    warm_up()
    port = CONFIG["PORT"]
    logger.info("启动 Flask 应用，端口 %d", port)
    app.run(host="0.0.0.0", port=port)
