// src/main.rs
// Single-file cloud drive demo: backend + embedded frontend
//
// Dependencies (Cargo.toml):
// [package]
// name = "cloudrive_single"
// version = "0.1.0"
// edition = "2021"
//
// [dependencies]
// actix-web = "4"
// actix-multipart = "0.4"
// actix-files = "0.6"
// serde = { version = "1.0", features = ["derive"] }
// serde_json = "1.0"
// tokio = { version = "1", features = ["rt-multi-thread", "macros", "fs"] }
// sqlx = { version = "0.7", features = ["sqlite", "runtime-tokio-native-tls"] }
// argon2 = "0.4"
// uuid = { version = "1", features = ["v4"] }
// chrono = { version = "0.4", features = ["serde"] }
// mime_guess = "2.0"
// futures-util = "0.3"
// dotenvy = "0.15"
// anyhow = "1.0"
// lazy_static = "1.4"
// rand = "0.8"
//
// Then run: cargo run
//
// Warning: this is demo code. Do not use as-is in production.

use actix_files::NamedFile;
use actix_multipart::Multipart;
use actix_web::{web, App, HttpResponse, HttpServer, Responder, HttpRequest, middleware};
use futures_util::StreamExt as _;
use serde::{Deserialize, Serialize};
use sqlx::{SqlitePool, sqlite::SqlitePoolOptions};
use uuid::Uuid;
use chrono::Utc;
use std::path::{PathBuf, Path};
use std::sync::Mutex;
use lazy_static::lazy_static;
use argon2::{Argon2, PasswordHash, PasswordVerifier, PasswordHasher};
use argon2::password_hash::SaltString;
use rand::Rng;
use std::fs;
use anyhow::Result;

// ---------- Models ----------
#[derive(Deserialize)]
struct RegisterRequest { username: String, password: String }

#[derive(Deserialize)]
struct LoginRequest { username: String, password: String }

#[derive(Serialize)]
struct AuthResponse { token: String, user_id: String }

#[derive(Serialize, sqlx::FromRow)]
struct Node {
    id: String,
    owner_id: String,
    parent_id: Option<String>,
    name: String,
    is_dir: i32,
    size: i64,
    storage_path: Option<String>,
    created_at: String,
    updated_at: String,
}

// ---------- Globals ----------
lazy_static! {
    static ref TOKENS: Mutex<std::collections::HashMap<String, String>> = Mutex::new(Default::default());
}

// ---------- Helpers ----------
fn issue_token(user_id: &str) -> String {
    let token = Uuid::new_v4().to_string();
    TOKENS.lock().unwrap().insert(token.clone(), user_id.to_string());
    token
}

fn get_user_by_token(token: &str) -> Option<String> {
    TOKENS.lock().unwrap().get(token).cloned()
}

fn file_storage_path(root: &str, owner_id: &str, id: &str) -> PathBuf {
    Path::new(root).join(owner_id).join(id)
}

async fn save_multipart_file(mut field: actix_multipart::Field, dest: &Path) -> anyhow::Result<u64> {
    use tokio::io::AsyncWriteExt;
    let mut f = tokio::fs::File::create(dest).await?;
    let mut size: u64 = 0;
    while let Some(chunk) = field.next().await {
        let data = chunk?;
        size += data.len() as u64;
        f.write_all(&data).await?;
    }
    Ok(size)
}

fn ensure_owner_dir(root: &str, owner_id: &str) -> anyhow::Result<()> {
    let p = Path::new(root).join(owner_id);
    fs::create_dir_all(p)?;
    Ok(())
}

// ---------- DB Init ----------
async fn init_db() -> Result<SqlitePool> {
    let url = std::env::var("DATABASE_URL").unwrap_or_else(|_| "sqlite://db.sqlite3".into());
    let pool = SqlitePoolOptions::new().max_connections(5).connect(&url).await?;
    // create tables
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        "#,
    ).execute(&pool).await?;
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            parent_id TEXT,
            name TEXT NOT NULL,
            is_dir INTEGER NOT NULL,
            size INTEGER DEFAULT 0,
            storage_path TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        );
        "#,
    ).execute(&pool).await?;
    Ok(pool)
}

