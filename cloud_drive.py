#!/usr/bin/env python3
# cloud_drive.py
# 改进版单文件 Flask 云盘（支持多文件上传、下载、列出层级目录、删除、重命名、拖拽移动）
# 前端使用 Bootstrap，AJAX + 拖拽上传和拖拽移动
# 运行前：pip install flask

import os
import shutil
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Tuple, List, Optional
from flask import (
    Flask, request, jsonify, send_file, render_template_string, abort
)
from werkzeug.utils import secure_filename

# ---------- 配置 ----------
APP_ROOT = Path(__file__).resolve().parent
STORAGE_ROOT = APP_ROOT / "storage"
MAX_UPLOAD_SIZE = 1024 * 1024 * 1024  # 1GB
ALLOWED_EXT = None  # None 表示允许所有类型；或设为 {'jpg','png','txt'}
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE
# ---------- 辅助函数（命名更语义化） ----------
def filename_allowed(filename: str) -> bool:
    if not filename:
        return False
    if "/" in filename or "\\" in filename:
        return False
    if ALLOWED_EXT is None:
        return True
    return filename.rsplit(".", 1)[-1].lower() in ALLOWED_EXT
def resolve_safe_path(relative_path: str, *, must_exist: bool = False) -> Path:
    """
    将用户输入的相对于 storage 的路径解析为绝对路径并校验在 STORAGE_ROOT 下。
    relative_path: '' 或 'a/b' 或 URL encoded。
    must_exist: 若为 True，则目标必须存在，否则抛出 ValueError。
    返回 Path。
    """
    if relative_path is None:
        relative_path = ''
    # 解码 URL 编码，消除前后空格
    relative_path = urllib.parse.unquote(relative_path).strip()
    # 阻止绝对路径
    rel = Path(relative_path)
    if rel.is_absolute():
        # 转为相对
        try:
            rel = rel.relative_to(rel.anchor)
        except Exception:
            rel = Path(str(rel)).name  # fallback
    candidate = (STORAGE_ROOT / rel).resolve()
    root_resolved = STORAGE_ROOT.resolve()
    if not str(candidate).startswith(str(root_resolved)):
        raise ValueError("非法路径（路径穿越检测失败）")
    if must_exist and not candidate.exists():
        raise ValueError("路径不存在")
    return candidate
