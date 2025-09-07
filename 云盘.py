# app.py
from flask import Flask, request, send_file, jsonify, render_template_string, abort
from werkzeug.utils import secure_filename
import os, shutil, io, zipfile, mimetypes
app = Flask(__name__)
UPLOAD_ROOT = os.path.abspath("uploads")
os.makedirs(UPLOAD_ROOT, exist_ok=True)
ALLOWED_EXTENSIONS = None  # set({'png','jpg','jpeg','gif','txt','pdf','zip'})
def is_allowed_filename(filename: str) -> bool:
    if ALLOWED_EXTENSIONS is None:
        return True
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def safe_join_root(*paths) -> str:
    parts = []
    for p in paths:
        if p is None or p == "":
            continue
        p = p.replace("\\", "/")
        if p.startswith("/"):
            p = p[1:]
        parts.append(p)
    joined = os.path.join(UPLOAD_ROOT, *parts)
    normalized = os.path.abspath(joined)
    if not normalized.startswith(UPLOAD_ROOT):
        raise ValueError("Invalid path (escape attempt)")
    return normalized

def rel_path_from_root(abs_path: str) -> str:
    if abs_path == UPLOAD_ROOT:
        return ""
    rel = os.path.relpath(abs_path, UPLOAD_ROOT)
    return rel.replace("\\", "/")

