import os
import shutil
from pathlib import Path
from urllib.parse import quote, unquote
from flask import Flask, request, send_file, jsonify, render_template_string, abort
from werkzeug.security import check_password_hash, generate_password_hash
from flask_httpauth import HTTPBasicAuth

app = Flask(__name__)
auth = HTTPBasicAuth()

BASE_DIRECTORY = Path(__file__).parent.resolve()
STORAGE_ROOT = BASE_DIRECTORY / "storage"
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1GB

USER_DATABASE = {
    "admin": generate_password_hash("password123"),
    "user": generate_password_hash("userpass")
}

@auth.verify_password
def verify_password(username, password):
    if username in USER_DATABASE and check_password_hash(USER_DATABASE.get(username), password):
        return username
    return None

def get_safe_path(relative_path: str) -> Path:
    relative_text = (relative_path or "").strip()
    relative_text = unquote(relative_text)
    if os.path.isabs(relative_text):
        raise ValueError("Absolute paths not allowed")
    candidate = (STORAGE_ROOT / relative_text).resolve()
    storage_resolved = STORAGE_ROOT.resolve()
    if not str(candidate).startswith(str(storage_resolved) + os.sep) and str(candidate) != str(storage_resolved):
        raise ValueError("Illegal path")
    return candidate

INDEX_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Simple Cloud Drive</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{max-width:1100px;margin:20px auto;}
    .item-row{align-items:center;padding:8px;border-bottom:1px solid #eee;}
    .upload-area{border:2px dashed #dee2e6;border-radius:6px;padding:16px;text-align:center;color:#6c757d;}
    .breadcrumb-item+.breadcrumb-item::before{content: "›"; padding: 0 6px; color:#6c757d;}
  </style>
</head>
<body>
<div class="container">
  <div class="d-flex justify-content-between align-items-center my-3">
    <h3>Simple Cloud Drive</h3>
    <div><small class="text-muted">User: {{ username }}</small></div>
  </div>

  <nav aria-label="breadcrumb">
    <ol class="breadcrumb" id="breadcrumb"></ol>
  </nav>

  <div class="mb-3 d-flex gap-2">
    <button class="btn btn-secondary" onclick="goUp()">Up</button>
    <input class="form-control form-control-sm w-50" type="text" id="newFolderName" placeholder="New folder name">
    <button class="btn btn-primary" onclick="createFolder()">Create Folder</button>
    <input type="file" id="fileInput" multiple class="form-control form-control-sm w-50">
    <button class="btn btn-success" onclick="uploadFiles()">Upload</button>
  </div>

  <div class="upload-area mb-3" id="uploadArea">Drag & Drop files here to upload</div>

  <div class="list-group" id="listContainer"></div>
</div>

<script>
let currentPath = "";

function renderBreadcrumb(){
  const breadcrumb = document.getElementById('breadcrumb');
  breadcrumb.innerHTML = '';
  const rootLi = document.createElement('li'); rootLi.className = 'breadcrumb-item';
  rootLi.innerHTML = '<a href="#" onclick="openPath(\\'\\')">root</a>';
  breadcrumb.appendChild(rootLi);
  if(!currentPath) return;
  const parts = currentPath.split('/').filter(Boolean);
  let accumulated = '';
  for(let i=0;i<parts.length;i++){
    accumulated = accumulated ? accumulated + '/' + parts[i] : parts[i];
    const li = document.createElement('li'); li.className='breadcrumb-item';
    li.innerHTML = '<a href="#" onclick="openPath(\\''+encodeURIComponent(accumulated)+'\\')">'+parts[i]+'</a>';
    breadcrumb.appendChild(li);
  }
}

function fetchList(){
  fetch('/api/list?path=' + encodeURIComponent(currentPath))
    .then(r=>r.json()).then(data=>{
      const container = document.getElementById('listContainer');
      container.innerHTML = '';
      if(data.err){ container.innerHTML = '<div class="alert alert-danger">'+data.err+'</div>'; return; }
      data.folders.forEach(folder=>{
        const div = document.createElement('div'); div.className='list-group-item d-flex item-row';
        const left = document.createElement('div'); left.className='d-flex gap-2 align-items-center flex-grow-1';
        left.innerHTML = '<span class="fs-5">📁</span><div>'+decodeURIComponent(folder)+'</div>';
        const right = document.createElement('div');
        right.innerHTML = '<button class="btn btn-sm btn-outline-primary me-1" onclick="openPath(\\''+encodeURIComponent((currentPath?currentPath+'/':'')+decodeURIComponent(folder))+'\\')">Open</button>' +
                          '<button class="btn btn-sm btn-outline-secondary me-1" onclick="renameItem(\\''+encodeURIComponent((currentPath?currentPath+'/':'')+decodeURIComponent(folder))+'\\')">Move/Rename</button>' +
                          '<button class="btn btn-sm btn-outline-danger" onclick="deleteItem(\\''+encodeURIComponent((currentPath?currentPath+'/':'')+decodeURIComponent(folder))+'\\', true)">Delete</button>';
        div.appendChild(left); div.appendChild(right); container.appendChild(div);
      });
      data.files.forEach(file=>{
        const div = document.createElement('div'); div.className='list-group-item d-flex item-row';
        const left = document.createElement('div'); left.className='d-flex gap-2 align-items-center flex-grow-1';
        left.innerHTML = '<span class="fs-5">📄</span><div><div>'+file.name+'</div></div>';
        const right = document.createElement('div');
        const filePath = encodeURIComponent(file.path);
        right.innerHTML = '<a class="btn btn-sm btn-outline-success me-1" href="/api/download?path='+filePath+'">Download</a>' +
                          '<button class="btn btn-sm btn-outline-secondary me-1" onclick="renameItem(\\''+filePath+'\\')">Move/Rename</button>' +
                          '<button class="btn btn-sm btn-outline-danger" onclick="deleteItem(\\''+filePath+'\\', false)">Delete</button>';
        div.appendChild(left); div.appendChild(right); container.appendChild(div);
      });
      renderBreadcrumb();
    });
}

function openPath(pathEnc){
  currentPath = decodeURIComponent(pathEnc || '');
  fetchList();
}

function goUp(){
  if(!currentPath) return;
  const parts = currentPath.split('/');
  parts.pop();
  currentPath = parts.filter(Boolean).join('/');
  fetchList();
}

function createFolder(){
  const name = document.getElementById('newFolderName').value.trim();
  if(!name){ alert('Please provide folder name'); return; }
  fetch('/api/mkdir', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({path: currentPath, name: name})
  }).then(r=>r.json()).then(res=>{
    if(res.ok){ document.getElementById('newFolderName').value=''; fetchList(); }
    else alert(res.err || 'Failed');
  });
}

function uploadFiles(){
  const input = document.getElementById('fileInput');
  if(!input.files.length){ alert('Select files to upload'); return; }
  const formData = new FormData();
  for(const file of input.files) formData.append('files', file);
  formData.append('path', currentPath);
  fetch('/api/upload', {method:'POST', body: formData})
    .then(r=>r.json()).then(res=>{ if(res.ok) { input.value=''; fetchList(); } else alert(res.err || 'Upload failed'); });
}

function deleteItem(pathEnc, isFolder){
  if(!confirm('Confirm delete?')) return;
  const path = decodeURIComponent(pathEnc);
  fetch('/api/delete', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({path: path, is_folder: isFolder})
  }).then(r=>r.json()).then(res=>{ if(res.ok) fetchList(); else alert(res.err || 'Delete failed'); });
}

function renameItem(pathEnc){
  const sourcePath = decodeURIComponent(pathEnc);
  const destination = prompt('Enter destination path relative to root (can include new name), e.g. "sub/target" or "newname":', sourcePath);
  if(!destination) return;
  fetch('/api/move', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({src: sourcePath, dst: destination})
  }).then(r=>r.json()).then(res=>{ if(res.ok) fetchList(); else alert(res.err || 'Move failed'); });
}

