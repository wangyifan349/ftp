from flask import Flask, request, redirect, url_for, send_from_directory, render_template_string, flash, abort
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from pathlib import Path

# 配置
BASE_DIR = os.path.dirname(__file__)
UPLOAD_ROOT = os.path.join(BASE_DIR, 'uploads')  # 根目录，所有文件夹操作都在此根下
ALLOWED_EXTENSIONS = None  # 若需限制可设集合
MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200 MB
os.makedirs(UPLOAD_ROOT, exist_ok=True)

app = Flask(__name__)
app.config['UPLOAD_ROOT'] = UPLOAD_ROOT
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.secret_key = 'change-this-secret-for-production'

TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>层级文件管理</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      .file-icon { width:28px; text-align:center; }
      .folder-row:hover { background:#f8f9fa; }
      .small-muted { font-size:0.85rem; color:#6c757d; }
    </style>
  </head>
  <body class="bg-light">
    <div class="container py-4">
      <h1 class="mb-4">层级文件管理</h1>

      {% with messages = get_flashed_messages() %}
        {% if messages %}
          <div class="mb-3">
            {% for m in messages %}
              <div class="alert alert-info">{{ m }}</div>
            {% endfor %}
          </div>
        {% endif %}
      {% endwith %}

      <div class="mb-3 d-flex justify-content-between align-items-center">
        <div>
          <nav aria-label="breadcrumb">
            <ol class="breadcrumb mb-0">
              <li class="breadcrumb-item"><a href="{{ url_for('index') }}">root</a></li>
              {% for i, p in enumerate(breadcrumbs) %}
                {% if i == (breadcrumbs|length - 1) %}
                  <li class="breadcrumb-item active" aria-current="page">{{ p.name }}</li>
                {% else %}
                  <li class="breadcrumb-item"><a href="{{ url_for('index', path=p.path) }}">{{ p.name }}</a></li>
                {% endif %}
              {% endfor %}
            </ol>
          </nav>
        </div>
        <div class="small-muted">当前路径: <code>{{ display_path }}</code></div>
      </div>

      <div class="card mb-4">
        <div class="card-body">
          <form method="post" action="{{ url_for('upload', path=current_rel_path) }}" enctype="multipart/form-data" class="row g-3 align-items-center">
            <div class="col-auto">
              <input class="form-control" type="file" name="file" required>
            </div>
            <div class="col-auto">
              <button class="btn btn-primary" type="submit">上传到此目录</button>
            </div>
            <div class="col-auto">
              <input class="form-control" name="new_folder" placeholder="新建子文件夹（可选）">
            </div>
            <div class="col-auto">
              <button class="btn btn-outline-secondary" formaction="{{ url_for('mkdir', path=current_rel_path) }}" formmethod="post" type="submit">新建文件夹</button>
            </div>
            <div class="col-12">
              <div class="form-text">最大文件大小: {{ max_size_mb }} MB。</div>
            </div>
          </form>
        </div>
      </div>

      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <strong>目录列表</strong>
          <form class="d-flex" method="get" action="{{ url_for('index') }}">
            <input type="hidden" name="path" value="{{ current_rel_path }}">
            <input class="form-control form-control-sm me-2" type="search" name="q" placeholder="搜索文件/文件夹" value="{{ q|default('') }}">
            <button class="btn btn-sm btn-outline-secondary" type="submit">搜索</button>
          </form>
        </div>
        <div class="list-group list-group-flush">
          {% if parent_link %}
            <a class="list-group-item list-group-item-action folder-row" href="{{ parent_link }}">
              <div class="d-flex justify-content-between align-items-center">
                <div><span class="file-icon">⬆️</span> <strong>.. (上级目录)</strong></div>
                <div class="small-muted"></div>
              </div>
            </a>
          {% endif %}
          {% if dirs %}
            {% for d in dirs %}
              <div class="list-group-item d-flex justify-content-between align-items-center folder-row">
                <div>
                  <span class="file-icon">📁</span>
                  <a href="{{ url_for('index', path=d.rel_path) }}"><strong>{{ d.name }}</strong></a>
                  <div class="small-muted">子项: {{ d.count }} · 修改: {{ d.mtime }}</div>
                </div>
                <div class="btn-group">
                  <a class="btn btn-sm btn-outline-primary" href="{{ url_for('index', path=d.rel_path) }}">打开</a>
                  <form method="post" action="{{ url_for('rmdir', path=d.rel_path) }}" style="display:inline;">
                    <button class="btn btn-sm btn-outline-danger" type="submit" onclick="return confirm('确定删除文件夹 {{ d.name }}（仅允许删除空文件夹）吗？');">删除</button>
                  </form>
                </div>
              </div>
            {% endfor %}
          {% endif %}

          {% if files %}
            {% for f in files %}
              <div class="list-group-item d-flex justify-content-between align-items-center">
                <div>
                  <span class="file-icon">📄</span>
                  <strong>{{ f.name }}</strong>
                  <div class="small-muted">大小: {{ f.size_kb }} KB · 修改: {{ f.mtime }}</div>
                </div>
                <div class="btn-group">
                  <a class="btn btn-sm btn-outline-primary" href="{{ url_for('download', path=f.rel_path) }}">下载</a>
                  <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('preview', path=f.rel_path) }}" target="_blank">预览</a>
                  <form method="post" action="{{ url_for('delete', path=f.rel_path) }}" style="display:inline;">
                    <button class="btn btn-sm btn-outline-danger" type="submit" onclick="return confirm('确定删除 {{ f.name }} 吗？');">删除</button>
                  </form>
                </div>
              </div>
            {% endfor %}
          {% endif %}

          {% if not dirs and not files %}
            <div class="list-group-item">目录为空。</div>
          {% endif %}
        </div>
      </div>

      <footer class="mt-4 text-muted small">
        根目录: <code>{{ upload_root }}</code>
      </footer>
    </div>
  </body>