# Bootstrap-based frontend
INDEX_HTML = """
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>文件管理（Bootstrap）</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{padding:20px;}
    .file-list li{padding:8px 0; border-bottom:1px solid #eee;}
    .preview-area{max-height:420px; overflow:auto; border:1px solid #ddd; padding:8px; border-radius:4px;}
    .crumb {cursor:pointer;}
  </style>
</head>
<body>
<div class="container">
  <h3 class="mb-3">文件管理（支持层级目录）</h3>

  <div class="mb-3">
    <nav aria-label="breadcrumb">
      <ol class="breadcrumb" id="breadcrumb"></ol>
    </nav>
  </div>

  <div class="row mb-3">
    <div class="col-md-8">
      <div class="input-group">
        <input id="newFolderInput" type="text" class="form-control" placeholder="子目录名（例如 docs/reports 或 single_folder）">
        <button id="createFolderBtn" class="btn btn-primary">进入/创建</button>
        <button id="upBtn" class="btn btn-secondary">上一级</button>
      </div>
    </div>
    <div class="col-md-4 text-end">
      <button id="refreshBtn" class="btn btn-outline-secondary">刷新</button>
    </div>
  </div>

  <div class="card mb-3">
    <div class="card-body">
      <form id="uploadForm" class="row g-2 align-items-center">
        <div class="col-md-6">
          <input id="fileInput" class="form-control" type="file" multiple>
        </div>
        <div class="col-md-3">
          <input id="saveAsInput" class="form-control" type="text" placeholder="单文件另存为（可选）">
        </div>
        <div class="col-md-3 text-end">
          <button class="btn btn-success" type="submit">上传</button>
        </div>
      </form>
    </div>
  </div>

  <div class="row">
    <div class="col-md-8">
      <div class="card mb-3">
        <div class="card-header d-flex justify-content-between align-items-center">
          <div>目录内容 /<span id="curPathText"></span></div>
          <div>
            <button id="batchDeleteBtn" class="btn btn-sm btn-danger">批量删除</button>
            <button id="batchZipBtn" class="btn btn-sm btn-outline-primary">批量下载 (ZIP)</button>
          </div>
        </div>
        <ul class="list-unstyled mb-0 p-3 file-list" id="listing"></ul>
      </div>
    </div>

    <div class="col-md-4">
      <div class="card mb-3">
        <div class="card-header">预览</div>
        <div class="card-body preview-area" id="preview">请选择一个文件以预览</div>
      </div>

      <div class="card">
        <div class="card-header">操作</div>
        <div class="card-body">
          <div class="mb-2">
            <button id="renameBtn" class="btn btn-sm btn-outline-secondary w-100 mb-2">重命名选中</button>
            <button id="moveBtn" class="btn btn-sm btn-outline-secondary w-100 mb-2">移动选中</button>
            <button id="downloadBtn" class="btn btn-sm btn-primary w-100">下载选中</button>
          </div>
          <small class="text-muted">支持多选（左侧复选框）</small>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Modals -->
<div class="modal fade" id="promptModal" tabindex="-1"><div class="modal-dialog"><div class="modal-content">
  <div class="modal-header"><h5 class="modal-title" id="promptTitle"></h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
  <div class="modal-body"><input id="promptInput" class="form-control"></div>
  <div class="modal-footer"><button id="promptOk" class="btn btn-primary">确认</button><button class="btn btn-secondary" data-bs-dismiss="modal">取消</button></div>
</div></div></div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
let curPath = "";
const promptModal = new bootstrap.Modal(document.getElementById('promptModal'));
function setCurPath(p){ curPath = p || ""; document.getElementById('curPathText').innerText = curPath; buildBreadcrumb(); loadListing(); }
function buildBreadcrumb(){
  const bc = document.getElementById('breadcrumb'); bc.innerHTML = '';
  const parts = curPath ? curPath.split('/').filter(Boolean) : [];
  const liRoot = document.createElement('li'); liRoot.className='breadcrumb-item crumb'; liRoot.innerText='root'; liRoot.onclick=()=>setCurPath(''); bc.appendChild(liRoot);
  let acc='';
  parts.forEach((part,i)=>{
    acc = acc ? acc + '/' + part : part;
    const li = document.createElement('li'); li.className='breadcrumb-item crumb'; li.innerText=part; li.onclick=(()=>setCurPath(acc)); bc.appendChild(li);
  });
}

document.getElementById('refreshBtn').onclick = ()=>loadListing();
document.getElementById('upBtn').onclick = ()=>{
  if(!curPath) return;
  const parts = curPath.split('/').filter(Boolean); parts.pop(); setCurPath(parts.join('/'));
};
document.getElementById('createFolderBtn').onclick = ()=>{
  const v = document.getElementById('newFolderInput').value.trim();
  if(!v) return;
  fetch('/api/dir', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ path: curPath ? (curPath + '/' + v) : v })})
    .then(r=>r.json()).then(j=>{ if(j.error) alert(j.error); else setCurPath(j.path || ''); });
};

document.getElementById('uploadForm').addEventListener('submit', async (e)=>{
  e.preventDefault();
  const files = document.getElementById('fileInput').files;
  if(files.length===0) { alert('请选择文件'); return; }
  const saveAs = document.getElementById('saveAsInput').value.trim();
  const form = new FormData();
  for(let i=0;i<files.length;i++) form.append('files', files[i], files[i].name);
  form.append('dest_path', curPath);
  if(saveAs) form.append('save_as', saveAs);
  const res = await fetch('/api/upload', { method:'POST', body: form });
  const j = await res.json();
  if(j.error) alert(j.error); else { alert(j.message||'上传成功'); document.getElementById('fileInput').value=''; document.getElementById('saveAsInput').value=''; loadListing(); }
});

// listing
async function loadListing(){
  const res = await fetch('/api/list?path=' + encodeURIComponent(curPath));
  if(!res.ok){ document.getElementById('listing').innerText='无法列出'; return; }
  const data = await res.json(); renderListing(data);
}
function renderListing(data){
  const el = document.getElementById('listing'); el.innerHTML='';
  if(data.error){ el.innerText = data.error; return; }
  if(curPath){
    const li = document.createElement('li'); li.innerHTML = `<div class="d-flex justify-content-between"><div><strong>目录: /${curPath}</strong></div><div></div></div>`; el.appendChild(li);
  }
  // dirs
  data.dirs.forEach(d=>{
    const li = document.createElement('li'); li.className='d-flex justify-content-between align-items-center';
    li.innerHTML = `<div><input type="checkbox" class="itemChk me-2" data-path="${d.relpath}" data-type="dir"> <i class="bi bi-folder-fill"></i> <strong>${d.name}</strong> <small class="text-muted">/${d.relpath}</small></div>
      <div>
        <button class="btn btn-sm btn-outline-secondary me-1" onclick="enterDir('${encodeURIComponent(d.relpath)}')">打开</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteDirConfirm('${encodeURIComponent(d.relpath)}')">删除</button>
      </div>`;
    el.appendChild(li);
  });
  // files
  data.files.forEach(f=>{
    const li = document.createElement('li'); li.className='d-flex justify-content-between align-items-center';
    li.innerHTML = `<div><input type="checkbox" class="itemChk me-2" data-path="${f.relpath}" data-type="file"> 📄 ${f.name} <small class="text-muted">${f.size} bytes</small></div>
      <div>
        <button class="btn btn-sm btn-outline-secondary me-1" onclick="previewFile('${encodeURIComponent(f.relpath)}')">预览</button>
        <button class="btn btn-sm btn-outline-primary me-1" onclick="downloadFile('${encodeURIComponent(f.relpath)}')">下载</button>
        <button class="btn btn-sm btn-outline-secondary me-1" onclick="promptRename('${encodeURIComponent(f.relpath)}')">重命名</button>
        <button class="btn btn-sm btn-outline-secondary" onclick="promptMove('${encodeURIComponent(f.relpath)}')">移动</button>
      </div>`;
    el.appendChild(li);
  });
  if(data.dirs.length===0 && data.files.length===0) el.innerHTML='<li class="text-muted">目录为空</li>';
}

function enterDir(p){ setCurPath(decodeURIComponent(p)); }

async function deleteDirConfirm(p){
  if(!confirm('确定递归删除此目录及其全部内容？')) return;
  const res = await fetch('/api/dir?path=' + p, { method:'DELETE' });
  const j = await res.json(); alert(j.message || j.error); loadListing();
}

async function previewFile(p){
  const res = await fetch('/api/preview?path=' + p);
  const preview = document.getElementById('preview');
  if(!res.ok){ const j=await res.json().catch(()=>null); preview.innerText = j?.error || '预览失败'; return; }
  const ct = res.headers.get('Content-Type') || '';
  if(ct.startsWith('image/')){
    const blob = await res.blob(); const url = URL.createObjectURL(blob); preview.innerHTML = `<img src="${url}" style="max-width:100%"/>`;
  } else if(ct.startsWith('text/') || ct.includes('json')){
    const txt = await res.text(); preview.innerHTML = `<pre>${escapeHtml(txt)}</pre>`;
  } else if(ct === 'application/pdf'){
    const blob = await res.blob(); const url = URL.createObjectURL(blob); preview.innerHTML = `<object data="${url}" type="application/pdf" width="100%" height="400px"></object>`;
  } else {
    preview.innerText = '不支持的预览类型: ' + ct;
  }
}
function escapeHtml(s){ return s.replace(/[&<"'>]/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m])); }
function downloadFile(p){ window.location = '/api/download?path=' + p; }

// batch operations
function getSelected(){ return Array.from(document.querySelectorAll('.itemChk:checked')).map(n=>({path:n.dataset.path, type:n.dataset.type})); }

document.getElementById('batchDeleteBtn').onclick = async ()=>{
  const items = getSelected(); if(items.length===0) { alert('未选择项'); return; }
  if(!confirm('确定批量删除？')) return;
  const res = await fetch('/api/batch_delete', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ items })});
  const j = await res.json(); alert(j.message || JSON.stringify(j)); loadListing();
};

document.getElementById('batchZipBtn').onclick = async ()=>{
  const items = getSelected(); if(items.length===0){ alert('未选择项'); return; }
  const res = await fetch('/api/batch_download', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ items })});
  if(!res.ok){ const j=await res.json().catch(()=>null); alert(j?.error||'打包失败'); return; }
  const blob = await res.blob(); const url = URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download='download.zip'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
};

document.getElementById('downloadBtn').onclick = ()=>{
  const items = getSelected(); if(items.length===0){ alert('未选择项'); return; }
  if(items.length===1 && items[0].type==='file'){ downloadFile(encodeURIComponent(items[0].path)); return; }
  // otherwise trigger zip
  document.getElementById('batchZipBtn').click();
};

function promptRename(encodedPath){
  const path = decodeURIComponent(encodedPath);
  document.getElementById('promptTitle').innerText = '重命名（仅文件或目录名）';
  document.getElementById('promptInput').value = '';
  promptModal.show();
  document.getElementById('promptOk').onclick = async ()=>{
    const newName = document.getElementById('promptInput').value.trim();
    if(!newName){ alert('请输入新名称'); return; }
    promptModal.hide();
    const res = await fetch('/api/rename', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ path, new_name: newName })});
    const j = await res.json(); alert(j.message || j.error); loadListing();
  };
}

function promptMove(encodedPath){
  const path = decodeURIComponent(encodedPath);
  document.getElementById('promptTitle').innerText = '移动到目标目录（相对于根）';
  document.getElementById('promptInput').value = curPath;
  promptModal.show();
  document.getElementById('promptOk').onclick = async ()=>{
    const dest = document.getElementById('promptInput').value.trim();
    promptModal.hide();
    const res = await fetch('/api/move', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ path, dest_dir: dest })});
    const j = await res.json(); alert(j.message || j.error); loadListing();
  };
}

// batch rename/move buttons (operate on first selected)
document.getElementById('renameBtn').onclick = ()=>{
  const items = getSelected(); if(items.length===0){ alert('未选择项'); return; }
  promptRename(encodeURIComponent(items[0].path));
};
document.getElementById('moveBtn').onclick = ()=>{
  const items = getSelected(); if(items.length===0){ alert('未选择项'); return; }
  promptMove(encodeURIComponent(items[0].path));
};

setCurPath('');
</script>
</body>
</html>
"""
@app.route("/")
def index():
    return render_template_string(INDEX_HTML)