// Drag & drop
const uploadArea = document.getElementById('uploadArea');
uploadArea.addEventListener('dragover', e=>{ e.preventDefault(); uploadArea.classList.add('border-primary'); });
uploadArea.addEventListener('dragleave', e=>{ e.preventDefault(); uploadArea.classList.remove('border-primary'); });
uploadArea.addEventListener('drop', e=>{
  e.preventDefault(); uploadArea.classList.remove('border-primary');
  const files = Array.from(e.dataTransfer.files);
  if(!files.length) return;
  const formData = new FormData();
  for(const file of files) formData.append('files', file);
  formData.append('path', currentPath);
  fetch('/api/upload', {method:'POST', body: formData}).then(r=>r.json()).then(res=>{ if(res.ok) fetchList(); else alert(res.err || 'Upload failed'); });
});

fetchList();
</script>
</body>
</html>
"""

@app.route('/')
@auth.login_required
def index():
    return render_template_string(INDEX_TEMPLATE, username=auth.current_user())

@app.route('/api/list')
@auth.login_required
def api_list():
    try:
        relative_path = request.args.get('path', '') or ''
        directory_path = get_safe_path(relative_path)
        if not directory_path.exists():
            return jsonify({'err': 'Path not found', 'folders': [], 'files': []})
        if not directory_path.is_dir():
            return jsonify({'err': 'Not a directory', 'folders': [], 'files': []})
        folder_list = []
        file_list = []
        for child in sorted(directory_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.is_dir():
                folder_list.append(quote(child.name))
            else:
                relative_child = os.path.relpath(str(child), str(STORAGE_ROOT))
                file_list.append({'name': child.name, 'path': quote(relative_child)})
        return jsonify({'folders': folder_list, 'files': file_list})
    except Exception as exception:
        return jsonify({'err': str(exception), 'folders': [], 'files': []})

@app.route('/api/upload', methods=['POST'])
@auth.login_required
def api_upload():
    try:
        relative_path = request.form.get('path', '') or ''
        target_directory = get_safe_path(relative_path)
        if not target_directory.exists():
            target_directory.mkdir(parents=True, exist_ok=True)
        if not target_directory.is_dir():
            return jsonify({'err': 'Target is not a directory'})
        upload_files = request.files.getlist('files')
        if not upload_files:
            return jsonify({'err': 'No files uploaded'})
        for upload_file in upload_files:
            filename = upload_file.filename or 'unnamed'
            # Use only filename portion to avoid path traversal from client
            filename = Path(filename).name
            destination = target_directory / filename
            upload_file.save(str(destination))
        return jsonify({'ok': True})
    except Exception as exception:
        return jsonify({'err': str(exception)})

@app.route('/api/download')
@auth.login_required
def api_download():
    try:
        relative_path = request.args.get('path', '') or ''
        file_path = get_safe_path(relative_path)
        if not file_path.exists() or not file_path.is_file():
            return abort(404)
        # download_name supported in modern Flask; fallback handled by keyword name if needed by environment
        try:
            return send_file(str(file_path), as_attachment=True, download_name=file_path.name)
        except TypeError:
            # older Flask: attachment_filename
            return send_file(str(file_path), as_attachment=True, attachment_filename=file_path.name)
    except Exception:
        return abort(400)

@app.route('/api/delete', methods=['POST'])
@auth.login_required
def api_delete():
    try:
        request_data = request.get_json() or {}
        relative_path = request_data.get('path', '')
        target_path = get_safe_path(relative_path)
        if not target_path.exists():
            return jsonify({'err': 'Path not found'})
        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()
        return jsonify({'ok': True})
    except Exception as exception:
        return jsonify({'err': str(exception)})

@app.route('/api/mkdir', methods=['POST'])
@auth.login_required
def api_make_directory():
    try:
        request_data = request.get_json() or {}
        relative_path = request_data.get('path', '') or ''
        folder_name = (request_data.get('name') or '').strip()
        if not folder_name:
            return jsonify({'err': 'Name required'})
        parent_directory = get_safe_path(relative_path)
        if not parent_directory.exists():
            parent_directory.mkdir(parents=True, exist_ok=True)
        destination_directory = parent_directory / folder_name
        if destination_directory.exists():
            return jsonify({'err': 'Already exists'})
        destination_directory.mkdir(parents=True)
        return jsonify({'ok': True})
    except Exception as exception:
        return jsonify({'err': str(exception)})

@app.route('/api/move', methods=['POST'])
@auth.login_required
def api_move_item():
    try:
        request_data = request.get_json() or {}
        source_relative = request_data.get('src', '')
        destination_relative = request_data.get('dst', '')
        if not source_relative or not destination_relative:
            return jsonify({'err': 'Source and destination required'})
        source_path = get_safe_path(source_relative)
        destination_path = get_safe_path(destination_relative)

        if not source_path.exists():
            return jsonify({'err': 'Source not found'})

        if destination_path.exists() and destination_path.is_dir():
            final_destination = destination_path / source_path.name
        else:
            final_parent = destination_path.parent
            if not final_parent.exists():
                final_parent.mkdir(parents=True, exist_ok=True)
            final_destination = destination_path

        # Prevent moving into own subdirectory
        try:
            # Python 3.9+: use is_relative_to
            if final_destination.resolve().is_relative_to(source_path.resolve()):
                return jsonify({'err': 'Cannot move into its own subdirectory'})
        except Exception:
            # Fallback for older Python: compare via relative_to
            try:
                final_destination.resolve().relative_to(source_path.resolve())
                return jsonify({'err': 'Cannot move into its own subdirectory'})
            except Exception:
                pass

        shutil.move(str(source_path), str(final_destination))
        return jsonify({'ok': True})
    except Exception as exception:
        return jsonify({'err': str(exception)})

if __name__ == '__main__':
    app.run(debug=True)
