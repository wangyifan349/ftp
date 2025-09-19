import os
import hashlib
from io import BytesIO
from flask import Flask, request, jsonify, render_template_string, send_file
from werkzeug.utils import secure_filename
from minio import Minio
from minio.error import S3Error

UPLOAD_FOLDER = "./uploads"
MINIO_BUCKET = "my-bucket"
MINIO_ENDPOINT = "play.min.io:9000"
MINIO_ACCESS_KEY = "YOUR_ACCESS_KEY"
MINIO_SECRET_KEY = "YOUR_SECRET_KEY"
MINIO_SECURE = False

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app = Flask(__name__, static_folder=None)
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE,
)
def ensure_bucket(bucket_name):
    try:
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
    except Exception:
        raise
def sha256_bytes(b: bytes):
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()
def obj_name_join(prefix, name):
    if not prefix:
        return name
    if not prefix.endswith("/"):
        prefix = prefix + "/"
    return prefix + name
INDEX_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>文件管理</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding: 20px; }
    #dropzone { border: 2px dashed #ced4da; border-radius: .5rem; padding: 20px; text-align: center; cursor: pointer; background: #f8f9fa; }
    .folder { cursor: pointer; }
    .file-item { display:flex; justify-content:space-between; align-items:center; padding:6px 8px; border-bottom:1px solid #f1f1f1; }
    .file-item:hover { background:#ffffff; }
    .muted { color:#6c757d; }
    .breadcrumb-item a { text-decoration: none; }
  </style>
</head>
<body>
<div class="container">
  <h1 class="mb-4">文件管理（单文件 app.py）</h1>

  <div class="row mb-3">
    <div class="col-md-8">
      <nav aria-label="breadcrumb">
        <ol class="breadcrumb" id="breadcrumb"></ol>
      </nav>
    </div>
    <div class="col-md-4 text-end">
      <button class="btn btn-outline-secondary me-2" id="refreshBtn">刷新</button>
      <button class="btn btn-danger" id="deleteSelectedBtn">删除选中</button>
    </div>
  </div>

  <div class="row mb-3">
    <div class="col-md-8">
      <div id="dropzone" class="mb-2">
        <strong id="dropText">点击或拖拽文件到此处上传（可多选）</strong>
        <div class="muted mt-2" id="curPrefixLabel"></div>
        <input type="file" id="fileInput" multiple style="display:none" />
      </div>
      <div class="mb-2">
        <button class="btn btn-primary" id="chooseBtn">选择文件</button>
        <button class="btn btn-success" id="uploadBtn">上传</button>
      </div>
      <div id="uploadStatus" class="mt-2"></div>
    </div>
    <div class="col-md-4">
      <div class="card">
        <div class="card-body">
          <h5 class="card-title">当前目录</h5>
          <div class="mb-2">
            <input class="form-control" id="prefixInput" placeholder="输入或编辑目录前缀，例如 folder/subfolder/" />
          </div>
          <div class="d-grid gap-2">
            <button class="btn btn-outline-primary" id="goPrefixBtn">进入目录</button>
            <button class="btn btn-outline-secondary" id="mkFolderBtn">新建空文件夹</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="row">
    <div class="col-md-12">
      <div class="list-group" id="listing"></div>
    </div>
  </div>
</div>

<div class="modal fade" id="moveModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <form class="modal-content" id="moveForm">
      <div class="modal-header">
        <h5 class="modal-title">移动/重命名</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label class="form-label">目标前缀（目录）</label>
          <input class="form-control" id="movePrefix" placeholder="例如 folder/ 或 folder/sub/">
        </div>
        <div class="mb-3">
          <label class="form-label">目标文件名（可选，空则保持原名）</label>
          <input class="form-control" id="moveName" placeholder="可留空">
        </div>
        <input type="hidden" id="moveSource">
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
        <button type="submit" class="btn btn-primary">确认移动</button>
      </div>
    </form>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
const listingEl = document.getElementById('listing');
const prefixInput = document.getElementById('prefixInput');
const curPrefixLabel = document.getElementById('curPrefixLabel');
const breadcrumb = document.getElementById('breadcrumb');
const fileInput = document.getElementById('fileInput');
const dropzone = document.getElementById('dropzone');
const chooseBtn = document.getElementById('chooseBtn');
const uploadBtn = document.getElementById('uploadBtn');
const refreshBtn = document.getElementById('refreshBtn');
const mkFolderBtn = document.getElementById('mkFolderBtn');
const goPrefixBtn = document.getElementById('goPrefixBtn');
const deleteSelectedBtn = document.getElementById('deleteSelectedBtn');
const uploadStatus = document.getElementById('uploadStatus');

const moveModal = new bootstrap.Modal(document.getElementById('moveModal'));
const moveForm = document.getElementById('moveForm');
const movePrefix = document.getElementById('movePrefix');
const moveName = document.getElementById('moveName');
const moveSource = document.getElementById('moveSource');

let currentPrefix = '';
let filesToUpload = [];

function api(path, opts){ return fetch(path, opts).then(r=>r.json()); }
function setStatus(msg, type='secondary'){ uploadStatus.innerHTML = '<div class="alert alert-'+type+' py-1">'+msg+'</div>'; }

dropzone.addEventListener('click', ()=> fileInput.click());
chooseBtn.addEventListener('click', ()=> fileInput.click());
fileInput.addEventListener('change', (e)=>{
  filesToUpload = Array.from(e.target.files);
  setStatus(filesToUpload.length + ' 个文件准备上传', 'info');
});

dropzone.addEventListener('dragover', (e)=>{ e.preventDefault(); dropzone.style.background = '#e9f7ef'; });
dropzone.addEventListener('dragleave', ()=>{ dropzone.style.background = '#f8f9fa'; });
dropzone.addEventListener('drop', (e)=>{
  e.preventDefault();
  dropzone.style.background = '#f8f9fa';
  filesToUpload = Array.from(e.dataTransfer.files);
  setStatus(filesToUpload.length + ' 个文件准备上传', 'info');
});

async function loadList(prefix=''){
  currentPrefix = prefix || '';
  prefixInput.value = currentPrefix;
  curPrefixLabel.textContent = '当前前缀: ' + (currentPrefix || '/ (根)');
  breadcrumb.innerHTML = '';
  const parts = currentPrefix ? currentPrefix.split('/').filter(Boolean) : [];
  const rootLi = document.createElement('li'); rootLi.className='breadcrumb-item';
  rootLi.innerHTML = '<a href="#" data-prefix="">根</a>'; breadcrumb.appendChild(rootLi);
  let accum = '';
  parts.forEach((p)=>{
    accum += p + '/';
    const li = document.createElement('li'); li.className = 'breadcrumb-item';
    li.innerHTML = '<a href="#" data-prefix="'+accum+'">'+p+'</a>';
    breadcrumb.appendChild(li);
  });
  Array.from(breadcrumb.querySelectorAll('a')).forEach(a=>{
    a.addEventListener('click', (e)=>{
      e.preventDefault();
      loadList(a.getAttribute('data-prefix'));
    });
  });

  const j = await api('/list?prefix=' + encodeURIComponent(currentPrefix));
  listingEl.innerHTML = '';
  if(j.prefixes && j.prefixes.length){
    j.prefixes.forEach(p=>{
      const name = p.replace(currentPrefix, '');
      const el = document.createElement('div');
      el.className = 'list-group-item';
      el.innerHTML = `<div class="d-flex w-100 justify-content-between align-items-center">
        <div>
          <input type="checkbox" class="form-check-input me-2 selchk" data-name="${p}">
          <span class="folder me-2">📁</span>
          <strong class="folder">${name}</strong>
        </div>
        <div>
          <button class="btn btn-sm btn-outline-secondary open-folder" data-prefix="${p}">打开</button>
        </div>
      </div>`;
      listingEl.appendChild(el);
    });
  }
  if(j.objects && j.objects.length){
    j.objects.forEach(o=>{
      const nameOnly = o.name.replace(currentPrefix, '');
      const el = document.createElement('div');
      el.className = 'list-group-item file-item';
      el.innerHTML = `<div class="d-flex align-items-center">
        <input type="checkbox" class="form-check-input me-2 selchk" data-name="${o.name}">
        <div>
          📄 <span class="ms-1">${nameOnly}</span><div class="muted small">${o.size ?? '—'} bytes</div>
        </div>
      </div>
      <div>
        <a class="btn btn-sm btn-outline-primary me-1" href="/download?object=${encodeURIComponent(o.name)}">下载</a>
        <button class="btn btn-sm btn-outline-secondary me-1 move-btn" data-name="${o.name}">移动</button>
        <button class="btn btn-sm btn-danger del-btn" data-name="${o.name}">删除</button>
      </div>`;
      listingEl.appendChild(el);
    });
  }
  Array.from(document.getElementsByClassName('open-folder')).forEach(b=>{
    b.onclick = ()=> loadList(b.getAttribute('data-prefix'));
  });
  Array.from(document.getElementsByClassName('del-btn')).forEach(b=>{
    b.onclick = async ()=>{
      const name = b.getAttribute('data-name');
      if(!confirm('删除 ' + name + ' ?')) return;
      const res = await api('/delete', {method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({object: name})});
      setStatus(JSON.stringify(res));
      loadList(currentPrefix);
    };
  });
  Array.from(document.getElementsByClassName('move-btn')).forEach(b=>{
    b.onclick = ()=>{
      const name = b.getAttribute('data-name');
      moveSource.value = name;
      movePrefix.value = currentPrefix;
      moveName.value = '';
      moveModal.show();
    };
  });
}

uploadBtn.addEventListener('click', async ()=>{
  if(!filesToUpload || filesToUpload.length === 0){ alert('请选择文件'); return; }
  const prefix = prefixInput.value || '';
  const form = new FormData();
  form.append('prefix', prefix);
  for(const f of filesToUpload){
    form.append('files', f, f.name);
  }
  setStatus('上传中...', 'info');
  const resp = await fetch('/upload', {method:'POST', body: form});
  const j = await resp.json();
  setStatus(JSON.stringify(j));
  filesToUpload = [];
  fileInput.value = '';
  loadList(prefix);
});

deleteSelectedBtn.addEventListener('click', async ()=>{
  const sels = Array.from(document.querySelectorAll('.selchk:checked')).map(el=>el.getAttribute('data-name'));
  if(sels.length === 0){ alert('未选中文件或文件夹'); return; }
  if(!confirm('删除选中 ' + sels.length + ' 项?')) return;
  const resp = await fetch('/delete_batch', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({objects: sels})});
  const j = await resp.json();
  setStatus(JSON.stringify(j));
  loadList(currentPrefix);
});

goPrefixBtn.addEventListener('click', ()=> {
  let p = prefixInput.value || '';
  if(p && !p.endsWith('/')) p = p + '/';
  loadList(p);
});

mkFolderBtn.addEventListener('click', async ()=>{
  let p = prefixInput.value || '';
  if(!p){ alert('请输入目录名称'); return; }
  if(!p.endsWith('/')) p = p + '/';
  const name = p;
  const resp = await fetch('/mkfolder', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({folder: name})});
  const j = await resp.json();
  setStatus(JSON.stringify(j));
  loadList(currentPrefix);
});

moveForm.addEventListener('submit', async (e)=>{
  e.preventDefault();
  const src = moveSource.value;
  let tgtPref = movePrefix.value || '';
  if(tgtPref && !tgtPref.endsWith('/')) tgtPref = tgtPref + '/';
  let tgtName = moveName.value ? moveName.value : src.split('/').pop();
  const target = tgtPref + tgtName;
  const resp = await fetch('/move', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({source: src, target: target})});
  const j = await resp.json();
  setStatus(JSON.stringify(j));
  moveModal.hide();
  loadList(currentPrefix);
});

