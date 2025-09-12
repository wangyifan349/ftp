from flask import Flask, request, jsonify, send_file, render_template_string, abort
import os
import shutil
from werkzeug.utils import secure_filename
from pathlib import Path
app = Flask(__name__)
ROOT_STORAGE = os.path.abspath(os.environ.get("FILEMGR_ROOT", "storage_root"))
os.makedirs(ROOT_STORAGE, exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB
# HTML (Bootstrap) 前端内嵌
INDEX_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>文件管理器</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding: 20px; }
    #file-tree { max-height: 60vh; overflow: auto; border: 1px solid #e5e7eb; border-radius: .25rem; padding: .75rem; background: #fff; }
    .item-row { display:flex; justify-content:space-between; align-items:center; padding: .25rem .5rem; border-radius:.25rem; }
    .item-row:hover { background: #f8fafc; cursor: default; }
    .folder-name { font-weight: 600; }
    .drop-target { background: #eef7ff !important; border: 1px dashed #93c5fd; }
    .small-muted { font-size: .9rem; color: #6b7280; }
  </style>
</head>
<body class="bg-light">
  <div class="container">
    <h3 class="mb-3">文件管理器</h3>

    <div class="mb-3 d-flex gap-2 align-items-center">
      <div>当前路径：<strong id="current-path">/</strong></div>
      <button id="up-btn" class="btn btn-sm btn-outline-secondary">上一级</button>
      <input id="mkdir-name" class="form-control form-control-sm w-auto" placeholder="新建目录名">
      <button id="mkdir-btn" class="btn btn-sm btn-primary">新建目录</button>

      <div class="ms-auto">
        <input id="upload-input" type="file" multiple style="display:none">
        <button id="choose-btn" class="btn btn-sm btn-success">选择文件</button>
        <button id="upload-btn" class="btn btn-sm btn-success">上传</button>
      </div>
    </div>

    <div class="mb-2 small-muted">提示：拖拽条目到目录上以移动；可多选上传；删除目录会递归（有确认）。</div>

    <div id="file-tree" class="bg-white"></div>

    <div id="log" class="mt-3"></div>
  </div>

<script>
const api = {
  list: p => fetch(`/api/list?path=${encodeURIComponent(p||"")}`).then(r=>r.json()),
  mkdir: (path,name) => fetch('/api/mkdir',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,name})}).then(r=>r.json()),
  upload: (path, files) => { const fd=new FormData(); fd.append('path', path); for (const f of files) fd.append('file', f); return fetch('/api/upload',{method:'POST',body:fd}).then(r=>r.json()) },
  download: path => { window.location = `/api/download?path=${encodeURIComponent(path)}`; },
  delete: (path, recursive=false) => fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path, recursive})}).then(r=>r.json()),
  move: (src,dest_dir) => fetch('/api/move',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({src,dest_dir})}).then(r=>r.json())
};

let currentPath = "";

function log(msg, type='info'){
  const el = document.getElementById('log');
  const div = document.createElement('div');
  div.className = type==='error' ? 'text-danger' : 'text-muted';
  div.textContent = msg;
  el.prepend(div);
  setTimeout(()=>{ if (el.children.length>10) el.removeChild(el.lastChild); }, 5000);
}

function setCurrentPath(p){
  currentPath = p||"";
  document.getElementById('current-path').textContent = "/" + currentPath;
  load();
}

async function load(){
  const res = await api.list(currentPath);
  if (res.error){ alert(res.error); return; }
  renderList(res.items);
}