async fn init_share_db() -> Result<SqlitePool> {
    let url = std::env::var("SHARE_DB_URL").unwrap_or_else(|_| "sqlite://share_db.sqlite3".into());
    let pool = SqlitePoolOptions::new().max_connections(2).connect(&url).await?;
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS shares (
            id TEXT PRIMARY KEY,
            node_id TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            read_only INTEGER NOT NULL DEFAULT 1,
            expires_at TEXT
        );
        "#,
    ).execute(&pool).await?;
    Ok(pool)
}

// ---------- Auth ----------
async fn create_user(pool: &SqlitePool, username: &str, password: &str) -> anyhow::Result<String> {
    let id = Uuid::new_v4().to_string();
    let salt = SaltString::generate(&mut rand::thread_rng());
    let argon2 = Argon2::default();
    let password_hash = argon2.hash_password(password.as_bytes(), &salt)?.to_string();
    sqlx::query!("INSERT INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
        &id, username, &password_hash, Utc::now().to_rfc3339()
    ).execute(pool).await?;
    Ok(id)
}

async fn verify_user(pool: &SqlitePool, username: &str, password: &str) -> anyhow::Result<Option<String>> {
    if let Some(row) = sqlx::query!("SELECT id, password_hash FROM users WHERE username = ?", username)
        .fetch_optional(pool).await? {
        let parsed = PasswordHash::new(&row.password_hash)?;
        Argon2::default().verify_password(password.as_bytes(), &parsed)?;
        Ok(Some(row.id))
    } else {
        Ok(None)
    }
}

// ---------- App State ----------
struct AppState {
    db: SqlitePool,
    share_db: SqlitePool,
    storage_root: String,
}

// ---------- Handlers ----------

fn auth_from_req(req: &HttpRequest) -> Option<String> {
    req.headers().get("authorization").and_then(|v| v.to_str().ok()).and_then(|s| {
        if s.starts_with("Bearer ") { Some(s[7..].to_string()) } else { None }
    }).and_then(|t| get_user_by_token(&t))
}

// Serve embedded frontend
async fn index() -> impl Responder {
    HttpResponse::Ok().content_type("text/html; charset=utf-8").body(INDEX_HTML)
}

async fn register_handler(data: web::Data<AppState>, body: web::Json<RegisterRequest>) -> impl Responder {
    match create_user(&data.db, &body.username, &body.password).await {
        Ok(id) => HttpResponse::Ok().json(serde_json::json!({ "user_id": id })),
        Err(e) => HttpResponse::BadRequest().body(format!("err: {}", e)),
    }
}

async fn login_handler(data: web::Data<AppState>, body: web::Json<LoginRequest>) -> impl Responder {
    match verify_user(&data.db, &body.username, &body.password).await {
        Ok(Some(user_id)) => {
            let token = issue_token(&user_id);
            HttpResponse::Ok().json(AuthResponse { token, user_id })
        },
        Ok(None) => HttpResponse::Unauthorized().body("invalid"),
        Err(e) => HttpResponse::InternalServerError().body(format!("err: {}", e)),
    }
}