loadList('');
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)
@app.route("/upload", methods=["POST"])
def upload():
    ensure_bucket(MINIO_BUCKET)
    prefix = request.form.get('prefix', '') or ''
    if prefix and not prefix.endswith('/'):
        prefix = prefix + '/'
    files = request.files.getlist('files')
    if not files:
        return jsonify({"error": "no files"}), 400
    results = []
    for f in files:
        filename = secure_filename(f.filename)
        if not filename:
            results.append({"file": None, "error": "invalid filename"})
            continue
        obj = obj_name_join(prefix, filename)
        data = f.read()
        try:
            bio = BytesIO(data)
            minio_client.put_object(
                MINIO_BUCKET, obj, data=bio, length=len(data), part_size=10*1024*1024
            )
            results.append({"file": filename, "object": obj, "sha256": sha256_bytes(data)})
        except Exception as e:
            results.append({"file": filename, "error": str(e)})
    return jsonify({"results": results})
@app.route("/download")
def download():
    obj = request.args.get('object')
    if not obj:
        return jsonify({"error": "missing object param"}), 400
    try:
        resp = minio_client.get_object(MINIO_BUCKET, obj)
    except S3Error as e:
        return jsonify({"error": "not found", "detail": str(e)}), 404
    except Exception as e:
        return jsonify({"error": "get failed", "detail": str(e)}), 500
    data = resp.read()
    resp.close()
    resp.release_conn()
    return send_file(BytesIO(data), as_attachment=True, download_name=os.path.basename(obj))