# API: list
@app.route("/api/list")
def api_list():
    rel_path = request.args.get('path', '') or ''
    try:
        target = safe_join_root(rel_path)
    except ValueError:
        return jsonify(error="Invalid path"), 400
    if not os.path.exists(target):
        return jsonify(error="Path not found"), 404
    if not os.path.isdir(target):
        return jsonify(error="Not a directory"), 400
    dirs, files = [], []
    with os.scandir(target) as it:
        for entry in it:
            if entry.is_dir():
                dirs.append({"name": entry.name, "relpath": rel_path_from_root(entry.path)})
            elif entry.is_file():
                files.append({"name": entry.name, "relpath": rel_path_from_root(entry.path), "size": entry.stat().st_size})
    dirs.sort(key=lambda x: x['name'].lower()); files.sort(key=lambda x: x['name'].lower())
    return jsonify(dirs=dirs, files=files)
# create dir
@app.route("/api/dir", methods=["POST"])
def api_create_dir():
    data = request.get_json() or {}
    rel_path = (data.get("path") or "").strip()
    if rel_path == "":
        return jsonify(error="Missing path"), 400
    try:
        target = safe_join_root(rel_path)
    except ValueError:
        return jsonify(error="Invalid path"), 400
    if os.path.exists(target):
        if os.path.isdir(target):
            return jsonify(message="目录已存在", path=rel_path_from_root(target))
        return jsonify(error="路径被文件占用"), 400
    os.makedirs(target, exist_ok=True)
    return jsonify(message="目录已创建", path=rel_path_from_root(target))