async fn upload_handler(mut payload: Multipart, req: HttpRequest, data: web::Data<AppState>) -> impl Responder {
    let owner = match auth_from_req(&req) { Some(u) => u, None => return HttpResponse::Unauthorized().body("no auth") };
    let mut parent_id: Option<String> = None;
    while let Some(field) = payload.next().await {
        let mut field = match field {
            Ok(f) => f,
            Err(e) => return HttpResponse::InternalServerError().body(format!("{}", e)),
        };
        if let Some(cd) = field.content_disposition().cloned() {
            if let Some(name) = cd.get_name() {
                if name == "parent_id" {
                    let mut buf = Vec::new();
                    while let Some(chunk) = field.next().await { buf.extend_from_slice(&chunk.unwrap()); }
                    parent_id = Some(String::from_utf8_lossy(&buf).to_string());
                    continue;
                } else if name == "file" {
                    let filename = cd.get_filename().map(|s| s.to_string()).unwrap_or_else(|| "unnamed".into());
                    if let Err(e) = ensure_owner_dir(&data.storage_root, &owner) { return HttpResponse::InternalServerError().body(format!("{}", e)); }
                    let id = Uuid::new_v4().to_string();
                    let storage_path = file_storage_path(&data.storage_root, &owner, &id);
                    let size = match save_multipart_file(field, &storage_path).await {
                        Ok(s) => s as i64,
                        Err(e) => return HttpResponse::InternalServerError().body(format!("{}", e)),
                    };
                    let now = Utc::now().to_rfc3339();
                    let sp = storage_path.to_str().map(|s| s.to_string());
                    sqlx::query!("INSERT INTO nodes (id, owner_id, parent_id, name, is_dir, size, storage_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        &id, &owner, parent_id, filename, 0i32, size, sp, now, now)
                        .execute(&data.db).await.expect("insert");
                    return HttpResponse::Ok().json(serde_json::json!({"id": id, "name": filename, "size": size}));
                }
            }
        }
    }
    HttpResponse::BadRequest().body("no file")
}

async fn list_nodes_handler(data: web::Data<AppState>, req: HttpRequest, query: web::Query<std::collections::HashMap<String,String>>) -> impl Responder {
    let owner = match auth_from_req(&req) { Some(u) => u, None => return HttpResponse::Unauthorized().body("no auth") };
    let parent = query.get("parent_id").cloned();
    let rows = sqlx::query_as!(Node,
        "SELECT id, owner_id, parent_id, name, is_dir, size, storage_path, created_at, updated_at FROM nodes WHERE owner_id = ? AND (parent_id IS ?)",
        owner, parent)
        .fetch_all(&data.db).await.expect("query");
    // convert is_dir to bool in frontend; here return raw rows
    HttpResponse::Ok().json(rows)
}

async fn download_handler(path: web::Path<(String,)>, data: web::Data<AppState>, req: HttpRequest) -> actix_web::Result<NamedFile> {
    let id = path.into_inner().0;
    // If Authorization present and valid, allow. Else check public share.
    let allow = match auth_from_req(&req) {
        Some(uid) => {
            // owner or shared public? allow if owner or if share exists granting access (handled below)
            if let Some(row) = sqlx::query!("SELECT owner_id FROM nodes WHERE id = ?", id).fetch_optional(&data.db).await.expect("q") {
                row.owner_id == uid
            } else { false }
        },
        None => false,
    };
    if allow {
        if let Some(row) = sqlx::query!("SELECT storage_path FROM nodes WHERE id = ?", id).fetch_optional(&data.db).await.expect("q") {
            if let Some(sp) = row.storage_path {
                let p = PathBuf::from(sp);
                return Ok(NamedFile::open(p).await?);
            }
        }
        return Err(actix_web::error::ErrorNotFound("not found"));
    }
    // check shares for public token parameter ?token=...
    if let Some(q) = req.uri().query() {
        // parse token param
        let qp: Vec<_> = q.split('&').collect();
        for item in qp {
            if item.starts_with("token=") {
                let t = item.trim_start_matches("token=");
                if let Some(srow) = sqlx::query!("SELECT node_id, expires_at FROM shares WHERE token = ?", t).fetch_optional(&data.share_db).await.expect("q") {
                    if srow.node_id == id {
                        // check expiry
                        if let Some(exp) = srow.expires_at {
                            if let Ok(exp_dt) = chrono::DateTime::parse_from_rfc3339(&exp) {
                                if exp_dt < chrono::Utc::now() { return Err(actix_web::error::ErrorNotFound("expired")); }
                            }
                        }
                        if let Some(row) = sqlx::query!("SELECT storage_path FROM nodes WHERE id = ?", id).fetch_optional(&data.db).await.expect("q") {
                            if let Some(sp) = row.storage_path {
                                let p = PathBuf::from(sp);
                                return Ok(NamedFile::open(p).await?);
                            }
                        }
                    }
                }
            }
        }
    }
    Err(actix_web::error::ErrorUnauthorized("unauthorized"))
}

async fn delete_node_handler(path: web::Path<(String,)>, data: web::Data<AppState>, req: HttpRequest) -> impl Responder {
    let owner = match auth_from_req(&req) { Some(u) => u, None => return HttpResponse::Unauthorized().body("no auth") };
    let id = path.into_inner().0;
    let row = sqlx::query!("SELECT owner_id, is_dir, storage_path FROM nodes WHERE id = ?", id).fetch_optional(&data.db).await.expect("q");
    if row.is_none() { return HttpResponse::NotFound().body("no"); }
    let row = row.unwrap();
    if row.owner_id != owner { return HttpResponse::Forbidden().body("forbidden"); }
    if row.is_dir != 0 {
        // delete children recursively - simple approach
        let mut to_delete = vec![id.clone()];
        while let Some(cur) = to_delete.pop() {
            let children = sqlx::query!("SELECT id, is_dir, storage_path FROM nodes WHERE parent_id = ?", cur).fetch_all(&data.db).await.expect("q");
            for c in children {
                if c.is_dir != 0 {
                    to_delete.push(c.id.clone());
                } else if let Some(sp) = c.storage_path {
                    let _ = std::fs::remove_file(sp);
                }
                sqlx::query!("DELETE FROM nodes WHERE id = ?", c.id).execute(&data.db).await.ok();
            }
            sqlx::query!("DELETE FROM nodes WHERE id = ?", cur).execute(&data.db).await.ok();
        }
    } else if let Some(sp) = row.storage_path {
        let _ = std::fs::remove_file(sp);
        sqlx::query!("DELETE FROM nodes WHERE id = ?", id).execute(&data.db).await.ok();
    } else {
        sqlx::query!("DELETE FROM nodes WHERE id = ?", id).execute(&data.db).await.ok();
    }
    HttpResponse::Ok().body("deleted")
}

#[derive(Deserialize)]
struct RenameReq { name: String }

async fn rename_node_handler(path: web::Path<(String,)>, data: web::Data<AppState>, req: HttpRequest, body: web::Json<RenameReq>) -> impl Responder {
    let owner = match auth_from_req(&req) { Some(u) => u, None => return HttpResponse::Unauthorized().body("no auth") };
    let id = path.into_inner().0;
    if let Some(row) = sqlx::query!("SELECT owner_id FROM nodes WHERE id = ?", id).fetch_optional(&data.db).await.expect("q") {
        if row.owner_id != owner { return HttpResponse::Forbidden().body("forbidden"); }
        sqlx::query!("UPDATE nodes SET name = ?, updated_at = ? WHERE id = ?", body.name, Utc::now().to_rfc3339(), id).execute(&data.db).await.ok();
        HttpResponse::Ok().body("ok")
    } else {
        HttpResponse::NotFound().body("no")
    }
}

#[derive(Deserialize)]
struct MoveReq { new_parent: Option<String> }

async fn move_node_handler(path: web::Path<(String,)>, data: web::Data<AppState>, req: HttpRequest, body: web::Json<MoveReq>) -> impl Responder {
    let owner = match auth_from_req(&req) { Some(u) => u, None => return HttpResponse::Unauthorized().body("no auth") };
    let id = path.into_inner().0;
    if let Some(row) = sqlx::query!("SELECT owner_id FROM nodes WHERE id = ?", id).fetch_optional(&data.db).await.expect("q") {
        if row.owner_id != owner { return HttpResponse::Forbidden().body("forbidden") }
        sqlx::query!("UPDATE nodes SET parent_id = ?, updated_at = ? WHERE id = ?", body.new_parent, Utc::now().to_rfc3339(), id).execute(&data.db).await.ok();
        HttpResponse::Ok().body("moved")
    } else {
        HttpResponse::NotFound().body("no")
    }
}

#[derive(Deserialize)]
struct ShareReq { read_only: Option<bool>, expires_seconds: Option<i64> }

async fn share_node_handler(path: web::Path<(String,)>, data: web::Data<AppState>, req: HttpRequest, body: web::Json<ShareReq>) -> impl Responder {
    let owner = match auth_from_req(&req) { Some(u) => u, None => return HttpResponse::Unauthorized().body("no auth") };
    let id = path.into_inner().0;
    if let Some(row) = sqlx::query!("SELECT owner_id FROM nodes WHERE id = ?", id).fetch_optional(&data.db).await.expect("q") {
        if row.owner_id != owner { return HttpResponse::Forbidden().body("forbidden") }
        let token = Uuid::new_v4().to_string();
        let sid = Uuid::new_v4().to_string();
        let expires_at = body.expires_seconds.map(|s| (Utc::now() + chrono::Duration::seconds(s)).to_rfc3339());
        sqlx::query!("INSERT INTO shares (id, node_id, token, read_only, expires_at) VALUES (?, ?, ?, ?, ?)",
            sid, id, token, body.read_only.unwrap_or(true) as i32, expires_at)
            .execute(&data.share_db).await.expect("ins share");
        return HttpResponse::Ok().json(serde_json::json!({ "token": token, "public_url": format!("/public/{}?token={}", id, token) }));
    }
    HttpResponse::NotFound().body("no")
}

async fn unshare_handler(path: web::Path<(String,)>, data: web::Data<AppState>, _req: HttpRequest) -> impl Responder {
    let token = path.into_inner().0;
    sqlx::query!("DELETE FROM shares WHERE token = ?", token).execute(&data.share_db).await.ok();
    HttpResponse::Ok().body("ok")
}

// public access by token
async fn public_handler(path: web::Path<(String,)>, data: web::Data<AppState>, req: HttpRequest) -> actix_web::Result<NamedFile> {
    let id = path.into_inner().0;
    // token in query
    let token_opt = req.query_string().split('&').find_map(|kv| {
        if kv.starts_with("token=") { Some(kv.trim_start_matches("token=").to_string()) } else { None }
    });
    if token_opt.is_none() { return Err(actix_web::error::ErrorUnauthorized("missing token")); }
    let token = token_opt.unwrap();
    if let Some(srow) = sqlx::query!("SELECT node_id, expires_at FROM shares WHERE token = ?", token).fetch_optional(&data.share_db).await.expect("q") {
        if srow.node_id != id { return Err(actix_web::error::ErrorUnauthorized("token mismatch")); }
        if let Some(exp) = srow.expires_at {
            if let Ok(exp_dt) = chrono::DateTime::parse_from_rfc3339(&exp) {
                if exp_dt < chrono::Utc::now() { return Err(actix_web::error::ErrorNotFound("expired")); }
            }
        }
        if let Some(row) = sqlx::query!("SELECT storage_path FROM nodes WHERE id = ?", id).fetch_optional(&data.db).await.expect("q") {
            if let Some(sp) = row.storage_path {
                let p = PathBuf::from(sp);
                return Ok(NamedFile::open(p).await?);
            }
        }
        return Err(actix_web::error::ErrorNotFound("not found"));
    }
    Err(actix_web::error::ErrorUnauthorized("invalid token"))
}

// ---------- Embedded Frontend HTML (vanilla JS) ----------
const INDEX_HTML: &str = r#"<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>Cloudrive (single binary)</title>
<style>
body{font-family: Arial, sans-serif; padding:20px}
.container{display:flex;gap:20px}
.box{border:1px solid #ccc;padding:12px;width:420px}
.file{border:1px solid #eee;padding:8px;margin:6px;background:#fafafa;cursor:grab}
.folder{font-weight:bold}
#tree{max-height:500px;overflow:auto}
.drag-over{outline:2px dashed #3b82f6}
</style>
</head>
<body>
<h1>Cloudrive — Demo</h1>
<p>注意：此演示用于本地测试，不建议生产直接使用。</p>
<div class="container">
  <div class="box">
    <h3>账号</h3>
    <div>
      <input id="reg_user" placeholder="用户名" /> <input id="reg_pass" type="password" placeholder="密码" />
      <button id="btn_reg">注册</button>
    </div>
    <div style="margin-top:8px">
      <input id="login_user" placeholder="用户名" /> <input id="login_pass" type="password" placeholder="密码" />
      <button id="btn_login">登录</button>
    </div>
    <div style="margin-top:8px">
      <button id="btn_logout">登出</button>
      <div id="who"></div>
    </div>
    <hr/>
    <h4>上传</h4>
    <input id="file_input" type="file" />
    <button id="btn_upload">上传</button>
    <div style="margin-top:8px">
      <label>目标文件夹 id (空为根):</label><input id="target_parent" />
    </div>
    <hr/>
    <h4>分享管理</h4>
    <div>
      分享 token: <input id="share_token" /> <button id="btn_unshare">取消分享</button>
    </div>
  </div>

  <div class="box">
    <h3>云盘</h3>
    <div>
      <button id="btn_refresh">刷新</button>
      <button id="btn_root">根目录</button>
      <div id="curpath">当前 parent: <span id="cur_parent">(root)</span></div>
    </div>
    <div id="tree"></div>
    <hr/>
    <div>
      <label>移动目标父 id: </label><input id="move_target" /> <button id="btn_move_select">选择并移动</button>
    </div>
  </div>
</div>

<script>
let TOKEN = null;
let USER_ID = null;
let CUR_PARENT = null; // null == root

function setStatus(){ document.getElementById('who').innerText = TOKEN ? ('已登录: '+USER_ID) : '未登录'; document.getElementById('cur_parent').innerText = CUR_PARENT || '(root)'; }

async function api(path, opts){
  opts = opts || {};
  opts.headers = opts.headers || {};
  if(TOKEN) opts.headers['Authorization'] = 'Bearer '+TOKEN;
  const res = await fetch('/api'+path, opts);
  return res;
}

document.getElementById('btn_reg').onclick = async ()=>{
  const u = document.getElementById('reg_user').value;
  const p = document.getElementById('reg_pass').value;
  const r = await api('/register', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:u,password:p}) });
  if(r.ok) alert('注册成功'); else alert('注册失败:'+await r.text());
};

document.getElementById('btn_login').onclick = async ()=>{
  const u = document.getElementById('login_user').value;
  const p = document.getElementById('login_pass').value;
  const r = await api('/login', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:u,password:p}) });
  if(r.ok){ const j = await r.json(); TOKEN = j.token; USER_ID = j.user_id; setStatus(); await refresh(); } else alert('登录失败:'+await r.text());
};