@app.route("/list")
def list_objects():
    prefix = request.args.get('prefix', '') or ''
    if prefix and not prefix.endswith('/'):
        prefix = prefix + '/'
    try:
        objs = minio_client.list_objects(MINIO_BUCKET, prefix=prefix, recursive=False, delimiter='/')
    except Exception as e:
        return jsonify({"error": "list failed", "detail": str(e)}), 500
    prefixes = []
    objects = []
    for o in objs:
        if hasattr(o, 'prefix') and o.prefix:
            prefixes.append(o.prefix)
        elif hasattr(o, 'object_name') and o.object_name:
            objects.append({"name": o.object_name, "size": getattr(o, "size", None)})
        else:
            s = str(o)
            if s.endswith('/'):
                prefixes.append(s)
            else:
                objects.append({"name": s})
    return jsonify({"prefixes": prefixes, "objects": objects})
@app.route("/delete", methods=["POST"])
def delete():
    data = request.get_json()
    if not data or 'object' not in data:
        return jsonify({"error": "missing object"}), 400
    obj = data['object']
    try:
        minio_client.remove_object(MINIO_BUCKET, obj)
        return jsonify({"msg": "deleted", "object": obj})
    except S3Error as e:
        return jsonify({"error": "delete failed", "detail": str(e)}), 404
    except Exception as e:
        return jsonify({"error": "delete failed", "detail": str(e)}), 500