def list_directory_items(relative_dir: str = "") -> Tuple[List[dict], Optional[str]]:
    """
    列出指定相对路径下的直接子项（不递归）。
    返回 (items, error_message)
    items: 每项 dict = {name, is_dir, size, mtime}
    """
    try:
        dir_path = resolve_safe_path(relative_dir, must_exist=True)
    except ValueError as e:
        return [], str(e)
    if not dir_path.is_dir():
        return [], "不是目录"
    items = []
    for entry in sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        stat = entry.stat()
        items.append({
            "name": entry.name,
            "is_dir": entry.is_dir(),
            "size": stat.st_size if entry.is_file() else 0,
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return items, None
# ---------- 前端页面（单页） ----------
INDEX_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Flask 云盘（改进）</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding: 20px; background:#f8f9fa; }
    .app-card { background:white; border-radius:8px; padding:20px; box-shadow:0 1px 6px rgba(0,0,0,0.06); }
    .folder { color:#0d6efd; font-weight:600; cursor:pointer; }
    .file { color:#212529; }
    .muted-sm { font-size:0.85rem; color:#6c757d; }
    .list-area { max-height:60vh; overflow:auto; border:1px dashed #e9ecef; border-radius:6px; padding:10px; background:#fff; }
    .drag-over { background: linear-gradient(90deg, rgba(13,110,253,0.03), rgba(13,110,253,0.01)); border-color:#0d6efd; }
    .item-row { display:flex; align-items:center; justify-content:space-between; padding:6px 8px; border-radius:6px; }
    .item-row.dragging { opacity:0.5; }
    .item-left { display:flex; align-items:center; gap:10px; }
    .actions { display:flex; gap:6px; }
    .breadcrumb-item + .breadcrumb-item::before { content: "›"; }
  </style>
</head>
<body>
<div class="container">
  <div class="app-card">
    <div class="d-flex justify-content-between align-items-start mb-3">
      <div>
        <h4>Flask 云盘（改进）</h4>
        <div class="muted-sm">支持多文件上传、拖拽移动、层级目录管理</div>
      </div>
      <div>
        <button class="btn btn-sm btn-outline-secondary" id="btnNewFolder">新建文件夹</button>
        <button class="btn btn-sm btn-outline-danger" id="btnDeleteSelected">删除选中</button>
      </div>
    </div>

    <nav aria-label="breadcrumb" class="mb-2">
      <ol class="breadcrumb" id="breadcrumb"></ol>
    </nav>

    <div class="d-flex mb-3 gap-2">
      <div class="flex-grow-1">
        <div class="input-group">
          <input class="form-control" type="file" id="fileInput" multiple>
          <button class="btn btn-primary" id="btnUpload">上传</button>
        </div>
        <div class="muted-sm mt-1">当前目录：<span id="currentPathDisplay">/</span></div>
      </div>
      <div style="width:220px;">
        <input class="form-control form-control-sm" placeholder="筛选 (文件名)" id="filterInput">
      </div>
    </div>

    <div class="list-area" id="listArea">
      <div class="text-center text-muted p-3" id="listPlaceholder">加载中…</div>
    </div>

    <!-- 模态：重命名 -->
    <div class="modal" tabindex="-1" id="modalRename">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header"><h5 class="modal-title">重命名</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
          <div class="modal-body">
            <input id="inputRename" class="form-control" />
            <input type="hidden" id="inputRenameOld" />
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
            <button class="btn btn-primary" id="btnRenameConfirm">确认</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 模态：新建文件夹 -->
    <div class="modal" tabindex="-1" id="modalNewFolder">
      <div class="modal-dialog"><div class="modal-content">
        <div class="modal-header"><h5 class="modal-title">新建文件夹</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
        <div class="modal-body"><input id="inputNewFolder" class="form-control" placeholder="文件夹名称"></div>
        <div class="modal-footer"><button class="btn btn-secondary" data-bs-dismiss="modal">取消</button><button class="btn btn-primary" id="btnCreateFolder">创建</button></div>
      </div></div>
    </div>

  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
const listArea = document.getElementById('listArea');
const breadcrumb = document.getElementById('breadcrumb');
const fileInput = document.getElementById('fileInput');
const btnUpload = document.getElementById('btnUpload');
const currentPathDisplay = document.getElementById('currentPathDisplay');
const modalRename = new bootstrap.Modal(document.getElementById('modalRename'));
const modalNewFolder = new bootstrap.Modal(document.getElementById('modalNewFolder'));
const inputRename = document.getElementById('inputRename');
const inputRenameOld = document.getElementById('inputRenameOld');
const btnRenameConfirm = document.getElementById('btnRenameConfirm');
const btnNewFolder = document.getElementById('btnNewFolder');
const btnCreateFolder = document.getElementById('btnCreateFolder');
const inputNewFolder = document.getElementById('inputNewFolder');
const btnDeleteSelected = document.getElementById('btnDeleteSelected');
const filterInput = document.getElementById('filterInput');

let currentPath = ''; // 空表示根目录
let itemsCache = []; // 当前目录项缓存，用于过滤
let dragSrcElement = null; // 拖拽来源元素数据
let draggingItemName = null;
let draggingIsDir = false;

// Utility
function encodePath(p){ return encodeURIComponent(p || ''); }
function humanSize(size){ if(size===0) return '0 B'; const i=Math.floor(Math.log(size)/Math.log(1024)); const u=['B','KB','MB','GB','TB']; return (size/Math.pow(1024,i)).toFixed(i?2:0)+' '+u[i]; }

// 路径与面包屑
function setPath(p){
  currentPath = p || '';
  currentPathDisplay.textContent = '/' + decodeURIComponent(currentPath);
  renderBreadcrumb();
  loadList();
}

function renderBreadcrumb(){
  const parts = currentPath === '' ? [] : currentPath.split('/').filter(Boolean);
  breadcrumb.innerHTML = '';
  const root = document.createElement('li');
  root.className = 'breadcrumb-item';
  root.innerHTML = '<a href="#" data-path="">根目录</a>';
  breadcrumb.appendChild(root);
  let accum = '';
  parts.forEach((part)=>{
    accum = accum === '' ? part : accum + '/' + part;
    const li = document.createElement('li');
    li.className = 'breadcrumb-item';
    li.innerHTML = `<a href="#" data-path="${encodeURIComponent(accum)}">${part}</a>`;
    breadcrumb.appendChild(li);
  });
  [...breadcrumb.querySelectorAll('a')].forEach(a=>{
    a.onclick = (e)=>{ e.preventDefault(); const p = a.getAttribute('data-path')||''; setPath(decodeURIComponent(p)); }
  });
}

// 加载目录
async function loadList(){
  listArea.classList.remove('drag-over');
  listArea.innerHTML = '<div class="text-center text-muted p-3">加载中…</div>';
  try{
    const res = await fetch('/api/list?path=' + encodePath(currentPath));
    const j = await res.json();
    if(!j.success){ listArea.innerHTML = '<div class="text-danger p-3">'+(j.message||'加载失败')+'</div>'; return; }
    itemsCache = j.items;
    renderList(j.items);
  }catch(e){
    listArea.innerHTML = '<div class="text-danger p-3">加载出错</div>';
  }
}

function renderList(items){
  const filter = filterInput.value.trim().toLowerCase();
  const filtered = items.filter(it => it.name.toLowerCase().includes(filter));
  if(filtered.length === 0){ listArea.innerHTML = '<div class="p-3 text-muted">空目录</div>'; return; }
  listArea.innerHTML = '';
  filtered.forEach(it=>{
    const row = document.createElement('div');
    row.className = 'item-row';
    row.setAttribute('draggable', 'true');
    row.dataset.name = it.name;
    row.dataset.isDir = it.is_dir ? '1' : '0';

    const left = document.createElement('div'); left.className='item-left';
    left.innerHTML = `
      <div><input type="checkbox" class="select-checkbox"></div>
      <div class="${it.is_dir ? 'folder' : 'file'}" title="${it.name}">${it.name}</div>
      <div class="muted-sm">${it.is_dir ? '文件夹' : humanSize(it.size)} • ${it.mtime}</div>
    `;
    const actions = document.createElement('div'); actions.className='actions';
    if(!it.is_dir){
      const aDown = document.createElement('a'); aDown.className='btn btn-sm btn-outline-primary'; aDown.textContent='下载';
      aDown.href = `/api/download?path=${encodePath(currentPath)}&name=${encodeURIComponent(it.name)}`;
      actions.appendChild(aDown);
    } else {
      const btnOpen = document.createElement('button'); btnOpen.className='btn btn-sm btn-outline-secondary'; btnOpen.textContent='打开';
      btnOpen.onclick = ()=>{ const next = currentPath === '' ? it.name : currentPath + '/' + it.name; setPath(next); };
      actions.appendChild(btnOpen);
    }
    const btnRename = document.createElement('button'); btnRename.className='btn btn-sm btn-outline-warning'; btnRename.textContent='重命名';
    btnRename.onclick = ()=>{ inputRenameOld.value = it.name; inputRename.value = it.name; modalRename.show(); };
    const btnDel = document.createElement('button'); btnDel.className='btn btn-sm btn-outline-danger'; btnDel.textContent='删除';
    btnDel.onclick = async ()=>{
      if(!confirm('确认删除：' + it.name + ' ?')) return;
      const res = await fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:currentPath,name:it.name})});
      const j = await res.json();
      if(j.success) loadList(); else alert('删除失败：' + (j.message||''));
    };
    actions.appendChild(btnRename);
    actions.appendChild(btnDel);

    row.appendChild(left);
    row.appendChild(actions);
    listArea.appendChild(row);

    // 拖拽事件（用于移动）
    row.addEventListener('dragstart', (e)=>{
      dragSrcElement = row;
      draggingItemName = it.name;
      draggingIsDir = it.is_dir;
      row.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      // 存放基本信息
      e.dataTransfer.setData('text/plain', JSON.stringify({name: it.name, is_dir: !!it.is_dir}));
    });
    row.addEventListener('dragend', ()=>{ if(dragSrcElement) dragSrcElement.classList.remove('dragging'); dragSrcElement=null; draggingItemName=null; draggingIsDir=false; });

    // 如果当前行是目录，则允许将其他项拖入以移动到该目录
    if(it.is_dir){
      row.addEventListener('dragover', (e)=>{ e.preventDefault(); e.dataTransfer.dropEffect='move'; row.classList.add('drag-over'); });
      row.addEventListener('dragleave', ()=>{ row.classList.remove('drag-over'); });
      row.addEventListener('drop', async (e)=>{
        e.preventDefault();
        row.classList.remove('drag-over');
        const dt = e.dataTransfer.getData('text/plain');
        let payload;
        try{ payload = JSON.parse(dt); }catch(err){ return; }
        const srcName = payload.name;
        const destDirName = it.name;
        // 目标路径 = currentPath + '/' + destDirName
        const destPath = currentPath === '' ? destDirName : (currentPath + '/' + destDirName);
        // 调用后端移动接口（move）
        const res = await fetch('/api/move', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({src_path: currentPath, name: srcName, dest_dir: destPath})
        });
        const j = await res.json();
        if(j.success) loadList(); else alert('移动失败：' + (j.message||''));
      });
    }
  });
}

// 拖拽到列表空白处直接上传
listArea.addEventListener('dragover', (e)=>{ e.preventDefault(); listArea.classList.add('drag-over'); e.dataTransfer.dropEffect='copy'; });
listArea.addEventListener('dragleave', ()=>{ listArea.classList.remove('drag-over'); });
listArea.addEventListener('drop', async (e)=>{
  e.preventDefault();
  listArea.classList.remove('drag-over');
  const dt = e.dataTransfer;
  if(dt.files && dt.files.length>0){
    // 上传文件
    const form = new FormData();
    for(let i=0;i<dt.files.length;i++) form.append('files', dt.files[i]);
    form.append('path', currentPath);
    await uploadFormData(form);
  } else {
    // 支持拖动来自同一页面的项到空白处——视为移动到当前目录（如果来源不是当前目录）
    try{
      const txt = dt.getData('text/plain');
      const obj = JSON.parse(txt);
      if(obj && obj.name){
        // assume src_path in dataTransfer? we pass current only, so perform move within same dir is no-op
      }
    }catch(err){}
  }
});

// 上传表单提交
btnUpload.onclick = async ()=>{
  if(!fileInput.files || fileInput.files.length === 0){ alert('请选择文件'); return; }
  const form = new FormData();
  for(let i=0;i<fileInput.files.length;i++) form.append('files', fileInput.files[i]);
  form.append('path', currentPath);
  await uploadFormData(form);
};

async function uploadFormData(form){
  try{
    const res = await fetch('/api/upload', { method:'POST', body: form });
    const j = await res.json();
    if(j.success){ fileInput.value=''; loadList(); } else { alert('上传失败：' + (j.message||'')); }
  }catch(e){ alert('上传出错'); }
}

// 重命名确认
btnRenameConfirm.onclick = async ()=>{
  const oldName = inputRenameOld.value;
  const newName = inputRename.value.trim();
  if(!newName){ alert('请输入新名称'); return; }
  const res = await fetch('/api/rename', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({path: currentPath, oldName, newName})
  });
  const j = await res.json();
  if(j.success){ modalRename.hide(); loadList(); } else { alert('重命名失败：' + (j.message||'')); }
};

// 新建文件夹
btnNewFolder.onclick = ()=> modalNewFolder.show();
btnCreateFolder.onclick = async ()=>{
  const name = inputNewFolder.value.trim();
  if(!name){ alert('请输入名称'); return; }
  const res = await fetch('/api/mkdir', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: currentPath, name}) });
  const j = await res.json();
  if(j.success){ modalNewFolder.hide(); inputNewFolder.value=''; loadList(); } else { alert('创建失败：' + (j.message||'')); }
};

