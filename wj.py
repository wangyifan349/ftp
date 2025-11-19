import os
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, Response
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_ROOT = BASE_DIR / "uploads"
UPLOAD_ROOT.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4GB

# ---------- 辅助 ----------
def error_json(msg, code=400):
    return jsonify({"error": msg}), code

def safe_join_root(rel_path: str) -> Path:
    rel = (rel_path or "").strip().replace("\\", "/")
    target = (UPLOAD_ROOT / rel).resolve()
    if not str(target).startswith(str(UPLOAD_ROOT.resolve())):
        raise ValueError("非法路径")
    return target

def list_directory(rel_path: str = ""):
    root = safe_join_root(rel_path)
    if not root.exists():
        return None, "路径不存在"
    items = []
    for p in sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        stat = p.stat()
        items.append({
            "name": p.name,
            "is_dir": p.is_dir(),
            "size": stat.st_size if p.is_file() else None,
            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return items, None

# ---------- 前端 ----------
INDEX_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>云文件管理</title>
<style>body{font-family:Arial;margin:20px}.path{margin-bottom:10px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px}th{background:#f4f4f4}</style>
</head><body>
<h2>云文件管理（示例）</h2>
<div class="path">当前路径: <span id="curpath">/</span> <button id="upBtn">上一级</button></div>
<form id="uploadForm"><input type="file" id="fileInput" name="files" multiple> <button>上传</button></form>
<div style="margin-top:10px"><input id="newFolderName" placeholder="新建文件夹名称"><button id="mkdirBtn">新建文件夹</button></div>
<table id="fileTable" style="margin-top:12px"><thead><tr><th>名称</th><th>类型</th><th>大小</th><th>修改时间</th><th>操作</th></tr></thead><tbody></tbody></table>
<script>
let curPath='';const curPathEl=document.getElementById('curpath'),tbody=document.querySelector('#fileTable tbody');
function setPath(p){curPath=p||'';curPathEl.textContent='/'+curPath;if(curPath.endsWith('/'))curPath=curPath.slice(0,-1);loadList();}
function loadList(){fetch('/api/list?path='+encodeURIComponent(curPath)).then(r=>r.json()).then(d=>{tbody.innerHTML='';if(d.error){alert(d.error);return;}d.items.forEach(it=>{const tr=document.createElement('tr');const nameTd=document.createElement('td');nameTd.textContent=it.name;const typeTd=document.createElement('td');typeTd.textContent=it.is_dir?'目录':'文件';const sizeTd=document.createElement('td');sizeTd.textContent=it.is_dir?'-':it.size;const mtd=document.createElement('td');mtd.textContent=it.mtime;const actTd=document.createElement('td');if(it.is_dir){const open=document.createElement('button');open.textContent='进入';open.onclick=()=>setPath((curPath?curPath+'/':'')+it.name);actTd.appendChild(open);}else{const dl=document.createElement('button');dl.textContent='下载';dl.onclick=()=>location.href='/api/download?path='+encodeURIComponent(curPath)+'&filename='+encodeURIComponent(it.name);actTd.appendChild(dl);}const del=document.createElement('button');del.textContent='删除';del.onclick=()=>doDelete(it.name);actTd.appendChild(del);const rn=document.createElement('button');rn.textContent='重命名';rn.onclick=()=>doRename(it.name);actTd.appendChild(rn);tr.appendChild(nameTd);tr.appendChild(typeTd);tr.appendChild(sizeTd);tr.appendChild(mtd);tr.appendChild(actTd);tbody.appendChild(tr);});}).catch(e=>alert('加载失败:'+e));}
document.getElementById('uploadForm').addEventListener('submit',e=>{e.preventDefault();const files=document.getElementById('fileInput').files; if(!files.length) return alert('请选择文件'); const fd=new FormData(); for(let i=0;i<files.length;i++) fd.append('files',files[i]); fd.append('path',curPath); fetch('/api/upload',{method:'POST',body:fd}).then(r=>r.json()).then(j=>{ if(j.error) alert(j.error); else { alert('上传成功: '+(j.saved||[]).join(',')); loadList(); }}).catch(e=>alert('上传失败:'+e));});
document.getElementById('mkdirBtn').addEventListener('click',()=>{const name=document.getElementById('newFolderName').value.trim(); if(!name) return alert('请输入名称'); fetch('/api/mkdir',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:curPath,name})}).then(r=>r.json()).then(j=>{ if(j.error) alert(j.error); else { alert('创建成功'); document.getElementById('newFolderName').value=''; loadList(); } }).catch(e=>alert('创建失败:'+e));});
document.getElementById('upBtn').addEventListener('click',()=>{ if(!curPath) return; const parts=curPath.split('/'); parts.pop(); setPath(parts.join('/')); });
function doDelete(name){ if(!confirm('确定删除 "'+name+'"?')) return; fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:curPath,name})}).then(r=>r.json()).then(j=>{ if(j.error) alert(j.error); else { alert('已删除'); loadList(); } }).catch(e=>alert('删除失败:'+e));}
function doRename(oldName){ const newName=prompt('新名称:',oldName); if(!newName) return; fetch('/api/rename',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:curPath,old:oldName,new:newName})}).then(r=>r.json()).then(j=>{ if(j.error) alert(j.error); else { alert('重命名成功'); loadList(); } }).catch(e=>alert('重命名失败:'+e));}
setPath('');
</script></body></html>
"""

# ---------- 路由 ----------
@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")

@app.route("/api/list")
def api_list():
    rel = request.args.get("path", "") or ""
    items, err = list_directory(rel)
    return error_json(err, 404) if err else jsonify({"path": rel, "items": items})

@app.route("/api/upload", methods=["POST"])
def api_upload():
    rel = request.form.get("path", "") or ""
    try:
        dest = safe_join_root(rel)
    except ValueError as e:
        return error_json(str(e), 400)
    dest.mkdir(parents=True, exist_ok=True)

    files = request.files.getlist("files")
    if not files:
        return error_json("没有上传文件", 400)

    saved = []
    for f in files:
        fname = secure_filename(f.filename)
        if not fname:
            continue
        target = dest / fname
        base, ext = os.path.splitext(fname)
        i = 1
        while target.exists():
            fname = f"{base}({i}){ext}"
            target = dest / fname
            i += 1
        try:
            f.save(str(target))
        except Exception as e:
            return error_json(f"保存失败: {e}", 500)
        saved.append(fname)
    return jsonify({"saved": saved})

@app.route("/api/download")
def api_download():
    rel = request.args.get("path", "") or ""
    filename = request.args.get("filename")
    if not filename:
        return error_json("filename 必需", 400)
    try:
        dirp = safe_join_root(rel)
    except ValueError as e:
        return error_json(str(e), 400)
    filep = dirp / filename
    if not filep.exists() or not filep.is_file():
        return error_json("文件不存在", 404)
    return send_from_directory(str(dirp), filename, as_attachment=True)

@app.route("/api/delete", methods=["POST"])
def api_delete():
    data = request.get_json() or {}
    rel = data.get("path", "") or ""
    name = data.get("name")
    if not name:
        return error_json("name 必需", 400)
    try:
        dirp = safe_join_root(rel)
    except ValueError as e:
        return error_json(str(e), 400)
    target = dirp / name
    if not target.exists():
        return error_json("目标不存在", 404)
    if target.is_dir():
        if any(target.iterdir()):
            return error_json("目录非空，先删除子项", 400)
        target.rmdir()
    else:
        target.unlink()
    return jsonify({"deleted": name})

@app.route("/api/mkdir", methods=["POST"])
def api_mkdir():
    data = request.get_json() or {}
    rel = data.get("path", "") or ""
    name = data.get("name")
    if not name:
        return error_json("name 必需", 400)
    name = secure_filename(name)
    try:
        parent = safe_join_root(rel)
    except ValueError as e:
        return error_json(str(e), 400)
    newdir = parent / name
    if newdir.exists():
        return error_json("目标已存在", 400)
    newdir.mkdir(parents=True, exist_ok=False)
    return jsonify({"created": str(newdir.relative_to(UPLOAD_ROOT))})

@app.route("/api/rename", methods=["POST"])
def api_rename():
    data = request.get_json() or {}
    rel = data.get("path", "") or ""
    old = data.get("old"); new = data.get("new")
    if not old or not new:
        return error_json("old 和 new 都必需", 400)
    new = secure_filename(new)
    try:
        parent = safe_join_root(rel)
    except ValueError as e:
        return error_json(str(e), 400)
    oldp = parent / old; newp = parent / new
    if not oldp.exists():
        return error_json("旧目标不存在", 404)
    if newp.exists():
        return error_json("新目标已存在", 400)
    oldp.rename(newp)
    return jsonify({"renamed": {"from": old, "to": new}})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