@app.route("/delete_batch", methods=["POST"])
def delete_batch():
    data = request.get_json()
    if not data or 'objects' not in data:
        return jsonify({"error": "missing objects"}), 400
    objs = data['objects']
    results = {"deleted": [], "errors": []}
    for o in objs:
        try:
            minio_client.remove_object(MINIO_BUCKET, o)
            results['deleted'].append(o)
        except Exception as e:
            results['errors'].append({"object": o, "error": str(e)})
    return jsonify(results)
@app.route("/mkfolder", methods=["POST"])
def mkfolder():
    data = request.get_json()
    if not data or 'folder' not in data:
        return jsonify({"error": "missing folder"}), 400
    folder = data['folder']
    if not folder.endswith('/'):
        folder = folder + '/'
    try:
        minio_client.put_object(MINIO_BUCKET, folder, data=BytesIO(b''), length=0)
        return jsonify({"msg": "folder created", "folder": folder})
    except Exception as e:
        return jsonify({"error": "create folder failed", "detail": str(e)}), 500
@app.route("/move", methods=["POST"])
def move():
    data = request.get_json()
    if not data or 'source' not in data or 'target' not in data:
        return jsonify({"error": "missing source/target"}), 400
    src = data['source']
    tgt = data['target']
    try:
        copy_src = {"Bucket": MINIO_BUCKET, "Object": src}
        minio_client.copy_object(MINIO_BUCKET, tgt, copy_src)
        minio_client.remove_object(MINIO_BUCKET, src)
        return jsonify({"msg": "moved", "source": src, "target": tgt})
    except Exception as e:
        return jsonify({"error": "move failed", "detail": str(e)}), 500
if __name__ == "__main__":
    try:
        ensure_bucket(MINIO_BUCKET)
    except Exception:
        pass
    app.run(host="0.0.0.0", port=5000, debug=True)