# delete dir (recursive)
@app.route("/api/dir", methods=["DELETE"])
def api_delete_dir():
    rel_path = request.args.get("path", "")
    recursive = True
    try:
        target = safe_join_root(rel_path)
    except ValueError:
        return jsonify(error="Invalid path"), 400
    if not os.path.exists(target):
        return jsonify(error="路径不存在"), 404
    if not os.path.isdir(target):
        return jsonify(error="不是目录"), 400
    try:
        if recursive:
            shutil.rmtree(target)
        else:
            os.rmdir(target)
    except Exception as e:
        return jsonify(error="删除失败: " + str(e)), 400
    return jsonify(message="目录已删除")
# upload
@app.route("/api/upload", methods=["POST"])
def api_upload():
    dest_path = (request.form.get("dest_path") or "").strip()
    save_as = (request.form.get("save_as") or "").strip()
    try:
        dest_abs = safe_join_root(dest_path)
    except ValueError:
        return jsonify(error="Invalid dest path"), 400
    os.makedirs(dest_abs, exist_ok=True)
    files = request.files.getlist('files') or list(request.files.values())
    if not files:
        return jsonify(error="No files uploaded"), 400
    saved, errors = [], []
    for f in files:
        if f.filename == '':
            errors.append("empty filename"); continue
        filename = secure_filename(f.filename)
        if save_as and len(files) == 1:
            filename = secure_filename(save_as)
        if not filename:
            errors.append("invalid filename"); continue
        if not is_allowed_filename(filename):
            errors.append(f"{filename}: extension not allowed"); continue
        dest_file = os.path.join(dest_abs, filename)
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(dest_file):
            filename_try = f"{base}({counter}){ext}"
            dest_file = os.path.join(dest_abs, filename_try)
            counter += 1
        try:
            f.save(dest_file); saved.append(rel_path_from_root(dest_file))
        except Exception as e:
            errors.append(f"{filename}: save error {e}")
    result = {"saved": saved, "message": f"已保存 {len(saved)} 文件"}
    if errors: result["errors"] = errors
    return jsonify(result)