</html>
"""

# 辅助函数：安全地解析相对路径到上传根下，防止越界
def resolve_path(rel_path: str):
    # rel_path 期望为 Unix 风格相对路径，无前导斜杠
    if rel_path is None:
        rel_path = ''
    # 规范化
    rel_path = rel_path.strip().lstrip('/\\')
    target = os.path.normpath(os.path.join(app.config['UPLOAD_ROOT'], rel_path))
    # 确保目标在根目录下
    root = os.path.abspath(app.config['UPLOAD_ROOT'])
    target_abs = os.path.abspath(target)
    if not target_abs.startswith(root):
        raise ValueError('非法路径')
    return target_abs

def allowed_file(filename):
    if ALLOWED_EXTENSIONS is None:
        return True
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def file_info(path: str, rel_base: str):
    st = os.stat(path)
    size_kb = max(1, int(st.st_size / 1024))
    mtime = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    rel_path = os.path.relpath(path, app.config['UPLOAD_ROOT']).replace('\\', '/')
    return {'name': os.path.basename(path), 'size_kb': size_kb, 'mtime': mtime, 'rel_path': rel_path}

def dir_info(path: str):
    mtime = datetime.fromtimestamp(os.stat(path).st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    count = len([p for p in os.listdir(path)])
    rel_path = os.path.relpath(path, app.config['UPLOAD_ROOT']).replace('\\', '/')
    return {'name': os.path.basename(path), 'mtime': mtime, 'count': count, 'rel_path': rel_path}

def build_breadcrumbs(rel_path: str):
    parts = [] if not rel_path else rel_path.strip('/').split('/')
    crumbs = []
    for i in range(len(parts)):
        sub = '/'.join(parts[: i+1])
        crumbs.append({'name': parts[i], 'path': sub})
    return crumbs

# 路由：列目录（可通过 ?path=a/b 搜索子目录）
@app.route('/', methods=['GET'])
def index():
    q = request.args.get('q', '').strip()
    rel_path = request.args.get('path', '').strip().lstrip('/\\')
    try:
        abs_path = resolve_path(rel_path)
    except ValueError:
        abort(400, '非法路径')
    if not os.path.exists(abs_path):
        flash('路径不存在，已回到根目录。')
        return redirect(url_for('index'))

    # 列出目录项
    entries = sorted(os.listdir(abs_path), key=lambda x: x.lower())
    dirs = []
    files = []
    for name in entries:
        full = os.path.join(abs_path, name)
        if q and q.lower() not in name.lower():
            continue
        if os.path.isdir(full):
            dirs.append(dir_info(full))
        else:
            files.append(file_info(full, rel_path))

    # 父目录链接
    parent_link = None
    if rel_path:
        parent_rel = os.path.dirname(rel_path).replace('\\', '/')
        parent_link = url_for('index', path=parent_rel) if parent_rel else url_for('index')

    return render_template_string(TEMPLATE,
                                  dirs=dirs, files=files,
                                  breadcrumbs=build_breadcrumbs(rel_path),
                                  current_rel_path=rel_path,
                                  parent_link=parent_link,
                                  display_path='/' + (rel_path or ''),
                                  upload_root=app.config['UPLOAD_ROOT'],
                                  max_size_mb=int(app.config['MAX_CONTENT_LENGTH']/(1024*1024)),
                                  q=q)

# 上传到指定相对目录
@app.route('/upload', methods=['POST'])
def upload():
    rel_path = request.args.get('path', '').strip().lstrip('/\\')
    try:
        abs_path = resolve_path(rel_path)
    except ValueError:
        abort(400, '非法路径')
    if not os.path.isdir(abs_path):
        flash('目标目录不存在。')
        return redirect(url_for('index'))

    if 'file' not in request.files:
        flash('未选择文件。')
        return redirect(url_for('index', path=rel_path))
    f = request.files['file']
    if f.filename == '':
        flash('未选择文件。')
        return redirect(url_for('index', path=rel_path))
    filename = secure_filename(f.filename)
    if not allowed_file(filename):
        flash('不允许的文件类型。')
        return redirect(url_for('index', path=rel_path))
    save_path = os.path.join(abs_path, filename)
    # 若存在则改名
    if os.path.exists(save_path):
        name, ext = os.path.splitext(filename)
        filename = f"{name}_{int(datetime.now().timestamp())}{ext}"
        save_path = os.path.join(abs_path, filename)
    f.save(save_path)
    flash(f'已上传: {filename}')
    return redirect(url_for('index', path=rel_path))

# 新建子文件夹（表单提交到 /mkdir?path=当前相对目录）
@app.route('/mkdir', methods=['POST'])
def mkdir():
    rel_path = request.args.get('path', '').strip().lstrip('/\\')
    new_folder = (request.form.get('new_folder') or '').strip()
    if not new_folder:
        flash('请输入文件夹名。')
        return redirect(url_for('index', path=rel_path))
    safe = secure_filename(new_folder)
    try:
        target_dir = resolve_path(os.path.join(rel_path, safe))
    except ValueError:
        abort(400, '非法路径')
    if os.path.exists(target_dir):
        flash('文件夹已存在。')
    else:
        os.makedirs(target_dir, exist_ok=True)
        flash(f'已创建文件夹: {safe}')
    return redirect(url_for('index', path=os.path.relpath(target_dir, app.config['UPLOAD_ROOT']).replace('\\','/')))

# 删除空文件夹（安全起见只允许删除空文件夹）
@app.route('/rmdir', methods=['POST'])
def rmdir():
    rel_path = request.args.get('path', '').strip().lstrip('/\\')
    try:
        abs_path = resolve_path(rel_path)
    except ValueError:
        abort(400, '非法路径')
    if not os.path.isdir(abs_path):
        flash('目标不是目录。')
        return redirect(url_for('index'))
    if os.listdir(abs_path):
        flash('文件夹非空，无法删除。')
        return redirect(url_for('index', path=rel_path))
    os.rmdir(abs_path)
    flash(f'已删除文件夹: {os.path.basename(abs_path)}')
    parent_rel = os.path.dirname(rel_path).replace('\\','/')
    return redirect(url_for('index', path=parent_rel))

# 下载（强制附件下载）
@app.route('/download/<path:path>', methods=['GET'])
def download(path):
    try:
        abs_path = resolve_path(path)
    except ValueError:
        abort(400, '非法路径')
    if not os.path.isfile(abs_path):
        abort(404)
    rel = os.path.relpath(abs_path, app.config['UPLOAD_ROOT']).replace('\\','/')
    # send_from_directory 的 directory 参数需要绝对目录的父目录和文件名分离
    dirpath = os.path.dirname(abs_path)
    filename = os.path.basename(abs_path)
    return send_from_directory(dirpath, filename, as_attachment=True)

# 预览（在浏览器打开）
@app.route('/preview/<path:path>', methods=['GET'])
def preview(path):
    try:
        abs_path = resolve_path(path)
    except ValueError:
        abort(400, '非法路径')
    if not os.path.isfile(abs_path):
        abort(404)
    dirpath = os.path.dirname(abs_path)
    filename = os.path.basename(abs_path)
    return send_from_directory(dirpath, filename, as_attachment=False)

# 删除文件
@app.route('/delete/<path:path>', methods=['POST'])
def delete(path):
    try:
        abs_path = resolve_path(path)
    except ValueError:
        abort(400, '非法路径')
    if not os.path.isfile(abs_path):
        flash('文件不存在。')
        return redirect(url_for('index'))
    os.remove(abs_path)
    flash(f'已删除文件: {os.path.basename(abs_path)}')
    parent_rel = os.path.dirname(path).replace('\\','/')
    return redirect(url_for('index', path=parent_rel))

if __name__ == '__main__':
    app.run(debug=True)