// 删除选中
btnDeleteSelected.onclick = async ()=>{
  const checks = [...document.querySelectorAll('.select-checkbox')].filter(cb=>cb.checked);
  if(checks.length===0){ alert('未选择任何项'); return; }
  if(!confirm('确认删除所选项？')) return;
  const names = checks.map(cb=> cb.closest('.item-row').dataset.name );
  const res = await fetch('/api/delete-multi',{ method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path: currentPath, names}) });
  const j = await res.json();
  if(j.success) loadList(); else alert('删除失败：' + (j.message||''));
};

// 过滤
filterInput.addEventListener('input', ()=> renderList(itemsCache));

// 初始化
setPath(''); // 加载根目录

</script>
</body>
</html>
"""
# ---------- API 实现（更语义化的函数名与更严谨处理） ----------
@app.route("/")
def index():
    return render_template_string(INDEX_HTML)
@app.route("/api/list")
def api_list():
    rel = request.args.get('path', '') or ''
    try:
        items, err = list_directory_items(rel)
        if err:
            return jsonify(success=False, message=err)
        return jsonify(success=True, items=items)
    except Exception as e:
        return jsonify(success=False, message=str(e))
@app.route("/api/upload", methods=['POST'])
def api_upload():
    rel = request.form.get('path', '') or ''
    try:
        target_dir = resolve_safe_path(rel)
    except ValueError:
        return jsonify(success=False, message="非法路径")
    # 确保目录存在
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return jsonify(success=False, message="无法创建目录")
    files = request.files.getlist('files')
    if not files:
        return jsonify(success=False, message="未上传任何文件")
    saved = []
    for f in files:
        filename = secure_filename(f.filename)
        if filename == '':
            continue
        if not filename_allowed(filename):
            return jsonify(success=False, message=f"不允许的文件名：{filename}")
        dest = target_dir / filename
        try:
            f.save(str(dest))
            saved.append(filename)
        except Exception as e:
            return jsonify(success=False, message=f"保存失败：{filename} -> {e}")
    return jsonify(success=True, saved=saved)
@app.route("/api/download")
def api_download():
    rel = request.args.get('path', '') or ''
    name = request.args.get('name', '')
    if not name:
        return abort(400)
    try:
        parent = resolve_safe_path(rel, must_exist=True)
        file_path = resolve_safe_path(str(Path(rel) / name), must_exist=True)
    except ValueError:
        return abort(400)
    if not file_path.exists() or not file_path.is_file():
        return abort(404)
    return send_file(str(file_path), as_attachment=True, download_name=file_path.name)
@app.route("/api/delete", methods=['POST'])
def api_delete():
    data = request.get_json(force=True)
    rel = data.get('path', '') or ''
    name = data.get('name', '')
    if not name:
        return jsonify(success=False, message="缺少名称")
    try:
        parent = resolve_safe_path(rel, must_exist=True)
        target = resolve_safe_path(str(Path(rel) / name), must_exist=True)
    except ValueError as e:
        return jsonify(success=False, message=str(e))
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, message=str(e))
@app.route("/api/delete-multi", methods=['POST'])
def api_delete_multi():
    data = request.get_json(force=True)
    rel = data.get('path', '') or ''
    names = data.get('names') or []
    if not isinstance(names, list) or len(names) == 0:
        return jsonify(success=False, message="未提供要删除的名称列表")
    try:
        parent = resolve_safe_path(rel, must_exist=True)
    except ValueError as e:
        return jsonify(success=False, message=str(e))
    errors = []
    for name in names:
        try:
            target = resolve_safe_path(str(Path(rel) / name), must_exist=True)
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        except Exception as e:
            errors.append(f"{name}: {e}")
    if errors:
        return jsonify(success=False, message="; ".join(errors))
    return jsonify(success=True)
@app.route("/api/rename", methods=['POST'])
def api_rename():
    data = request.get_json(force=True)
    rel = data.get('path', '') or ''
    old_name = data.get('oldName') or data.get('old_name') or ''
    new_name = data.get('newName') or data.get('new_name') or ''
    if not old_name or not new_name:
        return jsonify(success=False, message="缺少旧/新名称")
    if "/" in new_name or "\\" in new_name:
        return jsonify(success=False, message="新名称不能包含路径分隔符")
    try:
        parent = resolve_safe_path(rel, must_exist=True)
        src = resolve_safe_path(str(Path(rel) / old_name), must_exist=True)
        dst = resolve_safe_path(str(Path(rel) / new_name))
    except ValueError as e:
        return jsonify(success=False, message=str(e))
    if dst.exists():
        return jsonify(success=False, message="目标名已存在")
    try:
        src.rename(dst)
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, message=str(e))
@app.route("/api/mkdir", methods=['POST'])
def api_mkdir():
    data = request.get_json(force=True)
    rel = data.get('path', '') or ''
    name = data.get('name', '')
    if not name:
        return jsonify(success=False, message="缺少名称")
    if "/" in name or "\\" in name:
        return jsonify(success=False, message="名称不能包含路径分隔符")
    try:
        parent = resolve_safe_path(rel, must_exist=True)
    except ValueError as e:
        return jsonify(success=False, message=str(e))
    new_dir = parent / name
    if new_dir.exists():
        return jsonify(success=False, message="已存在同名文件或目录")
    try:
        new_dir.mkdir(parents=False, exist_ok=False)
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, message=str(e))
@app.route("/api/move", methods=['POST'])
def api_move():
    """
    移动文件或目录到目标目录。
    请求 JSON:
    { src_path: '当前目录（相对）', name: '要移动的名字', dest_dir: '目标目录（相对 storage 根）' }
    """
    data = request.get_json(force=True)
    src_path = data.get('src_path', '') or ''
    name = data.get('name', '')
    dest_dir = data.get('dest_dir', '')
    if not name or dest_dir is None:
        return jsonify(success=False, message="参数缺失")
    # 解析路径
    try:
        src_parent = resolve_safe_path(src_path, must_exist=True)
        src = resolve_safe_path(str(Path(src_path) / name), must_exist=True)
        dest = resolve_safe_path(dest_dir)  # 目标目录可以不存在（创建）
    except ValueError as e:
        return jsonify(success=False, message=str(e))
    # 目标必须是目录（若不存在则创建）
    try:
        if not dest.exists():
            dest.mkdir(parents=True, exist_ok=True)
        if not dest.is_dir():
            return jsonify(success=False, message="目标不是目录")
    except Exception as e:
        return jsonify(success=False, message="无法准备目标目录: " + str(e))
    # 防止把目录移动到其自身子目录（例如 move a -> a/b）
    try:
        src_resolved = src.resolve()
        dest_resolved = (dest / src.name).resolve()
        if str(dest_resolved).startswith(str(src_resolved)):
            return jsonify(success=False, message="不能将目录移动到其子目录")
    except Exception:
        pass
    target_path = dest / src.name
    if target_path.exists():
        return jsonify(success=False, message="目标已存在同名项")
    try:
        shutil.move(str(src), str(target_path))
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, message=str(e))
@app.route("/storage/<path:subpath>")
def storage_proxy(subpath):
    # 可直接访问文件或列出目录（谨慎使用）
    try:
        target = resolve_safe_path(subpath, must_exist=True)
    except ValueError:
        return abort(400)
    if target.is_file():
        return send_file(str(target), as_attachment=True, download_name=target.name)
    if target.is_dir():
        items, err = list_directory_items(subpath)
        if err:
            return jsonify(success=False, message=err)
        return jsonify(success=True, items=items)
    return abort(404)
if __name__ == "__main__":
    print("Storage root:", STORAGE_ROOT)
    app.run(debug=True)
