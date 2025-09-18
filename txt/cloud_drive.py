#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cloud_drive.py
单文件 Flask 云盘示例（演示用途）
功能：
- 分层目录浏览/创建
- 多文件上传（支持拖拽）
- 移动/删除
- 分享链接（无认证）
注意：仅演示，生产请加强安全。
"""
import os
import io
import uuid
import json
import shutil
from pathlib import Path
from urllib.parse import unquote
from flask import (
    Flask, request, render_template_string, jsonify, send_file,
    redirect, url_for, abort
)
from werkzeug.utils import secure_filename

# ---------- 配置 ----------
ROOT = Path("storage")
ROOT.mkdir(parents=True, exist_ok=True)
SHARE_DB = Path("share_db.json")
if not SHARE_DB.exists():
    SHARE_DB.write_text("{}", encoding="utf-8")
ALLOWED_EXTENSIONS = None  # None 表示允许所有类型
MAX_CONTENT_LENGTH = 1024 * 1024 * 1024  # 1 GiB
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
# ---------- 辅助函数 ----------
def safe_join_root(relative_path: str) -> Path:
    if relative_path is None or relative_path == "":
        relative_path = "."
    relative_path = unquote(relative_path)
    candidate = (ROOT / relative_path).resolve()
    root_resolved = ROOT.resolve()
    if not str(candidate).startswith(str(root_resolved)):
        raise ValueError("Illegal path")
    return candidate
def allowed_file(filename: str) -> bool:
    if ALLOWED_EXTENSIONS is None:
        return True
    extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return extension in ALLOWED_EXTENSIONS
def list_directory(relative_path: str):
    target_path = safe_join_root(relative_path)
    if not target_path.exists():
        return {"files": [], "dirs": []}
    files_list = []
    dirs_list = []
    for entry in sorted(target_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        stat_info = entry.stat()
        item = {
            "name": entry.name,
            "is_dir": entry.is_dir(),
            "size": stat_info.st_size,
            "mtime": int(stat_info.st_mtime)
        }
        if entry.is_dir():
            dirs_list.append(item)
        else:
            files_list.append(item)
    return {"files": files_list, "dirs": dirs_list}
def load_share_db():
    try:
        return json.loads(SHARE_DB.read_text(encoding="utf-8"))
    except Exception:
        return {}
def save_share_db(mapping):
    SHARE_DB.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
def create_share(relative_path: str):
    mapping = load_share_db()
    share_id = uuid.uuid4().hex[:12]
    mapping[share_id] = relative_path
    save_share_db(mapping)
    return share_id
def resolve_share(share_id: str):
    mapping = load_share_db()
    return mapping.get(share_id)
# ---------- 前端模板 ----------
TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>简单云盘</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    .dropzone { border:2px dashed #ccc; padding:18px; border-radius:8px; text-align:center; background:#f8f9fa; }
    .dropzone.dragover { background:#eef; border-color:#66f; }
    .file-row { display:flex; justify-content:space-between; align-items:center; padding:8px; border-bottom:1px solid #eee; }
    .muted { color:#666; font-size:0.9rem; }
    .active { background-color:#d0ebff; }
  </style>
</head>
<body>
<div class="container py-3">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h4>简单云盘</h4>
    <div>
      <button id="btnUp" class="btn btn-sm btn-secondary">上级</button>
      <button id="btnNew" class="btn btn-sm btn-primary">新建目录</button>
    </div>
  </div>

  <div class="mb-2">位置：<span id="curPath">{{ current_path }}</span></div>

  <div id="dropzone" class="dropzone mb-3">
    拖拽文件到此上传（或点击选择）
    <div class="mt-2">
      <input id="fileInput" type="file" multiple style="display:none;">
      <button id="btnChoose" class="btn btn-outline-primary btn-sm">选择文件</button>
    </div>
  </div>

  <div class="mb-3">
    <h6>目录</h6>
    <div id="dirs" class="list-group mb-2"></div>
    <h6>文件</h6>
    <div id="files" class="list-group"></div>
  </div>

  <div class="mb-3">
    <label>移动目标（先在列表中“选择”项，然后选择目标并移动）</label>
    <select id="moveTarget" class="form-select mb-2"></select>
    <div class="muted">选中项在每行点“选择”按钮切换状态。</div>
  </div>

  <hr>

  <div>
    <h6>分享管理</h6>
    <div id="shares"></div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
let currentPath = "{{ current_path }}";
const curPathEl = document.getElementById('curPath');
const dirsEl = document.getElementById('dirs');
const filesEl = document.getElementById('files');
const moveTarget = document.getElementById('moveTarget');
const sharesEl = document.getElementById('shares');
let selectedSet = new Set();

function apiFetch(path, options){ return fetch('/api'+path, options).then(r=>r.ok?r.json():r.text().then(t=>{throw t;})); }

function refresh(){
  apiFetch('/list?path=' + encodeURIComponent(currentPath)).then(data=>{
    curPathEl.textContent = currentPath;
    dirsEl.innerHTML = '';
    filesEl.innerHTML = '';
    data.dirs.forEach(d=>{
      const div = document.createElement('div');
      div.className='list-group-item file-row';
      div.innerHTML = `<div style="flex:1"><strong class="dir-link" data-name="${d.name}">📁 ${d.name}</strong></div>
        <div>
          <button class="btn btn-sm btn-outline-primary select-btn" data-type="dir" data-name="${d.name}">选择</button>
          <button class="btn btn-sm btn-outline-secondary share-btn" data-name="${d.name}">分享</button>
          <button class="btn btn-sm btn-danger del-btn" data-type="dir" data-name="${d.name}">删除</button>
        </div>`;
      dirsEl.appendChild(div);
    });
    data.files.forEach(f=>{
      const div = document.createElement('div');
      div.className='list-group-item file-row';
      div.innerHTML = `<div style="flex:1">📄 ${f.name} <div class="muted">${f.size} bytes</div></div>
        <div>
          <a class="btn btn-sm btn-success" href="/download?path=${encodeURIComponent(currentPath+'/'+f.name)}" target="_blank">下载</a>
          <button class="btn btn-sm btn-outline-primary select-btn" data-type="file" data-name="${f.name}">选择</button>
          <button class="btn btn-sm btn-outline-secondary share-btn" data-name="${f.name}">分享</button>
          <button class="btn btn-sm btn-danger del-btn" data-type="file" data-name="${f.name}">删除</button>
        </div>`;
      filesEl.appendChild(div);
    });

    // bind dir links
    document.querySelectorAll('.dir-link').forEach(el=>{
      el.onclick = () => {
        const name = el.dataset.name;
        currentPath = (currentPath === '.' ? name : currentPath + '/' + name);
        refresh();
        refreshTargets();
      };
    });
    // bind selects
    document.querySelectorAll('.select-btn').forEach(b=>{
      b.onclick = () => {
        const type = b.dataset.type || 'file';
        const name = b.dataset.name;
        const key = type + '::' + (currentPath + '/' + name);
        if (selectedSet.has(key)){
          selectedSet.delete(key);
          b.textContent = '选择';
          b.classList.remove('active');
        } else {
          selectedSet.add(key);
          b.textContent = '已选';
          b.classList.add('active');
        }
      };
    });
    // bind share
    document.querySelectorAll('.share-btn').forEach(b=>{
      b.onclick = () => {
        const name = b.dataset.name;
        const target = currentPath + '/' + name;
        fetch('/api/share', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: target})})
          .then(r=>r.json()).then(j=>{ alert('分享链接: ' + window.location.origin + '/s/' + j.share_id); refreshShares(); });
      };
    });
    // bind delete
    document.querySelectorAll('.del-btn').forEach(b=>{
      b.onclick = () => {
        const name = b.dataset.name, type = b.dataset.type;
        if (!confirm('确定删除 ' + name + ' ?')) return;
        fetch('/api/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: currentPath + '/' + name})})
          .then(r=>{ if(!r.ok) r.text().then(t=>alert('删除失败:'+t)); else { refresh(); refreshTargets(); refreshShares(); } });
      };
    });

  }).catch(e=>{ console.error(e); alert('读取失败'); });
}

document.getElementById('btnChoose').onclick = ()=> document.getElementById('fileInput').click();
document.getElementById('fileInput').onchange = ()=> {
  const files = document.getElementById('fileInput').files;
  uploadFiles(files);
};

const dz = document.getElementById('dropzone');
dz.addEventListener('dragover', e=>{ e.preventDefault(); dz.classList.add('dragover'); });
dz.addEventListener('dragleave', e=>{ dz.classList.remove('dragover'); });
dz.addEventListener('drop', e=>{ e.preventDefault(); dz.classList.remove('dragover'); uploadFiles(e.dataTransfer.files); });

function uploadFiles(files){
  if(!files || files.length===0) return;
  const form = new FormData();
  for(let i=0;i<files.length;i++) form.append('file', files[i]);
  form.append('path', currentPath);
  fetch('/api/upload', {method:'POST', body: form})
    .then(r=>r.json()).then(j=>{ if(j.success){ refresh(); refreshTargets(); } else alert('上传失败'); })
    .catch(e=>{ alert('上传错误'); console.error(e); });
}

document.getElementById('btnUp').onclick = ()=>{
  if(!currentPath || currentPath=='.'){ currentPath='.'; refresh(); return; }
  const parts = currentPath.split('/').filter(x=>x);
  parts.pop();
  currentPath = parts.length?parts.join('/') : '.';
  refresh(); refreshTargets();
};

document.getElementById('btnNew').onclick = ()=>{
  const name = prompt('目录名：');
  if(!name) return;
  fetch('/api/mkdir', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: currentPath + '/' + name})})
    .then(r=>{ if(!r.ok) r.text().then(t=>alert('创建失败:'+t)); else { refresh(); refreshTargets(); } });
};

function refreshTargets(){
  fetch('/api/list_all_dirs?path=' + encodeURIComponent(currentPath)).then(r=>r.json()).then(data=>{
    moveTarget.innerHTML = '';
    data.forEach(d=>{ const o = document.createElement('option'); o.value=d; o.textContent=d; moveTarget.appendChild(o); });
  });
}

moveTarget.onchange = ()=>{
  if(selectedSet.size===0){ alert('请先选择要移动的项'); return; }
  const target = moveTarget.value;
  if(!confirm('将 '+selectedSet.size+' 项移动到 '+target+' ?')) return;
  fetch('/api/move', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({target: target, items: Array.from(selectedSet)})})
    .then(r=>{ if(!r.ok) r.text().then(t=>alert('移动失败:'+t)); else { selectedSet.clear(); refresh(); refreshTargets(); refreshShares(); } });
};

// 分享管理
function refreshShares(){
  fetch('/api/shares').then(r=>r.json()).then(data=>{
    sharesEl.innerHTML = '';
    data.forEach(s=>{
      const div = document.createElement('div');
      div.className = 'mb-2';
      const url = window.location.origin + '/s/' + s.id;
      div.innerHTML = `<div><strong>${s.path}</strong> → <a href="${url}" target="_blank">${url}</a>
        <button class="btn btn-sm btn-danger revoke-btn" data-id="${s.id}">撤销</button></div>`;
      sharesEl.appendChild(div);
    });
    document.querySelectorAll('.revoke-btn').forEach(b=>{
      b.onclick = ()=> {
        const id = b.dataset.id;
        fetch('/api/share/'+id, {method:'DELETE'}).then(r=>{ refreshShares(); });
      };
    });
  });
}

refresh(); refreshTargets(); refreshShares();
</script>
</body>
</html>
"""
# ---------- 路由与 API ----------
@app.route('/')
def index():
    return render_template_string(TEMPLATE, current_path='.')