# download
@app.route("/api/download")
def api_download():
    rel_path = request.args.get("path", "")
    try:
        target = safe_join_root(rel_path)
    except ValueError:
        abort(400, "Invalid path")
    if not os.path.exists(target) or not os.path.isfile(target):
        abort(404, "File not found")
    return send_file(target, as_attachment=True)
# preview
@app.route("/api/preview")
def api_preview():
    rel_path = request.args.get("path", "")
    try:
        target = safe_join_root(rel_path)
    except ValueError:
        return jsonify(error="Invalid path"), 400
    if not os.path.exists(target) or not os.path.isfile(target):
        return jsonify(error="File not found"), 404
    ctype, _ = mimetypes.guess_type(target)
    if ctype is None:
        ctype = 'application/octet-stream'
    if ctype.startswith('text/') or ctype in ('application/json',):
        try:
            with open(target, 'r', encoding='utf-8', errors='replace') as f:
                txt = f.read(200000)
            return (txt, 200, {'Content-Type': ctype + '; charset=utf-8'})
        except Exception as e:
            return jsonify(error="无法读取文本: " + str(e)), 500
    return send_file(target, mimetype=ctype)
# delete file
@app.route("/api/file", methods=["DELETE"])
def api_delete_file():
    rel_path = request.args.get("path", "")
    try:
        target = safe_join_root(rel_path)
    except ValueError:
        return jsonify(error="Invalid path"), 400
    if not os.path.exists(target):
        return jsonify(error="文件不存在"), 404
    if not os.path.isfile(target):
        return jsonify(error="不是文件"), 400
    try:
        os.remove(target)
    except Exception as e:
        return jsonify(error="删除失败: " + str(e)), 500
    return jsonify(message="文件已删除")
