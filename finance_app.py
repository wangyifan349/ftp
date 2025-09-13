# finance_app.py
# Single-file finance manager (Flask + sqlite3 raw SQL)
# - password hashing: bcrypt
# - charts: Chart.js (frontend)
# - UI: Bootstrap 5 + Bootstrap Icons
# - export Excel: openpyxl
# - DB: sqlite3 (raw SQL)
# Note: Example single-file for local/trusted use. For production use HTTPS, CSRF, stronger session management, etc.
from flask import Flask, g, request, jsonify, send_file
import sqlite3, os
from datetime import datetime
from io import BytesIO
import openpyxl
import bcrypt
DB_PATH = 'finance.db'
app = Flask(__name__)
# ---------- Database helpers (sqlite3 raw SQL) ----------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        need_init = not os.path.exists(DB_PATH)
        db = g._database = sqlite3.connect(DB_PATH, check_same_thread=False)
        db.row_factory = sqlite3.Row
        if need_init:
            init_db(db)
    return db
def init_db(db):
    cur = db.cursor()
    # users table, password stored as bcrypt hash
    cur.execute('''
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash BLOB NOT NULL
    )
    ''')
    # transactions table
    cur.execute('''
    CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        description TEXT NOT NULL,
        amount REAL NOT NULL,
        type TEXT NOT NULL, -- income or expense
        category TEXT,
        date TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')
    # insert example user demo/demo (hashed)
    pwd = b"demo"
    salt = bcrypt.gensalt()
    ph = bcrypt.hashpw(pwd, salt)
    cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("demo", ph))
    db.commit()
@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, '_database', None)
    if db:
        db.close()
# ---------- User helpers ----------
def get_user_by_username(username):
    cur = get_db().execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
    return cur.fetchone()
def get_user_by_id(uid):
    cur = get_db().execute("SELECT id, username FROM users WHERE id = ?", (uid,))
    return cur.fetchone()
# ---------- API: register / login (bcrypt) ----------
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    if not username or not password:
        return jsonify({"error":"username and password required"}), 400
    if get_user_by_username(username):
        return jsonify({"error":"username exists"}), 400
    pw_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    pw_hash = bcrypt.hashpw(pw_bytes, salt)
    cur = get_db().cursor()
    cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, pw_hash))
    get_db().commit()
    return jsonify({"message":"registered","user_id": cur.lastrowid, "username": username}), 201
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    user = get_user_by_username(username)
    if not user:
        return jsonify({"error":"invalid username or password"}), 401
    pw_bytes = password.encode('utf-8')
    stored = user['password_hash']
    try:
        ok = bcrypt.checkpw(pw_bytes, stored)
    except Exception:
        ok = False
    if not ok:
        return jsonify({"error":"invalid username or password"}), 401
    return jsonify({"message":"login successful","user_id": user['id'], "username": user['username']}), 200
# ---------- Helper: require user by id in request body ----------
def require_user_from(data):
    uid = data.get('user_id')
    if not uid:
        return None, (jsonify({"error":"missing user_id"}), 401)
    user = get_user_by_id(uid)
    if not user:
        return None, (jsonify({"error":"invalid user_id"}), 401)
    return user, None
# ---------- Transactions API (raw SQL) ----------
@app.route('/api/add_transaction', methods=['POST'])
def api_add_transaction():
    data = request.json or {}
    user, err = require_user_from(data)
    if err: return err
    description = (data.get('description') or '').strip()
    try:
        amount = float(data.get('amount'))
    except:
        return jsonify({"error":"invalid amount"}), 400
    ttype = data.get('type')
    if ttype not in ('income','expense'):
        return jsonify({"error":"type must be 'income' or 'expense'"}), 400
    category = (data.get('category') or '').strip() or None
    date_str = data.get('date') or datetime.utcnow().isoformat()
    cur = get_db().cursor()
    cur.execute("""INSERT INTO transactions (user_id, description, amount, type, category, date)
                   VALUES (?, ?, ?, ?, ?, ?)""", (user['id'], description, amount, ttype, category, date_str))
    get_db().commit()
    return jsonify({"message":"added","transaction_id": cur.lastrowid}), 201
@app.route('/api/edit_transaction', methods=['POST'])
def api_edit_transaction():
    data = request.json or {}
    user, err = require_user_from(data)
    if err: return err
    tx_id = data.get('id')
    if not tx_id:
        return jsonify({"error":"missing transaction id"}), 400
    cur = get_db().execute("SELECT * FROM transactions WHERE id=? AND user_id=?", (tx_id, user['id']))
    tx = cur.fetchone()
    if not tx:
        return jsonify({"error":"transaction not found or no permission"}), 404
    description = data.get('description', tx['description'])
    try:
        amount = float(data.get('amount', tx['amount']))
    except:
        return jsonify({"error":"invalid amount"}), 400
    ttype = data.get('type', tx['type'])
    if ttype not in ('income','expense'):
        return jsonify({"error":"type must be 'income' or 'expense'"}), 400
    category = data.get('category', tx['category'])
    date_str = data.get('date', tx['date'])
    get_db().execute("""UPDATE transactions SET description=?, amount=?, type=?, category=?, date=? WHERE id=? AND user_id=?""",
                     (description, amount, ttype, category, date_str, tx_id, user['id']))
    get_db().commit()
    return jsonify({"message":"updated"}), 200
@app.route('/api/delete_transaction', methods=['POST'])
def api_delete_transaction():
    data = request.json or {}
    user, err = require_user_from(data)
    if err: return err
    tx_id = data.get('id')
    if not tx_id:
        return jsonify({"error":"missing transaction id"}), 400
    cur = get_db().cursor()
    cur.execute("DELETE FROM transactions WHERE id=? AND user_id=?", (tx_id, user['id']))
    get_db().commit()
    if cur.rowcount == 0:
        return jsonify({"error":"transaction not found or no permission"}), 404
    return jsonify({"message":"deleted"}), 200
# ---------- Get transactions (with filters) ----------
@app.route('/api/get_transactions', methods=['GET'])
def api_get_transactions():
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({"error":"please provide user_id"}), 400
    if not get_user_by_id(user_id):
        return jsonify({"error":"invalid user_id"}), 401
    q = "SELECT * FROM transactions WHERE user_id = ?"
    params = [user_id]
    start = request.args.get('start_date')
    end = request.args.get('end_date')
    if start:
        q += " AND date >= ?"; params.append(start)
    if end:
        q += " AND date <= ?"; params.append(end)
    category = request.args.get('category')
    if category:
        q += " AND category = ?"; params.append(category)
    ttype = request.args.get('type')
    if ttype in ('income','expense'):
        q += " AND type = ?"; params.append(ttype)
    q += " ORDER BY date DESC"
    cur = get_db().execute(q, params)
    rows = cur.fetchall()
    txs = []
    for r in rows:
        txs.append({"id": r['id'], "description": r['description'], "amount": r['amount'],
                    "type": r['type'], "category": r['category'], "date": r['date']})
    return jsonify(txs), 200
# ---------- Monthly summary (for charts) ----------
@app.route('/api/monthly_summary', methods=['GET'])
def api_monthly_summary():
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({"error":"please provide user_id"}), 400
    if not get_user_by_id(user_id):
        return jsonify({"error":"invalid user_id"}), 401
    cur = get_db().execute("""
      SELECT substr(date,1,7) as month,
             SUM(CASE WHEN type='income' THEN amount ELSE 0 END) as income,
             SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) as expense
      FROM transactions
      WHERE user_id=?
      GROUP BY month
      ORDER BY month ASC
    """, (user_id,))
    rows = cur.fetchall()
    res = []
    for r in rows:
        income = r['income'] or 0
        expense = r['expense'] or 0
        res.append({"month": r['month'], "income": income, "expense": expense, "balance": income - expense})
    return jsonify(res), 200
# ---------- Export Excel (existing route, kept) ----------
@app.route('/api/export_excel', methods=['GET'])
def api_export_excel():
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({"error":"please provide user_id"}), 400
    user = get_user_by_id(user_id)
    if not user:
        return jsonify({"error":"invalid user_id"}), 401
    cur = get_db().execute("SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC", (user_id,))
    rows = cur.fetchall()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append(["ID","date","description","type","category","amount"])
    for r in rows:
        ws.append([r['id'], r['date'], r['description'], r['type'], r['category'] or '', r['amount']])
    # monthly summary sheet
    cur2 = get_db().execute("""
      SELECT substr(date,1,7) as month,
             SUM(CASE WHEN type='income' THEN amount ELSE 0 END) as income,
             SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) as expense
      FROM transactions WHERE user_id=? GROUP BY month ORDER BY month ASC
    """, (user_id,))
    ws2 = wb.create_sheet("Monthly Summary")
    ws2.append(["month","income","expense","balance"])
    for r in cur2.fetchall():
        income = r['income'] or 0
        expense = r['expense'] or 0
        ws2.append([r['month'], income, expense, income - expense])
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    filename = f"finance_{user['username']}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.xlsx"
    return send_file(bio, download_name=filename, as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
# ---------- New Export route (English named) ----------
@app.route('/api/export', methods=['GET'])
def api_export():
    # same implementation as api_export_excel, named 'export'
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({"error":"please provide user_id"}), 400
    user = get_user_by_id(user_id)
    if not user:
        return jsonify({"error":"invalid user_id"}), 401
    cur = get_db().execute("SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC", (user_id,))
    rows = cur.fetchall()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append(["ID","date","description","type","category","amount"])
    for r in rows:
        ws.append([r['id'], r['date'], r['description'], r['type'], r['category'] or '', r['amount']])
    cur2 = get_db().execute("""
      SELECT substr(date,1,7) as month,
             SUM(CASE WHEN type='income' THEN amount ELSE 0 END) as income,
             SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) as expense
      FROM transactions WHERE user_id=? GROUP BY month ORDER BY month ASC
    """, (user_id,))
    ws2 = wb.create_sheet("Monthly_Summary")
    ws2.append(["month","income","expense","balance"])
    for r in cur2.fetchall():
        income = r['income'] or 0
        expense = r['expense'] or 0
        ws2.append([r['month'], income, expense, income - expense])
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    filename = f"finance_{user['username']}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.xlsx"
    return send_file(bio, download_name=filename, as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
# ---------- Frontend page (single-file) ----------
@app.route('/')
def index():
    # Page uses Bootstrap 5, Chart.js, Bootstrap Icons
    return """
<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>财务管理（单文件）</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
body{max-width:1100px;margin:16px auto;padding:12px;}
.small{font-size:0.9rem;color:#555;}
.card{margin-bottom:12px;}
.table-fixed tbody{height:300px;overflow:auto;display:block;}
</style>
</head>
<body>
<div class="container">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h3><i class="bi bi-wallet2"></i> 单文件财务管理</h3>
    <div id="userArea"></div>
  </div>

  <div id="authCard" class="card p-3">
    <div class="row g-2 align-items-center">
      <div class="col-auto">
        <input id="username" class="form-control" placeholder="用户名">
      </div>
      <div class="col-auto">
        <input id="password" type="password" class="form-control" placeholder="密码">
      </div>
      <div class="col-auto">
        <button class="btn btn-primary" onclick="login()"><i class="bi bi-box-arrow-in-right"></i> 登录</button>
        <button class="btn btn-outline-secondary" onclick="register()"><i class="bi bi-person-plus"></i> 注册</button>
      </div>
      <div class="col-12 small text-muted">示例账户：<span class="badge bg-primary">demo / demo</span></div>
    </div>
  </div>

  <div id="app" style="display:none;">
    <div class="card p-3">
      <div class="row g-2">
        <div class="col-md-6">
          <input id="desc" class="form-control" placeholder="描述">
        </div>
        <div class="col-md-2">
          <input id="amount" class="form-control" placeholder="金额">
        </div>
        <div class="col-md-2">
          <input id="category" class="form-control" placeholder="分类">
        </div>
        <div class="col-md-2 d-flex gap-2">
          <button class="btn btn-success w-100" onclick="addIncome()"><i class="bi bi-plus-circle"></i> 新增收入</button>
          <button class="btn btn-danger w-100" onclick="addExpense()"><i class="bi bi-dash-circle"></i> 新增支出</button>
        </div>
      </div>
      <div class="mt-2 d-flex gap-2">
        <button class="btn btn-outline-secondary" onclick="openAddModal()">高级添加</button>
        <button class="btn btn-outline-primary" onclick="exportFile()"><i class="bi bi-file-earmark-excel"></i> Export Excel</button>
      </div>
    </div>

    <div class="row">
      <div class="col-lg-7">
        <div class="card p-3">
          <h5>交易列表</h5>
          <div class="row g-2 mb-2">
            <div class="col">
              <input id="filterCategory" class="form-control" placeholder="按分类过滤">
            </div>
            <div class="col-auto">
              <select id="filterType" class="form-select">
                <option value="">全部</option><option value="income">收入</option><option value="expense">支出</option>
              </select>
            </div>
            <div class="col-auto">
              <input id="filterMonth" class="form-control" placeholder="YYYY-MM">
            </div>
            <div class="col-auto">
              <button class="btn btn-secondary" onclick="loadTransactions()">刷新</button>
            </div>
          </div>
          <div id="txTable" class="table-responsive"></div>
        </div>
      </div>

      <div class="col-lg-5">
        <div class="card p-3 mb-3">
          <h5>每月统计（柱状图）</h5>
          <canvas id="monthChart" height="220"></canvas>
        </div>
        <div class="card p-3">
          <h5>月度表格</h5>
          <div id="monthlySummary"></div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
// Simple local session (localStorage stores user under English key "currentUser")
function setUser(u){ if(u) localStorage.setItem('currentUser', JSON.stringify(u)); else localStorage.removeItem('currentUser'); render(); }
function getUser(){ try{return JSON.parse(localStorage.getItem('currentUser'));}catch(e){return null;} }

function render(){
  const ua = document.getElementById('userArea');
  const user = getUser();
  if(user){
    ua.innerHTML = '已登录：' + escapeHtml(user.username) + ' <button class="btn btn-sm btn-outline-secondary" onclick="logout()">登出</button>';
    document.getElementById('authCard').style.display='none';
    document.getElementById('app').style.display='block';
    loadTransactions(); loadMonthly(); loadChart();
  } else {
    ua.innerHTML = '';
    document.getElementById('authCard').style.display='block';
    document.getElementById('app').style.display='none';
  }
}

// Auth
async function register(){
  const username=document.getElementById('username').value.trim();
  const password=document.getElementById('password').value.trim();
  if(!username||!password){ alert('请输入用户名和密码'); return; }
  const r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
  const j=await r.json();
  if(!r.ok){ alert(j.error||'注册失败'); return; }
  setUser({user_id:j.user_id, username:j.username});
}
async function login(){
  const username=document.getElementById('username').value.trim();
  const password=document.getElementById('password').value.trim();
  if(!username||!password){ alert('请输入用户名和密码'); return; }
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
  const j=await r.json();
  if(!r.ok){ alert(j.error||'登录失败'); return; }
  setUser({user_id:j.user_id, username:j.username});
}
function logout(){ setUser(null); }

// Quick add
async function addIncome(){ await quickAdd('income'); }
async function addExpense(){ await quickAdd('expense'); }
async function quickAdd(type){
  const user=getUser(); if(!user){ alert('请先登录'); return; }
  const description=document.getElementById('desc').value.trim();
  const amount=document.getElementById('amount').value.trim();
  const category=document.getElementById('category').value.trim();
  if(!description||!amount){ alert('请填写描述和金额'); return; }
  const r=await fetch('/api/add_transaction',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id:user.user_id,description,amount,type,category})});
  const j=await r.json();
  if(!r.ok){ alert(j.error||'添加失败'); return; }
  document.getElementById('desc').value=''; document.getElementById('amount').value=''; document.getElementById('category').value='';
  loadTransactions(); loadMonthly(); loadChart();
}

// Advanced add (with custom date)
function openAddModal(){
  const user=getUser(); if(!user){ alert('请先登录'); return; }
  const description=prompt('描述'); if(description===null) return;
  const amount=prompt('金额'); if(amount===null) return;
  const type=prompt("类型: 'income' 或 'expense'","expense"); if(type===null) return;
  const category=prompt('分类','');
  const date=prompt('日期（ISO 或 YYYY-MM-DD）', new Date().toISOString());
  (async ()=>{
    const r=await fetch('/api/add_transaction',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({user_id:user.user_id,description,amount,type,category,date})});
    const j=await r.json();
    if(!r.ok){ alert(j.error||'添加失败'); return; }
    loadTransactions(); loadMonthly(); loadChart();
  })();
}

// List load & render
async function loadTransactions(){
  const user=getUser(); if(!user) return;
  let url='/api/get_transactions?user_id=' + user.user_id;
  const category=document.getElementById('filterCategory').value.trim();
  const type=document.getElementById('filterType').value;
  const month=document.getElementById('filterMonth').value.trim();
  if(category) url += '&category=' + encodeURIComponent(category);
  if(type) url += '&type=' + encodeURIComponent(type);
  if(month) { url += '&start_date=' + encodeURIComponent(month + '-01T00:00:00') + '&end_date=' + encodeURIComponent(month + '-31T23:59:59'); }
  const r=await fetch(url);
  const data=await r.json();
  if(!r.ok){ alert(data.error||'加载失败'); return; }
  renderTxTable(data);
}

function renderTxTable(txs){
  const c=document.getElementById('txTable');
  if(!txs||txs.length===0){ c.innerHTML='<div class="small">暂无交易</div>'; return; }
  let html='<table class="table table-sm table-hover"><thead><tr><th>日期</th><th>描述</th><th>分类</th><th>类型</th><th class="text-end">金额</th><th>操作</th></tr></thead><tbody>';
  txs.forEach(t=>{
    const amt = Number(t.amount).toFixed(2);
    html += `<tr><td>${escapeHtml(t.date)}</td><td>${escapeHtml(t.description)}</td><td>${escapeHtml(t.category||'')}</td><td>${escapeHtml(t.type)}</td><td class="text-end">${amt}</td>`;
    html += `<td><button class="btn btn-sm btn-outline-primary me-1" onclick="editTx(${t.id})"><i class="bi bi-pencil"></i></button>`;
    html += `<button class="btn btn-sm btn-outline-danger" onclick="deleteTx(${t.id})"><i class="bi bi-trash"></i></button></td></tr>`;
  });
  html += '</tbody></table>';
  c.innerHTML = html;
}

async function deleteTx(id){
  if(!confirm('确认删除？')) return;
  const user=getUser(); if(!user) return;
  const r=await fetch('/api/delete_transaction',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({user_id:user.user_id, id})});
  const j=await r.json();
  if(!r.ok){ alert(j.error||'删除失败'); return; }
  loadTransactions(); loadMonthly(); loadChart();
}

function editTx(id){
  (async ()=>{
    const user=getUser(); if(!user) return;
    const r=await fetch('/api/get_transactions?user_id=' + user.user_id);
    const txs=await r.json();
    const tx=txs.find(x=>x.id===id);
    if(!tx){ alert('未找到'); return; }
    const description=prompt('描述', tx.description); if(description===null) return;
    const amount=prompt('金额', tx.amount); if(amount===null) return;
    const type=prompt("类型 (income 或 expense)", tx.type); if(type===null) return;
    const category=prompt('分类', tx.category||''); if(category===null) return;
    const date=prompt('日期 (ISO)', tx.date); if(date===null) return;
    const res=await fetch('/api/edit_transaction',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({user_id:user.user_id,id,description,amount,type,category,date})});
    const j=await res.json();
    if(!res.ok){ alert(j.error||'更新失败'); return; }
    loadTransactions(); loadMonthly(); loadChart();
  })();
}

// Monthly summary & chart
let monthChart = null;
async function loadMonthly(){
  const user=getUser(); if(!user) return;
  const r=await fetch('/api/monthly_summary?user_id=' + user.user_id);
  const data=await r.json();
  if(!r.ok){ alert(data.error||'加载失败'); return; }
  const el=document.getElementById('monthlySummary');
  if(!data||data.length===0){ el.innerHTML='<div class="small">暂无月度数据</div>'; return; }
  let html = '<table class="table table-sm"><thead><tr><th>月份</th><th class="text-end">收入</th><th class="text-end">支出</th><th class="text-end">结余</th></tr></thead><tbody>';
  data.forEach(m=>{
    html += `<tr><td>${escapeHtml(m.month)}</td><td class="text-end">${Number(m.income).toFixed(2)}</td><td class="text-end">${Number(m.expense).toFixed(2)}</td><td class="text-end">${Number(m.balance).toFixed(2)}</td></tr>`;
  });
  html += '</tbody></table>';
  el.innerHTML = html;
  return data;
}

async function loadChart(){
  const user=getUser(); if(!user) return;
  const r=await fetch('/api/monthly_summary?user_id=' + user.user_id);
  const data=await r.json();
  if(!r.ok) return;
  const labels = data.map(d=>d.month);
  const incomes = data.map(d=>d.income);
  const expenses = data.map(d=>d.expense);
  const ctx = document.getElementById('monthChart').getContext('2d');
  if(monthChart) monthChart.destroy();
  monthChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {label: '收入', data: incomes, backgroundColor: 'rgba(40,167,69,0.7)'},
        {label: '支出', data: expenses, backgroundColor: 'rgba(220,53,69,0.7)'}
      ]
    },
    options: {
      responsive: true,
      scales: {
        x: { stacked: false },
        y: { beginAtZero: true }
      }
    }
  });
}

// Export file (calls new /api/export route)
function exportFile(){
  const user=getUser(); if(!user) return;
  window.location = '/api/export?user_id=' + user.user_id;
}

function escapeHtml(s){ return s? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : ''; }

// Init
render();
</script>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""
if __name__ == '__main__':
    with app.app_context():
        get_db()
    app.run(debug=False)