@app.route('/list')
def api_list():
    path = request.args.get('path', '.')
    try:
        return jsonify(list_directory(path))
    except ValueError:
        abort(400, "非法路径")
@app.route('/api/list_all_dirs')
def api_list_all_dirs():
    try:
        base = request.args.get('path', '.')
        _ = safe_join_root(base)
    except Exception:
        abort(400, "非法路径")
    result = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        relative = os.path.relpath(dirpath, ROOT)
        normalized = relative.replace('\\','/') if relative != '.' else '.'
        result.append(normalized)
    return jsonify(sorted(result))
@app.route('/api/upload', methods=['POST'])
def api_upload():
    target = request.form.get('path', '.')
    try:
        destination = safe_join_root(target)
    except Exception:
        return jsonify({"success": False, "error": "非法路径"}), 400
    destination.mkdir(parents=True, exist_ok=True)
    files = request.files.getlist('file')
    saved_files = []
    for upload_file in files:
        filename = secure_filename(upload_file.filename)
        if not filename:
            continue
        if not allowed_file(filename):
            continue
        out_path = destination / filename
        if out_path.exists():
            stem = out_path.stem
            suffix = out_path.suffix
            counter = 1
            while True:
                candidate = destination / f"{stem} ({counter}){suffix}"
                if not candidate.exists():
                    out_path = candidate
                    break
                counter += 1
        upload_file.save(str(out_path))
        saved_files.append(str(out_path.relative_to(ROOT)))
    return jsonify({"success": True, "saved": saved_files})
