from flask import Flask, g, jsonify, request, Response, send_file
import sqlite3
from datetime import datetime
import os
import io
import json
import zipfile
DB_PATH = os.path.join(os.path.dirname(__file__), 'notes.db')
app = Flask(__name__)
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()
def init_db():
    db = get_db()
    db.execute('''
    CREATE TABLE IF NOT EXISTS notes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      content TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    ''')
    db.commit()
@app.before_first_request
def setup():
    init_db()
@app.route('/')
def index():
    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>云端记事本</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body{background:#f6f7fb}
    #app{display:flex;gap:16px;padding:16px;align-items:stretch;min-height:100vh}
    #sidebar{width:320px;max-width:40%}
    #editor{flex:1}
    .note-item{cursor:pointer}
    .note-snippet{color:#6b7280;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    @media (max-width:800px){
      #app{flex-direction:column;padding:8px}
      #sidebar{width:100%}
    }
  </style>
</head>
<body>
  <div class="container-fluid">
    <div id="app" class="row">
      <div id="sidebar" class="col-md-4">
        <div class="card mb-3">
          <div class="card-body d-flex align-items-center">
            <h5 class="card-title mb-0">记事本</h5>
            <div class="ms-auto">
              <button id="new-btn" class="btn btn-primary btn-sm">＋ 新建</button>
              <button id="export-btn" class="btn btn-outline-secondary btn-sm ms-2">导出全部</button>
            </div>
          </div>
          <div class="card-body">
            <input id="search" class="form-control mb-2" placeholder="搜索标题或内容">
            <ul id="notes-list" class="list-group" style="max-height:60vh;overflow:auto"></ul>
          </div>
        </div>
      </div>

      <div id="editor" class="col-md-8">
        <div class="card">
          <div class="card-body">
            <div class="d-flex mb-2">
              <input id="note-title" class="form-control me-2" placeholder="标题">
              <div class="btn-group">
                <button id="save-btn" class="btn btn-success">保存</button>
                <button id="delete-btn" class="btn btn-danger">删除</button>
              </div>
            </div>
            <textarea id="note-content" class="form-control" style="height:50vh" placeholder="在此输入笔记内容"></textarea>
            <div id="meta" class="text-muted mt-2"></div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
  <script src="/static/main.js"></script>
</body>
</html>"""
    return Response(html, mimetype='text/html')

@app.route('/static/main.js')
def js():
    js = """let notes = [];
let currentId = null;
const el = id => document.getElementById(id);

async function api(path, opts){
  const res = await fetch(path, Object.assign({
    headers: {'Content-Type':'application/json'}
  }, opts));
  if(res.status === 204) return null;
  const data = await res.json().catch(()=>null);
  if(!res.ok) throw data || {error:'network'};
  return data;
}

async function fetchNotes(){
  try{
    notes = await api('/api/notes', {method:'GET'});
    renderList();
    if(currentId == null && notes.length) {
      selectNote(notes[0].id);
    } else if(currentId) {
      let found = null;
      for(let i = 0; i < notes.length; i++){
        if(notes[i].id === currentId){
          found = notes[i];
          break;
        }
      }
      if(!found && notes.length) selectNote(notes[0].id);
    }
  }catch(e){ console.error(e) }
}

function renderList(filter=''){
  const list = el('notes-list');
  list.innerHTML = '';
  const q = filter.trim().toLowerCase();
  for(let i = 0; i < notes.length; i++){
    const n = notes[i];
    if(q){
      const t = (n.title||'').toLowerCase();
      const c = (n.content||'').toLowerCase();
      if(t.indexOf(q) === -1 && c.indexOf(q) === -1) continue;
    }
    const li = document.createElement('li');
    li.className = 'list-group-item note-item d-flex flex-column';
    li.dataset.id = n.id;
    li.addEventListener('click', ()=>selectNote(n.id));
    const tdiv = document.createElement('div'); tdiv.className='fw-semibold'; tdiv.textContent = n.title || 'Untitled';
    const sdiv = document.createElement('div'); sdiv.className='note-snippet';
    sdiv.textContent = (n.content || '').replace(/\\n/g,' ').slice(0,120);
    li.appendChild(tdiv); li.appendChild(sdiv);
    list.appendChild(li);
  }
}

function fillEditor(note){
  el('note-title').value = note.title || '';
  el('note-content').value = note.content || '';
  const meta = '创建: ' + (note.created_at || '-') + '  更新时间: ' + (note.updated_at || '-');
  el('meta').textContent = meta;
}

async function selectNote(id){
  try{
    const note = await api('/api/notes/' + id, {method:'GET'});
    currentId = note.id;
    fillEditor(note);
    const items = document.querySelectorAll('.note-item');
    for(let i = 0; i < items.length; i++){
      const it = items[i];
      const nid = Number(it.dataset.id);
      if(nid === currentId) it.classList.add('active'); else it.classList.remove('active');
    }
  }catch(e){ console.error(e) }
}

async function newNote(){
  try{
    const n = await api('/api/notes', {
      method:'POST',
      body: JSON.stringify({title: '新建笔记', content: ''})
    });
    await fetchNotes();
    selectNote(n.id);
  }catch(e){ console.error(e) }
}

let saveTimer = null;
function scheduleAutoSave(){
  if(saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNote, 800);
}

async function saveNote(){
  const title = el('note-title').value.trim() || 'Untitled';
  const content = el('note-content').value;
  try{
    if(currentId){
      await api('/api/notes/' + currentId, {
        method: 'PUT',
        body: JSON.stringify({title: title, content: content})
      });
    } else {
      const n = await api('/api/notes', {
        method: 'POST',
        body: JSON.stringify({title: title, content: content})
      });
      currentId = n.id;
    }
    await fetchNotes();
    selectNote(currentId);
  }catch(e){ console.error(e) }
}

async function deleteNote(){
  if(!currentId) return;
  if(!confirm('确认删除该笔记？')) return;
  try{
    await api('/api/notes/' + currentId, {method:'DELETE'});
    currentId = null;
    await fetchNotes();
    if(notes.length) selectNote(notes[0].id);
    else {
      el('note-title').value = '';
      el('note-content').value = '';
      el('meta').textContent = '';
    }
  }catch(e){ console.error(e) }
}

function attachEvents(){
  el('new-btn').addEventListener('click', newNote);
  el('save-btn').addEventListener('click', saveNote);
  el('delete-btn').addEventListener('click', deleteNote);
  el('export-btn').addEventListener('click', exportAll);
  el('note-title').addEventListener('input', scheduleAutoSave);
  el('note-content').addEventListener('input', scheduleAutoSave);
  el('search').addEventListener('input', function(e){ renderList(e.target.value); });
  window.addEventListener('beforeunload', function(){ if(saveTimer) saveNote(); });
}

async function exportAll(){
  try{
    const res = await fetch('/api/notes/export', {method:'GET'});
    if(!res.ok) throw new Error('export failed');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const now = new Date().toISOString().slice(0,19).replace(/[:T]/g,'-');
    a.download = 'notes-export-' + now + '.zip';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }catch(e){ console.error(e) }
}

window.addEventListener('load', async function(){
  attachEvents();
  await fetchNotes();
});"""
    return Response(js, mimetype='application/javascript')
@app.route('/api/notes', methods=['GET'])
def list_notes():
    db = get_db()
    cur = db.execute('SELECT id, title, content, created_at, updated_at FROM notes ORDER BY updated_at DESC')
    rows = cur.fetchall()
    result = []
    i = 0
    while i < len(rows):
        row = rows[i]
        item = {
            'id': row['id'],
            'title': row['title'],
            'content': row['content'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        }
        result.append(item)
        i += 1
    return jsonify(result)
@app.route('/api/notes/<int:note_id>', methods=['GET'])
def get_note(note_id):
    db = get_db()
    cur = db.execute('SELECT id, title, content, created_at, updated_at FROM notes WHERE id = ?', (note_id,))
    row = cur.fetchone()
    if not row:
        return jsonify({'error': 'not found'}), 404
    note = {
        'id': row['id'],
        'title': row['title'],
        'content': row['content'],
        'created_at': row['created_at'],
        'updated_at': row['updated_at']
    }
    return jsonify(note)
@app.route('/api/notes', methods=['POST'])
def create_note():
    data = request.get_json() or {}
    title = data.get('title')
    content = data.get('content')
    if title is None:
        title = 'Untitled'
    if content is None:
        content = ''
    now = datetime.utcnow().isoformat()
    db = get_db()
    cur = db.execute('INSERT INTO notes (title, content, created_at, updated_at) VALUES (?, ?, ?, ?)',
                     (title, content, now, now))
    db.commit()
    nid = cur.lastrowid
    cur2 = db.execute('SELECT id, title, content, created_at, updated_at FROM notes WHERE id = ?', (nid,))
    row = cur2.fetchone()
    note = {
        'id': row['id'],
        'title': row['title'],
        'content': row['content'],
        'created_at': row['created_at'],
        'updated_at': row['updated_at']
    }
    return jsonify(note), 201
@app.route('/api/notes/<int:note_id>', methods=['PUT'])
def update_note(note_id):
    data = request.get_json() or {}
    title = data.get('title')
    content = data.get('content')
    if title is None:
        title = 'Untitled'
    if content is None:
        content = ''
    now = datetime.utcnow().isoformat()
    db = get_db()
    cur = db.execute('SELECT id FROM notes WHERE id = ?', (note_id,))
    row = cur.fetchone()
    if not row:
        return jsonify({'error': 'not found'}), 404
    db.execute('UPDATE notes SET title = ?, content = ?, updated_at = ? WHERE id = ?',
               (title, content, now, note_id))
    db.commit()
    cur2 = db.execute('SELECT id, title, content, created_at, updated_at FROM notes WHERE id = ?', (note_id,))
    row2 = cur2.fetchone()
    note = {
        'id': row2['id'],
        'title': row2['title'],
        'content': row2['content'],
        'created_at': row2['created_at'],
        'updated_at': row2['updated_at']
    }
    return jsonify(note)
@app.route('/api/notes/<int:note_id>', methods=['DELETE'])
def delete_note(note_id):
    db = get_db()
    cur = db.execute('SELECT id FROM notes WHERE id = ?', (note_id,))
    row = cur.fetchone()
    if not row:
        return jsonify({'error': 'not found'}), 404
    db.execute('DELETE FROM notes WHERE id = ?', (note_id,))
    db.commit()
    return jsonify({'result': 'deleted'})
@app.route('/api/notes/export', methods=['GET'])
def export_notes():
    db = get_db()
    cur = db.execute('SELECT id, title, content, created_at, updated_at FROM notes ORDER BY id ASC')
    rows = cur.fetchall()
    notes_list = []
    i = 0
    while i < len(rows):
        row = rows[i]
        note_obj = {
            'id': row['id'],
            'title': row['title'],
            'content': row['content'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        }
        notes_list.append(note_obj)
        i += 1
    # 构建 JSON 文件并放入 zip
    mem_zip = io.BytesIO()
    z = zipfile.ZipFile(mem_zip, mode='w', compression=zipfile.ZIP_DEFLATED)
    json_bytes = json.dumps(notes_list, ensure_ascii=False, indent=2).encode('utf-8')
    z.writestr('notes.json', json_bytes)
    # 也每条单独保存为 txt（可选）
    j = 0
    while j < len(notes_list):
        n = notes_list[j]
        filename = f"note-{n['id']}.txt"
        content = f"Title: {n['title']}\nCreated: {n['created_at']}\nUpdated: {n['updated_at']}\n\n{n['content']}"
        z.writestr(filename, content.encode('utf-8'))
        j += 1
    z.close()
    mem_zip.seek(0)
    now = datetime.utcnow().isoformat().replace(':','-').split('.')[0]
    return send_file(
        mem_zip,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'notes-export-{now}.zip'
    )
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
