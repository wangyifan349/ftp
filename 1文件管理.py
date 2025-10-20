from flask import Flask, request, send_from_directory, render_template_string, redirect, url_for, jsonify
import os
import shutil

app = Flask(__name__)

BASE_DIR = 'uploads'
os.makedirs(BASE_DIR, exist_ok=True)

HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>文件管理系统</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { padding: 20px; }
        .file-item, .folder-item { padding: 8px; border: 1px solid #ddd; margin-bottom: 5px; border-radius: 5px; display:flex; justify-content:space-between; align-items:center; }
        #drop-area { border: 2px dashed #0d6efd; padding: 20px; text-align: center; border-radius: 10px; margin-bottom: 20px; }
        #drop-area.highlight { border-color: #198754; }
    </style>
</head>
<body>
<div class="container">
    <h2>文件管理系统</h2>
    <p>当前路径: /{{ path or '' }}</p>

    <div id="drop-area">
        <p>拖拽文件到此上传</p>
        <input type="file" id="fileElem" multiple hidden>
        <button class="btn btn-primary" onclick="document.getElementById('fileElem').click()">选择文件</button>
    </div>

    <form action="/mkdir" method="post" class="d-flex mb-3">
        <input type="text" name="folder" class="form-control" placeholder="新建文件夹名称" required>
        <input type="hidden" name="path" value="{{ path }}">
        <button class="btn btn-success ms-2">创建</button>
    </form>

    {% if path %}
        <a href="/?path={{ parent_path }}" class="btn btn-secondary mb-3">返回上级</a>
    {% endif %}

    <div>
        {% for folder in folders %}
            <div class="folder-item">
                <a href="/?path={{ path + '/' if path else '' }}{{ folder }}">📁 {{ folder }}</a>
                <div>
                    <button class="btn btn-sm btn-warning" onclick="moveItem('{{ folder }}', 'folder')">移动</button>
                    <a href="/delete?path={{ path }}&name={{ folder }}&type=folder" class="btn btn-sm btn-danger ms-2">删除</a>
                </div>
            </div>
        {% endfor %}
        {% for file in files %}
            <div class="file-item">
                📄 {{ file }}
                <div>
                    <a href="/download?path={{ path }}&filename={{ file }}" class="btn btn-sm btn-primary">下载</a>
                    <button class="btn btn-sm btn-warning ms-2" onclick="moveItem('{{ file }}', 'file')">移动</button>
                    <a href="/delete?path={{ path }}&name={{ file }}&type=file" class="btn btn-sm btn-danger ms-2">删除</a>
                </div>
            </div>
        {% endfor %}
    </div>
</div>

<script>
const dropArea = document.getElementById('drop-area');
const fileInput = document.getElementById('fileElem');

['dragenter', 'dragover'].forEach(eventName => {
    dropArea.addEventListener(eventName, e => { e.preventDefault(); dropArea.classList.add('highlight'); });
});

['dragleave', 'drop'].forEach(eventName => {
    dropArea.addEventListener(eventName, e => { e.preventDefault(); dropArea.classList.remove('highlight'); });
});

dropArea.addEventListener('drop', e => {
    let files = e.dataTransfer.files;
    uploadFiles(files);
});

fileInput.addEventListener('change', e => uploadFiles(fileInput.files));

function uploadFiles(files) {
    let formData = new FormData();
    for (let file of files) formData.append('files', file);
    formData.append('path', "{{ path }}");
    fetch('/upload', { method: 'POST', body: formData }).then(() => location.reload());
}

function moveItem(name, type) {
    let newPath = prompt("输入目标路径（例如 folder/subfolder）：");
    if (newPath !== null) {
        fetch('/move', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: "{{ path }}", name: name, type: type, new_path: newPath})
        }).then(() => location.reload());
    }
}
</script>
</body>
</html>
"""

@app.route('/')
def index():
    path = request.args.get('path', '').strip('/')
    current = os.path.join(BASE_DIR, path)
    os.makedirs(current, exist_ok=True)

    items = os.listdir(current)
    folders = [i for i in items if os.path.isdir(os.path.join(current, i))]
    files = [i for i in items if os.path.isfile(os.path.join(current, i))]
    parent_path = '/'.join(path.split('/')[:-1]) if path else ''
    return render_template_string(HTML, path=path, parent_path=parent_path, folders=folders, files=files)

@app.route('/upload', methods=['POST'])
def upload():
    path = request.form.get('path', '').strip('/')
    upload_dir = os.path.join(BASE_DIR, path)
    for f in request.files.getlist('files'):
        f.save(os.path.join(upload_dir, f.filename))
    return redirect(url_for('index', path=path))

@app.route('/download')
def download():
    path = request.args.get('path', '').strip('/')
    filename = request.args.get('filename')
    return send_from_directory(os.path.join(BASE_DIR, path), filename, as_attachment=True)

@app.route('/mkdir', methods=['POST'])
def mkdir():
    path = request.form.get('path', '').strip('/')
    folder = request.form.get('folder')
    os.makedirs(os.path.join(BASE_DIR, path, folder), exist_ok=True)
    return redirect(url_for('index', path=path))

@app.route('/delete')
def delete():
    path = request.args.get('path', '').strip('/')
    name = request.args.get('name')
    type_ = request.args.get('type')
    target = os.path.join(BASE_DIR, path, name)
    if type_ == 'file':
        os.remove(target)
    elif type_ == 'folder':
        shutil.rmtree(target)
    return redirect(url_for('index', path=path))

@app.route('/move', methods=['POST'])
def move():
    data = request.get_json()
    src = os.path.join(BASE_DIR, data['path'], data['name'])
    dst = os.path.join(BASE_DIR, data['new_path'], data['name'])
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
