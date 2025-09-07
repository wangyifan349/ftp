# app.py
import json
from functools import wraps
from flask import Flask, request, render_template_string, redirect, url_for, session
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
from sentence_transformers import SentenceTransformer
import numpy as np
import faiss
import os
# ---------- 配置 ----------
# 认证用户（示例）：用户名/密码（密码以 hash 存储）
# 生产请用安全方式管理凭证
USER_DATA = {
    "admin": generate_password_hash("secret123")  # 请修改为你自己的密码
}
SECRET_KEY = os.urandom(24)

# ---------- 初始化 Flask 与认证 ----------
app = Flask(__name__)
app.secret_key = SECRET_KEY
auth = HTTPBasicAuth()

@auth.verify_password
def verify_password(username, password):
    if username in USER_DATA and check_password_hash(USER_DATA.get(username), password):
        return username
    return None

# 装饰器：要求登录但保持会话标记（首次认证后会话内跳过再次弹窗）
def login_required_session(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("authenticated"):
            return f(*args, **kwargs)
        # 使用 HTTP Basic Auth 弹窗进行首轮认证
        user = auth.current_user()
        if user:
            session["authenticated"] = True
            return f(*args, **kwargs)
        return auth.login_required(f)(*args, **kwargs)
    return decorated

# ---------- QA 数据示例 ----------
qa_items = [
    {"id": "q1", "question": "VLC 是什么？", "answer": "VLC 是一个跨平台的开源多媒体播放器，支持多数音视频格式与流媒体。", "metadata": {"tags": ["player","video"]}},
    {"id": "q2", "question": "如何将视频转码为 MP4？", "answer": "可使用 HandBrake 或 FFmpeg 将视频转码为 MP4；FFmpeg 命令示例：\n\n    ffmpeg -i input.mkv -c:v libx264 -crf 23 -c:a aac output.mp4\n\n命令中可根据需要调整编码器与参数。", "metadata": {"tags": ["transcode","ffmpeg","handbrake"]}},
    {"id": "q3", "question": "如何编辑 RAW 照片？", "answer": "使用 Darktable 或 RawTherapee 对 RAW 照片进行非破坏性编辑、白平衡和色彩校正。", "metadata": {"tags": ["photo","raw"]}},
    {"id": "q4", "question": "如何阻止 Windows 更新？", "answer": "企业环境下使用 WSUS 或 Windows Update for Business；个人可通过本地组策略或停止 wuauserv 服务，但这会带来安全风险。", "metadata": {"tags": ["windows","update"]}},
    {"id": "q5", "question": "怎样修图类似 Photoshop？", "answer": "GIMP 可作为开源替代，支持图层、蒙版与插件。示例修图步骤：\n\n    1. 打开图像\n    2. 复制图层并处理非破坏性调整\n    3. 使用曲线/色阶调整曝光和对比度\n    4. 使用蒙版进行局部调整\n", "metadata": {"tags": ["image","gimp"]}}
]
# ---------- 模型与索引构建 ----------
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
model = SentenceTransformer(MODEL_NAME)
def make_corpus_item_text(item):
    return item["question"] + " " + item["answer"]
corpus_texts = [make_corpus_item_text(it) for it in qa_items]
embeddings = model.encode(corpus_texts, convert_to_numpy=True, show_progress_bar=False)
def l2_normalize(x, axis=1, eps=1e-12):
    norms = np.linalg.norm(x, axis=axis, keepdims=True)
    return x / (norms + eps)
embeddings = l2_normalize(embeddings)
d = embeddings.shape[1]
index = faiss.IndexFlatIP(d)
index.add(embeddings)
id_map = [it["id"] for it in qa_items]
id_to_item = {it["id"]: it for it in qa_items}
# ---------- 查询函数 ----------
def query_qa(query, top_k=5):
    q_emb = model.encode([query], convert_to_numpy=True)
    q_emb = l2_normalize(q_emb)
    scores, indices = index.search(q_emb, top_k)
    scores = scores[0]
    indices = indices[0]
    results = []
    for score, idx in zip(scores, indices):
        item_id = id_map[idx]
        item = id_to_item[item_id]
        results.append({
            "id": item_id,
            "question": item["question"],
            "answer": item["answer"],
            "metadata": item.get("metadata", {}),
            "score": float(score)
        })
    return results
# ---------- 前端模板（Bootstrap + 淡金色主题 + 复制按钮，答案用三引号显示） ----------
HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QA 向量检索（金色主题）</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    :root{
      --gold-50: #fffaf0;
      --gold-100: #fff2d6;
      --gold-200: #ffe7b3;
      --gold-500: #d4a55a;
      --gold-700: #b07a3f;
    }
    body { background: linear-gradient(180deg, var(--gold-50), #ffffff); padding-top: 2rem; color:#2b2b2b; }
    .card { border: 1px solid rgba(208,170,120,0.35); box-shadow: 0 2px 6px rgba(160,120,60,0.08); }
    .btn-gold { background: linear-gradient(180deg,var(--gold-200),var(--gold-500)); color:#fff; border: none; }
    .btn-outline-gold { color:var(--gold-700); border-color: rgba(176,122,63,0.45); }
    .score-badge { font-weight:600; background: rgba(208,170,120,0.12); color:var(--gold-700); border-radius:0.4rem; padding:0.25rem 0.5rem; }
    pre.triple { background:#fffdf7; border-radius:6px; padding:0.75rem; white-space:pre-wrap; word-break:break-word; font-family: monospace; position:relative; }
    .copy-btn { position:absolute; top:8px; right:8px; font-size:0.85rem; }
    .meta-badge { background: rgba(176,122,63,0.08); color:var(--gold-700); border-radius:0.35rem; padding:0.25rem 0.45rem; margin-left:0.25rem; }
  </style>
</head>
<body>
  <div class="container">
    <div class="row mb-4 align-items-center">
      <div class="col-md-8">
        <h2 style="color:var(--gold-700)">QA 向量检索（FAISS + sentence-transformers）</h2>
        <p class="text-muted">输入问题并检索最相似的 QA 条目。首次访问会弹出登录（HTTP Basic），认证成功后会话保持。</p>
      </div>
      <div class="col-md-4 text-md-end">
        <form method="post" action="{{ url_for('logout') }}" style="display:inline;">
          <button class="btn btn-outline-gold">登出</button>
        </form>
        <a href="/" class="btn btn-outline-secondary ms-2">重置</a>
      </div>
    </div>

    <form method="post" action="{{ url_for('search') }}" class="row g-3 mb-4">
      <div class="col-12 col-md-9">
        <input type="text" class="form-control form-control-lg" id="query" name="query" placeholder="在此输入问题..." value="{{ query|default('') }}" required>
      </div>
      <div class="col-6 col-md-2">
        <input type="number" class="form-control" id="top_k" name="top_k" min="1" max="20" value="{{ top_k|default('3') }}">
      </div>
      <div class="col-6 col-md-1">
        <button type="submit" class="btn btn-gold w-100">检索</button>
      </div>
    </form>

    {% if results is defined %}
      <div class="row mb-2">
        <div class="col-12"><h5>检索结果（{{ results|length }}）</h5></div>
      </div>
      <div class="row">
        {% for r in results %}
          <div class="col-12">
            <div class="card mb-3">
              <div class="card-body">
                <div class="d-flex justify-content-between mb-2">
                  <div>
                    <span class="score-badge">score {{ '%.4f'|format(r.score) }}</span>
                    <small class="text-muted ms-2">id: {{ r.id }}</small>
                    {% if r.metadata.tags %}
                      {% for t in r.metadata.tags %}
                        <span class="meta-badge">{{ t }}</span>
                      {% endfor %}
                    {% endif %}
                  </div>
                </div>
                <h6 class="card-title">Q: {{ r.question }}</h6>
                <div class="card-text position-relative mt-2">
                  <pre class="triple" id="pre-{{ loop.index }}">
``` 
{{ r.answer }}
``` 
                    <button class="btn btn-sm btn-outline-secondary copy-btn" data-target="pre-{{ loop.index }}">复制</button>
                  </pre>
                </div>
              </div>
            </div>
          </div>
        {% endfor %}
      </div>
    {% endif %}

  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  <script>
    // 复制按钮逻辑：复制三引号块内部文本（去除首尾三引号行）
    document.addEventListener('click', function(e){
      if(e.target.matches('.copy-btn')){
        const tid = e.target.getAttribute('data-target');
        const pre = document.getElementById(tid);
        if(!pre) return;
        // 获取全部文本并移除三引号行（首尾）
        let text = pre.innerText || pre.textContent;
        // 有时 innerText 包含按钮文本 "复制"，去掉按钮文本
        // 先移除复制字样（若存在）
        text = text.replace(/\\b复制\\b/g, '').trim();
        // 移除首尾的 ``` 如果存在
        text = text.replace(/^\\s*```\\s*\\n?/, '').replace(/\\n?\\s*```\\s*$/, '');
        // 复制到剪贴板
        navigator.clipboard.writeText(text).then(function(){
          e.target.innerText = '已复制';
          setTimeout(()=> e.target.innerText = '复制', 1200);
        }, function(){
          // 回退：选择并尝试 execCommand（旧方法）
          const range = document.createRange();
          range.selectNodeContents(pre);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
          try { document.execCommand('copy'); e.target.innerText = '已复制'; setTimeout(()=> e.target.innerText = '复制', 1200);} catch(err){ alert('复制失败，请手动选择并复制。'); }
        });
      }
    });
  </script>
</body>
</html>
"""
# ---------- 路由 ----------
@app.route("/", methods=["GET"])
@login_required_session
def index():
    return render_template_string(HTML)
@app.route("/search", methods=["POST"])
@login_required_session
def search():
    q = request.form.get("query", "").strip()
    top_k = int(request.form.get("top_k", "3"))
    if not q:
        return redirect(url_for("index"))
    results = query_qa(q, top_k=top_k)
    class R: pass
    out = []
    for r in results:
        obj = R()
        obj.id = r["id"]
        obj.question = r["question"]
        obj.answer = r["answer"]
        obj.metadata = r["metadata"]
        obj.score = r["score"]
        out.append(obj)
    return render_template_string(HTML, results=out, query=q, top_k=top_k)
@app.route("/logout", methods=["POST"])
def logout():
    session.pop("authenticated", None)
    return redirect(url_for("index"))
# ---------- 启动 ----------
if __name__ == "__main__":
    # 仅用于本地调试；生产环境使用 WSGI（gunicorn/nginx）
    app.run(host="0.0.0.0", port=5000, debug=True)