@app.route('/download')
def download():
    path = request.args.get('path', '.')
    try:
        file_path = safe_join_root(path)
    except Exception:
        abort(400, "非法路径")
    if not file_path.exists():
        abort(404)
    if file_path.is_dir():
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_archive:
            for root_dir, dirnames, filenames in os.walk(file_path):
                for filename in filenames:
                    full = os.path.join(root_dir, filename)
                    arcname = os.path.relpath(full, start=file_path)
                    zip_archive.write(full, arcname)
        buffer.seek(0)
        download_name = (file_path.name or 'archive') + '.zip'
        return send_file(buffer, mimetype='application/zip', as_attachment=True, download_name=download_name)
    return send_file(str(file_path), as_attachment=True)
@app.route('/api/mkdir', methods=['POST'])
def api_mkdir():
    data = request.get_json() or {}
    path = data.get('path')
    try:
        dir_path = safe_join_root(path)
    except Exception:
        abort(400, "非法路径")
    try:
        dir_path.mkdir(parents=True, exist_ok=False)
        return ('', 204)
    except FileExistsError:
        return ('已存在', 409)
    except Exception as exc:
        return (str(exc), 500)
@app.route('/api/delete', methods=['POST'])
def api_delete():
    data = request.get_json() or {}
    path = data.get('path')
    try:
        target_path = safe_join_root(path)
    except Exception:
        abort(400, "非法路径")
    if not target_path.exists():
        return ('不存在', 404)
    try:
        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()
        return ('', 204)
    except Exception as exc:
        return (str(exc), 500)