function renderList(items){
  const container = document.getElementById('file-tree');
  container.innerHTML = '';

  // 上一级
  const upRow = document.createElement('div');
  upRow.className = 'item-row';
  upRow.innerHTML = `<div class="text-muted">.. (上一级)</div>`;
  upRow.onclick = ()=> {
    const parts = currentPath.split('/').filter(Boolean);
    parts.pop();
    setCurrentPath(parts.join('/'));
  };
  container.appendChild(upRow);

  items.forEach(it=>{
    const row = document.createElement('div');
    row.className = 'item-row';
    row.draggable = true;
    row.dataset.path = it.path;

    const left = document.createElement('div');
    left.style.display = 'flex';
    left.style.gap = '12px';
    left.style.alignItems = 'center';
    const icon = document.createElement('div');
    icon.innerHTML = it.is_dir ? '📁' : '📄';
    const name = document.createElement('div');
    name.textContent = it.name + (it.is_dir ? '/' : '');
    if (it.is_dir) name.className = 'folder-name';
    left.appendChild(icon);
    left.appendChild(name);

    const right = document.createElement('div');

    if (!it.is_dir){
      const dl = document.createElement('button'); dl.className='btn btn-sm btn-outline-primary me-1'; dl.textContent='下载';
      dl.onclick = (e)=>{ e.stopPropagation(); api.download(it.path); };
      right.appendChild(dl);
    }

    const del = document.createElement('button'); del.className='btn btn-sm btn-outline-danger me-1'; del.textContent='删除';
    del.onclick = async (e) => {
      e.stopPropagation();
      const confirmMsg = it.is_dir ? `确定要递归删除目录 ${it.path} 吗？` : `确定要删除文件 ${it.path} 吗？`;
      if (!confirm(confirmMsg)) return;
      const r = await api.delete(it.path, it.is_dir);
      if (r.error) { log(r.error, 'error'); } else { log('删除成功: ' + it.path); load(); }
    };
    right.appendChild(del);

    const moveBtn = document.createElement('button'); moveBtn.className='btn btn-sm btn-outline-secondary'; moveBtn.textContent='选中并移动';
    moveBtn.onclick = async (e) => {
      e.stopPropagation();
      const dest = prompt("输入目标目录（相对路径，留空为根）:");
      if (dest===null) return;
      const r = await api.move(it.path, dest.trim());
      if (r.error) { alert(r.error); } else { log('移动到 ' + r.moved_to); load(); }
    };
    right.appendChild(moveBtn);

    row.appendChild(left);
    row.appendChild(right);

    // 点击进入或下载
    row.onclick = () => {
      if (it.is_dir) setCurrentPath(it.path);
      else api.download(it.path);
    };

    // 拖放支持 - 源
    row.addEventListener('dragstart', (ev)=>{
      ev.dataTransfer.setData('text/plain', it.path);
    });

    // 作为 drop 目标（仅目录）
    if (it.is_dir){
      row.addEventListener('dragover', (ev)=>{ ev.preventDefault(); row.classList.add('drop-target'); });
      row.addEventListener('dragleave', ()=> row.classList.remove('drop-target'));
      row.addEventListener('drop', async (ev)=>{
        ev.preventDefault();
        row.classList.remove('drop-target');
        const src = ev.dataTransfer.getData('text/plain');
        if (!src) return;
        if (src === it.path || src.startsWith(it.path + '/')) { alert('不能移动到自身或子目录'); return; }
        const res = await api.move(src, it.path);
        if (res.error) alert(res.error); else { log('移动成功: ' + src + ' → ' + res.moved_to); load(); }
      });
    }

    container.appendChild(row);
  });
}

// UI 控件
document.getElementById('up-btn').onclick = ()=> {
  const parts = currentPath.split('/').filter(Boolean);
  parts.pop();
  setCurrentPath(parts.join('/'));
};

document.getElementById('mkdir-btn').onclick = async ()=>{
  const name = document.getElementById('mkdir-name').value.trim();
  if (!name) return alert('请输入目录名');
  const res = await api.mkdir(currentPath, name);
  if (res.error) alert(res.error); else { document.getElementById('mkdir-name').value=''; load(); }
};

document.getElementById('choose-btn').onclick = ()=> document.getElementById('upload-input').click();

document.getElementById('upload-btn').onclick = async ()=>{
  const input = document.getElementById('upload-input');
  if (input.files.length === 0) return alert('请选择文件');
  const res = await api.upload(currentPath, input.files);
  if (res.error) alert(res.error); else { log('上传成功: ' + (res.saved||[]).join(', ')); input.value=''; load(); }
};

// 初始化
setCurrentPath("");