document.getElementById('btn_logout').onclick = ()=>{
  TOKEN = null; USER_ID = null; setStatus();
};

document.getElementById('btn_upload').onclick = async ()=>{
  const f = document.getElementById('file_input').files[0];
  if(!f){ alert('请选择文件'); return; }
  const form = new FormData();
  form.append('file', f);
  const pid = document.getElementById('target_parent').value;
  if(pid) form.append('parent_id', pid);
  const r = await api('/upload', { method:'POST', body: form });
  if(r.ok){ alert('上传成功'); await refresh(); } else alert('上传失败:'+await r.text());
};

document.getElementById('btn_refresh').onclick = refresh;
document.getElementById('btn_root').onclick = ()=>{ CUR_PARENT = null; setStatus(); refresh(); };

async function refresh(){
  setStatus();
  const q = CUR_PARENT ? ('?parent_id='+encodeURIComponent(CUR_PARENT)) : '';
  const r = await api('/list'+q, { method:'GET' });
  if(!r.ok){ alert('获取列表失败:'+await r.text()); return; }
  const items = await r.json();
  renderTree(items);
}

function renderTree(items){
  const tree = document.getElementById('tree'); tree.innerHTML = '';
  items.forEach(it=>{
    const d = document.createElement('div');
    d.className = 'file';
    d.draggable = true;
    d.dataset.id = it.id;
    d.innerHTML = '<span class="'+(it.is_dir? 'folder':'')+'">'+escapeHtml(it.name)+'</span> <small>('+(it.is_dir? '文件夹':'文件')+') id:'+it.id+')</small>';
    // buttons
    const btns = document.createElement('div');
    btns.style.marginTop = '6px';
    if(!it.is_dir){
      const dl = document.createElement('button'); dl.innerText = '下载'; dl.onclick = async ()=>{ await downloadItem(it); };
      btns.appendChild(dl);
    }
    const del = document.createElement('button'); del.innerText = '删除'; del.onclick = async ()=>{ if(confirm('删除?')){ await fetch('/api/delete/'+it.id, { method:'DELETE', headers: TOKEN?{'Authorization':'Bearer '+TOKEN}:{}}); await refresh(); } };
    const rn = document.createElement('button'); rn.innerText = '重命名'; rn.onclick = async ()=>{ const n = prompt('新名字', it.name); if(n) { await fetch('/api/rename/'+it.id, { method:'POST', headers: {'Content-Type':'application/json', ...(TOKEN?{'Authorization':'Bearer '+TOKEN}:{})}, body: JSON.stringify({name:n}) }); await refresh(); } };
    const mv = document.createElement('button'); mv.innerText = '移动到...'; mv.onclick = async ()=>{ const np = prompt('目标父 id (空为根)'); await fetch('/api/move/'+it.id, { method:'POST', headers: {'Content-Type':'application/json', ...(TOKEN?{'Authorization':'Bearer '+TOKEN}:{})}, body: JSON.stringify({new_parent: np || null}) }); await refresh(); };
    const sh = document.createElement('button'); sh.innerText = '分享'; sh.onclick = async ()=>{ const r = await fetch('/api/share/'+it.id, { method:'POST', headers: {'Content-Type':'application/json', ...(TOKEN?{'Authorization':'Bearer '+TOKEN}:{})}, body: JSON.stringify({read_only:true, expires_seconds:3600*24}) }); if(r.ok){ const j=await r.json(); alert('分享链接: '+(location.origin + j.public_url)); document.getElementById('share_token').value = j.token; } else alert('分享失败:'+await r.text()); };
    const open = document.createElement('button'); open.innerText='进入'; open.onclick = ()=>{ if(it.is_dir){ CUR_PARENT = it.id; setStatus(); refresh(); } else alert('不是文件夹'); };
    btns.appendChild(open); btns.appendChild(sh); btns.appendChild(mv); btns.appendChild(rn); btns.appendChild(del);
    d.appendChild(btns);

    // drag events
    d.addEventListener('dragstart', (e)=>{
      e.dataTransfer.setData('text/plain', it.id);
      d.style.opacity = '0.5';
    });
    d.addEventListener('dragend', (e)=>{ d.style.opacity = '1'; });

    // allow drop if folder
    if(it.is_dir){
      d.addEventListener('dragover', (e)=>{ e.preventDefault(); d.classList.add('drag-over'); });
      d.addEventListener('dragleave', (e)=>{ d.classList.remove('drag-over'); });
      d.addEventListener('drop', async (e)=>{ e.preventDefault(); d.classList.remove('drag-over'); const dragged = e.dataTransfer.getData('text/plain'); if(dragged){ await fetch('/api/move/'+dragged, { method:'POST', headers: {'Content-Type':'application/json', ...(TOKEN?{'Authorization':'Bearer '+TOKEN}:{})}, body: JSON.stringify({new_parent: it.id}) }); await refresh(); } });
    }

    tree.appendChild(d);
  });
}