@app.route('/api/move', methods=['POST'])
def api_move():
    data = request.get_json() or {}
    target = data.get('target')
    items = data.get('items', [])
    try:
        destination = safe_join_root(target)
    except Exception:
        abort(400, "非法路径")
    if not destination.exists():
        return ('目标不存在', 400)
    for key in items:
        try:
            item_type, full = key.split('::', 1)
        except Exception:
            continue
        try:
            source_path = safe_join_root(full)
        except Exception:
            continue
        if not source_path.exists():
            continue
        target_path = destination / source_path.name
        if target_path.exists():
            stem = target_path.stem
            suffix = target_path.suffix
            counter = 1
            while True:
                candidate = destination / f"{stem} ({counter}){suffix}"
                if not candidate.exists():
                    target_path = candidate
                    break
                counter += 1
        try:
            shutil.move(str(source_path), str(target_path))
        except Exception as exc:
            return (str(exc), 500)
    return ('', 204)
@app.route('/api/share', methods=['POST'])
def api_share():
    data = request.get_json() or {}
    path = data.get('path')
    try:
        resolved = safe_join_root(path)
    except Exception:
        abort(400, "非法路径")
    if not resolved.exists():
        return ('目标不存在', 404)
    share_id = create_share(path)
    return jsonify({"share_id": share_id})
@app.route('/api/shares')
def api_shares():
    mapping = load_share_db()
    return jsonify([{"id": k, "path": v} for k, v in mapping.items()])
@app.route('/api/share/<share_id>', methods=['DELETE'])
def api_share_delete(share_id):
    mapping = load_share_db()
    if share_id in mapping:
        mapping.pop(share_id)
        save_share_db(mapping)
        return ('', 204)
    return ('不存在', 404)
@app.route('/s/<share_id>')
def shared_view(share_id):
    path = resolve_share(share_id)
    if not path:
        return ('分享不存在', 404)
    try:
        resolved_path = safe_join_root(path)
    except Exception:
        return ('非法路径', 400)
    if resolved_path.is_dir():
        items = list_directory(path)
        html = "<h3>共享目录: %s</h3><ul>" % (path,)
        for d in items['dirs']:
            html += '<li>📁 %s</li>' % d['name']
        for f in items['files']:
            download_url = url_for('download', path=path + '/' + f['name'], _external=True)
            html += '<li>📄 <a href="%s">%s</a></li>' % (download_url, f['name'])
        html += "</ul>"
        return html
    else:
        return redirect(url_for('download', path=path))
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