# rename
@app.route("/api/rename", methods=["POST"])
def api_rename():
    data = request.get_json() or {}
    rel_path = (data.get("path") or "").strip()
    new_name = (data.get("new_name") or "").strip()
    if not rel_path or not new_name:
        return jsonify(error="缺少 path 或 new_name"), 400
    if '/' in new_name or '\\' in new_name:
        return jsonify(error="new_name 不能包含路径分隔符"), 400
    try:
        old_abs = safe_join_root(rel_path)
    except ValueError:
        return jsonify(error="Invalid path"), 400
    if not os.path.exists(old_abs):
        return jsonify(error="源不存在"), 404
    parent = os.path.dirname(old_abs)
    new_abs = os.path.join(parent, secure_filename(new_name))
    try:
        if os.path.exists(new_abs):
            return jsonify(error="目标已存在"), 400
        os.rename(old_abs, new_abs)
    except Exception as e:
        return jsonify(error="重命名失败: " + str(e)), 500
    return jsonify(message="重命名成功", new_path=rel_path_from_root(new_abs))

# move
@app.route("/api/move", methods=["POST"])
def api_move():
    data = request.get_json() or {}
    rel_path = (data.get("path") or "").strip()
    dest_dir = (data.get("dest_dir") or "").strip()
    try:
        src_abs = safe_join_root(rel_path)
        dest_dir_abs = safe_join_root(dest_dir)
    except ValueError:
        return jsonify(error="Invalid path"), 400
    if not os.path.exists(src_abs):
        return jsonify(error="源不存在"), 404
    if not os.path.isdir(dest_dir_abs):
        return jsonify(error="目标目录不存在"), 404
    name = os.path.basename(src_abs)
    dest_abs = os.path.join(dest_dir_abs, name)
    base, ext = os.path.splitext(name)
    counter = 1
    while os.path.exists(dest_abs):
        dest_abs = os.path.join(dest_dir_abs, f"{base}({counter}){ext}")
        counter += 1
    try:
        shutil.move(src_abs, dest_abs)
    except Exception as e:
        return jsonify(error="移动失败: " + str(e)), 500
    return jsonify(message="移动成功", new_path=rel_path_from_root(dest_abs))
# batch delete
@app.route("/api/batch_delete", methods=["POST"])
def api_batch_delete():
    data = request.get_json() or {}
    items = data.get("items") or []
    if not isinstance(items, list) or len(items) == 0:
        return jsonify(error="没有 items"), 400
    errors = []; deleted = []
    for it in items:
        p = it.get("path")
        if not p:
            errors.append({"item": it, "error": "missing path"}); continue
        try:
            abs_p = safe_join_root(p)
        except ValueError:
            errors.append({"path": p, "error": "invalid path"}); continue
        if not os.path.exists(abs_p):
            errors.append({"path": p, "error": "not found"}); continue
        try:
            if os.path.isdir(abs_p):
                shutil.rmtree(abs_p)
            else:
                os.remove(abs_p)
            deleted.append(p)
        except Exception as e:
            errors.append({"path": p, "error": str(e)})
    return jsonify(message="批量删除完成", deleted=deleted, errors=errors)
# batch download
@app.route("/api/batch_download", methods=["POST"])
def api_batch_download():
    data = request.get_json() or {}
    items = data.get("items") or []
    if not isinstance(items, list) or len(items) == 0:
        return jsonify(error="没有 items"), 400
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    for it in items:
        p = it.get("path")
        if not p: continue
        try:
            abs_p = safe_join_root(p)
        except ValueError:
            continue
        if not os.path.exists(abs_p): continue
        if os.path.isdir(abs_p):
            for root, _, files in os.walk(abs_p):
                for fname in files:
                    full = os.path.join(root, fname)
                    arcname = os.path.join(rel_path_from_root(abs_p), os.path.relpath(full, abs_p))
                    z.write(full, arcname)
        else:
            z.write(abs_p, rel_path_from_root(abs_p))
    z.close(); buf.seek(0)
    return send_file(buf, mimetype='application/zip', as_attachment=True, download_name='download.zip')
# info
@app.route("/api/info")
def api_info():
    return jsonify(upload_root=UPLOAD_ROOT)
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