async function downloadItem(it){
  const url = '/api/download/'+it.id;
  // try with token
  const headers = TOKEN ? {'Authorization':'Bearer '+TOKEN} : {};
  const res = await fetch(url, { headers });
  if(res.ok){
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = it.name;
    a.click();
    URL.revokeObjectURL(a.href);
  } else {
    alert('下载失败: '+await res.text());
  }
}

document.getElementById('btn_unshare').onclick = async ()=>{
  const t = document.getElementById('share_token').value;
  if(!t){ alert('请输入 token'); return; }
  await fetch('/api/unshare/'+t, { method:'DELETE' });
  alert('取消分享（如果 token 存在）');
};

document.getElementById('btn_move_select').onclick = async ()=>{
  const target = document.getElementById('move_target').value;
  const sel = prompt('要移动的 item id:');
  if(!sel) return;
  await fetch('/api/move/'+sel, { method:'POST', headers: {'Content-Type':'application/json', ...(TOKEN?{'Authorization':'Bearer '+TOKEN}:{})}, body: JSON.stringify({new_parent: target || null}) });
  await refresh();
};

function escapeHtml(s){ return s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }

setStatus();
refresh();
</script>
</body>
</html>
"#;

// ---------- Main ----------
#[actix_web::main]
async fn main() -> std::io::Result<()> {
    dotenvy::dotenv().ok();
    let storage_root = std::env::var("STORAGE_ROOT").unwrap_or_else(|_| "./data".into());
    fs::create_dir_all(&storage_root).ok();

    let db = init_db().await.expect("db init");
    let share_db = init_share_db().await.expect("share db init");

    // ensure root user? no
    let app_state = web::Data::new(AppState { db: db.clone(), share_db: share_db.clone(), storage_root: storage_root.clone() });

    println!("Starting server at http://127.0.0.1:8080");
    HttpServer::new(move || {
        App::new()
            .wrap(middleware::Logger::default())
            .app_data(app_state.clone())
            .service(web::resource("/").route(web::get().to(index)))
            .service(web::scope("/api")
                .route("/register", web::post().to(register_handler))
                .route("/login", web::post().to(login_handler))
                .route("/upload", web::post().to(upload_handler))
                .route("/list", web::get().to(list_nodes_handler))
                .route("/download/{id}", web::get().to(download_handler))
                .route("/delete/{id}", web::delete().to(delete_node_handler))
                .route("/rename/{id}", web::post().to(rename_node_handler))
                .route("/move/{id}", web::post().to(move_node_handler))
                .route("/share/{id}", web::post().to(share_node_handler))
                .route("/unshare/{token}", web::delete().to(unshare_handler))
            )
            .service(web::resource("/public/{id}").route(web::get().to(public_handler)))
    })
    .bind(("127.0.0.1", 8080))?
    .run()
    .await
}