</script>
</body>
</html>
"""
def safe_join(root: str, *paths: str) -> str:
    root_p = Path(root).resolve()
    target = root_p.joinpath(*paths).resolve()
    try:
        target.relative_to(root_p)
    except Exception:
        raise ValueError("Attempt to access outside storage root")
    return str(target)
def list_directory(rel_path=""):
    target = safe_join(ROOT_STORAGE, rel_path) if rel_path else str(Path(ROOT_STORAGE))
    if not os.path.exists(target):
        raise FileNotFoundError
    if not os.path.isdir(target):
        raise NotADirectoryError
    items = []
    with os.scandir(target) as it:
        for entry in it:
            items.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "path": os.path.join(rel_path, entry.name).replace("\\", "/") if rel_path else entry.name.replace("\\", "/"),
                "size": entry.stat().st_size if entry.is_file() else None
            })
    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return items
@app.route("/")
def index():
    return render_template_string(INDEX_HTML)
@app.route("/api/list")
def api_list():
    rel = request.args.get("path", "").strip().strip("/")
    try:
        items = list_directory(rel)
    except FileNotFoundError:
        return jsonify({"error": "目录不存在"}), 404
    except NotADirectoryError:
        return jsonify({"error": "不是目录"}), 400
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    return jsonify({"path": rel, "items": items})
@app.route("/api/mkdir", methods=["POST"])
def api_mkdir():
    data = request.get_json() or {}
    rel = (data.get("path") or "").strip().strip("/")
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name 必须提供"}), 400
    name = secure_filename(name)
    try:
        target = safe_join(ROOT_STORAGE, rel, name) if rel else safe_join(ROOT_STORAGE, name)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    try:
        os.makedirs(target, exist_ok=False)
    except FileExistsError:
        return jsonify({"error": "目录已存在"}), 400
    return jsonify({"ok": True, "path": os.path.join(rel, name).replace("\\", "/")})
@app.route("/api/upload", methods=["POST"])
def api_upload():
    rel = (request.form.get("path") or "").strip().strip("/")
    try:
        dest = safe_join(ROOT_STORAGE, rel) if rel else safe_join(ROOT_STORAGE)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not os.path.isdir(dest):
        return jsonify({"error": "目标目录不存在"}), 404
    if 'file' not in request.files:
        return jsonify({"error": "没有文件上传（字段名为 file）"}), 400
    files = request.files.getlist("file")
    saved = []
    for f in files:
        filename = secure_filename(f.filename)
        if not filename:
            continue
        out = os.path.join(dest, filename)
        # 若文件存在则添加 suffix 避免覆盖
        if os.path.exists(out):
            base, ext = os.path.splitext(filename)
            i = 1
            while os.path.exists(os.path.join(dest, f"{base}({i}){ext}")):
                i += 1
            filename = f"{base}({i}){ext}"
            out = os.path.join(dest, filename)
        f.save(out)
        saved.append(os.path.join(rel, filename).replace("\\", "/") if rel else filename.replace("\\", "/"))
    return jsonify({"ok": True, "saved": saved})
@app.route("/api/download")
def api_download():
    rel = (request.args.get("path") or "").lstrip("/")
    if not rel:
        return jsonify({"error": "path 必须提供"}), 400
    try:
        target = safe_join(ROOT_STORAGE, rel)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not os.path.exists(target) or not os.path.isfile(target):
        return jsonify({"error": "文件不存在"}), 404
    return send_file(target, as_attachment=True)
@app.route("/api/delete", methods=["POST"])
def api_delete():
    data = request.get_json() or {}
    rel = (data.get("path") or "").lstrip("/")
    recursive = bool(data.get("recursive", False))
    if not rel:
        return jsonify({"error": "path 必须提供"}), 400
    try:
        target = safe_join(ROOT_STORAGE, rel)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not os.path.exists(target):
        return jsonify({"error": "目标不存在"}), 404
    try:
        if os.path.isdir(target):
            # 递归删除
            shutil.rmtree(target)
        else:
            os.remove(target)
    except Exception as e:
        return jsonify({"error": f"删除失败: {str(e)}"}), 500
    return jsonify({"ok": True})
@app.route("/api/move", methods=["POST"])
def api_move():
    data = request.get_json() or {}
    src = (data.get("src") or "").lstrip("/")
    dest_dir = (data.get("dest_dir") or "").strip().strip("/")
    if not src:
        return jsonify({"error": "src 必须提供"}), 400
    try:
        abs_src = safe_join(ROOT_STORAGE, src)
        abs_dest_dir = safe_join(ROOT_STORAGE, dest_dir) if dest_dir else safe_join(ROOT_STORAGE)
    except ValueError:
        return jsonify({"error": "非法路径"}), 400
    if not os.path.exists(abs_src):
        return jsonify({"error": "源不存在"}), 404
    if not os.path.isdir(abs_dest_dir):
        return jsonify({"error": "目标目录不存在"}), 404
    name = os.path.basename(abs_src)
    abs_dest = os.path.join(abs_dest_dir, name)
    # 防止覆盖：如果目标存在，返回错误
    if os.path.exists(abs_dest):
        return jsonify({"error": "目标已存在"}), 400
    try:
        shutil.move(abs_src, abs_dest)
    except Exception as e:
        return jsonify({"error": f"移动失败: {str(e)}"}), 500
    rel_dest = os.path.join(dest_dir, name).replace("\\", "/") if dest_dir else name.replace("\\", "/")
    return jsonify({"ok": True, "moved_to": rel_dest})
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
