from flask import Flask, render_template_string, request, jsonify
import re
from transformers import pipeline
import threading
import time

# ---------- 配置 ----------
MODEL_ZH_TO_EN = "Helsinki-NLP/opus-mt-zh-en"
MODEL_EN_TO_ZH = "Helsinki-NLP/opus-mt-en-zh"
TRANSLATE_TIMEOUT = 60  # 后端处理超时提示（秒）

# ---------- Flask app ----------
app = Flask(__name__)

# 页面模板（使用 Bootstrap 5）
HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>双向翻译聊天室</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    html, body { height: 100%; background: #eaf7ef; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial; }
    .chat-wrapper { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 32px; box-sizing: border-box; }
    .chat-container {
      width: 100%;
      max-width: 1100px;             /* 更宽的中间区域 */
      background: linear-gradient(180deg,#f7fff8,#eef9ee); /* 护眼柔和渐变 */
      border-radius: 16px;
      padding: 28px;
      box-shadow: 0 10px 30px rgba(14, 30, 20, 0.06);
      height: calc(100vh - 96px);    /* 更大的可用高度 */
      display: flex;
      flex-direction: column;
      gap: 18px;
      box-sizing: border-box;
    }
    .chat-header { display:flex; align-items:center; justify-content:space-between; gap:12px; }
    .chat-box {
      flex: 1 1 auto;
      overflow-y: auto;
      background: rgba(255,255,255,0.7);
      border-radius: 14px;
      padding: 26px;
      border: 1.5px solid rgba(34, 197, 94, 0.12); /* 柔和绿色边框 */
    }
    .msg { max-width: 90%; padding: .85rem 1.05rem; border-radius: 12px; margin-bottom: 14px; box-shadow: 0 4px 10px rgba(16,24,40,0.04); line-height:1.5; font-size: 1rem; }
    .msg.me { background: linear-gradient(90deg,#dff6e9,#d0f0df); margin-left: auto; text-align: left; }
    .msg.them { background: #ffffff; margin-right: auto; text-align: left; }
    .meta { font-size: .78rem; color: #4b5563; margin-top: .25rem; }
    .status { font-size: .9rem; color:#374151; }
    .placeholder-center { height:100%; display:flex; align-items:center; justify-content:center; color:#6b7280; }
    .controls { display:flex; gap:12px; align-items:flex-end; }
    textarea#msg { min-height:56px; max-height:180px; resize:vertical; border-radius:10px; padding:12px; border:1px solid rgba(16,24,40,0.06); }
    .small-muted { font-size: .85rem; color:#475569; }
    .btn-outline-primary { border-color: rgba(16,24,40,0.06); }
    @media (max-width: 720px) {
      .chat-container { padding: 18px; height: calc(100vh - 48px); max-width: 100%; border-radius: 12px; }
      .msg { max-width: 100%; }
      .controls { flex-direction: column; align-items:stretch; }
    }
  </style>
</head>
<body>
  <div class="chat-wrapper">
    <div class="chat-container shadow-sm">
      <div class="chat-header">
        <div>
          <h5 class="mb-0">双向翻译聊天室</h5>
          <div class="status" id="modelStatus">模型状态：<span class="badge bg-secondary">正在加载...</span></div>
        </div>
        <div>
          <button id="clearBtn" class="btn btn-sm btn-outline-secondary">清空会话</button>
        </div>
      </div>

      <div id="chat" class="chat-box" aria-live="polite" aria-atomic="false">
        <div class="placeholder-center" id="welcome">
          <div class="text-center">
            <h6 class="mb-2">欢迎 — 输入中文或英文开始对话</h6>
            <div class="text-muted">发送后会自动检测语言并翻译给对方</div>
          </div>
        </div>
      </div>

      <form id="form" class="mt-3 d-flex gap-2" onsubmit="return false;">
        <textarea id="msg" class="form-control" rows="2" placeholder="输入中文或英文，按 Enter 发送（Shift+Enter 换行）" aria-label="消息"></textarea>
        <div class="d-flex flex-column align-items-end">
          <button id="send" class="btn btn-primary mb-2" type="button">发送</button>
          <button id="sendAsync" class="btn btn-outline-primary btn-sm" type="button" title="异步发送（允许并发）">并发发送</button>
        </div>
      </form>

      <div class="mt-2 text-end small-muted">首次启动会下载模型，可能需要较长时间。刷新页面可清空会话。</div>
    </div>
  </div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
const chat = document.getElementById('chat');
const msg = document.getElementById('msg');
const send = document.getElementById('send');
const sendAsync = document.getElementById('sendAsync');
const modelStatus = document.getElementById('modelStatus');
const clearBtn = document.getElementById('clearBtn');
let busy = false;

// 安全时间（前端）避免长时间等待
const FRONTEND_TIMEOUT = {{ timeout }};

function setModelReady(ready) {
  modelStatus.innerHTML = '模型状态：' + (ready
    ? '<span class="badge bg-success">已就绪</span>'
    : '<span class="badge bg-secondary">正在加载...</span>');
}

function appendBubble(text, who, meta) {
  document.getElementById('welcome')?.remove();
  const wrapper = document.createElement('div');
  wrapper.className = 'd-flex flex-column';
  wrapper.style.alignItems = who === 'me' ? 'flex-end' : 'flex-start';
  const b = document.createElement('div');
  b.className = 'msg ' + (who === 'me' ? 'me' : 'them');
  b.innerText = text;
  wrapper.appendChild(b);
  if (meta) {
    const m = document.createElement('div');
    m.className = 'meta';
    m.innerText = meta;
    wrapper.appendChild(m);
  }
  chat.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
}

function showError(text) {
  appendBubble(text, 'them', '');
}

async function postTranslate(payload) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FRONTEND_TIMEOUT * 1000);
  try {
    const resp = await fetch('/translate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    if (!resp.ok) {
      const j = await resp.json().catch(()=>({error:'网络错误'}));
      throw new Error(j.error || '网络错误');
    }
    return await resp.json();
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('请求超时');
    throw e;
  }
}

async function sendMessage(concurrent=false) {
  const text = msg.value.trim();
  if (!text) return;
  if (!concurrent && busy) return;
  if (!concurrent) busy = true;
  send.disabled = true;
  sendAsync.disabled = true;

  appendBubble(text, 'me', '原文');
  msg.value = '';
  try {
    const j = await postTranslate({text});
    if (j && j.translation) {
      appendBubble(j.translation, 'them', '方向: ' + j.direction);
    } else {
      showError('翻译失败：无响应');
    }
  } catch (err) {
    showError('翻译失败：' + (err.message || err));
  } finally {
    if (!concurrent) busy = false;
    send.disabled = false;
    sendAsync.disabled = false;
  }
}

send.addEventListener('click', ()=>sendMessage(false));
sendAsync.addEventListener('click', ()=>sendMessage(true));
msg.addEventListener('keydown', function(e){
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage(false);
  }
});

clearBtn.addEventListener('click', ()=>{
  chat.innerHTML = '<div class="placeholder-center" id="welcome"><div class="text-center"><h6 class="mb-2">欢迎 — 输入中文或英文开始对话</h6><div class="text-muted">发送后会自动检测语言并翻译给对方</div></div></div>';
});

// on load, check model status
(async function(){
  try {
    const resp = await fetch('/model_status');
    const j = await resp.json();
    setModelReady(!!j.ready);
  } catch (e) {
    setModelReady(false);
  }
})();
</script>
</body>
</html>
"""

# ---------- Pipelines (预加载) ----------
pipe_zh_en = None
pipe_en_zh = None
models_ready = False
_models_lock = threading.Lock()

def load_models():
    global pipe_zh_en, pipe_en_zh, models_ready
    with _models_lock:
        if models_ready:
            return
        print("正在创建 translation pipelines，可能需要一些时间，请稍候...")
        pipe_zh_en = pipeline("translation", model=MODEL_ZH_TO_EN)
        pipe_en_zh = pipeline("translation", model=MODEL_EN_TO_ZH)
        models_ready = True
        print("pipelines 已就绪。")

# 后台加载模型
threading.Thread(target=load_models, daemon=True).start()

# ---------- 辅助函数 ----------
def detect_direction(text: str) -> str:
    zh = len(re.findall(r"[\u4e00-\u9fff]", text))
    en = len(re.findall(r"[A-Za-z]", text))
    total = len(text) or 1
    if zh / total >= 0.4:
        return "zh->en"
    if en / total >= 0.4:
        return "en->zh"
    return "zh->en"

def translate_with_pipeline(text: str, direction: str) -> str:
    global pipe_zh_en, pipe_en_zh, models_ready
    if not models_ready:
        # 阻塞加载（首次请求时若后台未完成）
        load_models()
    if direction == "zh->en":
        out = pipe_zh_en(text, max_length=512)
    else:
        out = pipe_en_zh(text, max_length=512)
    return out[0]["translation_text"]

# ---------- 路由 ----------
@app.route("/")
def index():
    # 渲染时将后端超时配置传给前端
    return render_template_string(HTML, timeout=TRANSLATE_TIMEOUT)

@app.route("/model_status")
def model_status():
    return jsonify({"ready": bool(models_ready)})

@app.route("/translate", methods=["POST"])
def translate():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error":"empty"}), 400
    direction = detect_direction(text)
    start = time.time()
    try:
        translation = translate_with_pipeline(text, direction)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    elapsed = time.time() - start
    if elapsed > TRANSLATE_TIMEOUT:
        return jsonify({"error":"处理超时"}), 504
    return jsonify({"direction": direction, "translation": translation})

# ---------- 启动 ----------
if __name__ == "__main__":
    print("启动 Flask 应用（访问 http://127.0.0.1:5000 ）")
    app.run(host="0.0.0.0", port=5000, debug=False)
