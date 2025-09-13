将以下整份源码保存为 main.go 并运行（需要 go mod init + go get 依赖： gorilla/mux、mattn/go-sqlite3、golang.org/x/crypto/bcrypt）。

package main

import (
	"archive/zip"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"html/template"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "github.com/mattn/go-sqlite3"
	"github.com/gorilla/mux"
	"golang.org/x/crypto/bcrypt"
)

// ========== Configuration ==========
const (
	baseDirectory   = "./storage"   // storage root dir
	maxUploadBytes  = 300 << 20     // 300 MB
	databaseFile    = "./data.db"   // sqlite file
	listenAddress   = ":8080"       // listen address
	tokenLength     = 24
	cookieName      = "session_user"
	templatePattern = "index"
)

// ========== Models ==========
type User struct {
	ID       int64
	Username string
	Password string // bcrypt hash
}

type Share struct {
	ID        int64     `json:"id"`
	Path      string    `json:"path"`
	OwnerID   int64     `json:"owner_id"`
	Token     string    `json:"token"`
	CreatedAt time.Time `json:"created_at"`
	Active    bool      `json:"active"`
}

// ========== Globals ==========
var sqldb *sql.DB
var tpl *template.Template

// ========== Utilities ==========
func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}

// safeJoin: prevents path traversal, returns absolute path inside baseDirectory
func safeJoin(base string, userPath string) (string, error) {
	cleanPath := filepath.Clean("/" + userPath) // ensure leading slash then clean
	full := filepath.Join(base, cleanPath)
	absBase, err := filepath.Abs(base)
	if err != nil {
		return "", err
	}
	absFull, err := filepath.Abs(full)
	if err != nil {
		return "", err
	}
	if !strings.HasPrefix(absFull, absBase) {
		return "", errors.New("invalid path")
	}
	return absFull, nil
}

// copyFile helper used for cross-fs moves
func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	return out.Sync()
}

// generateToken: simple token (for demo). Replace with crypto/rand in prod.
func generateToken(n int) string {
	t := fmt.Sprintf("%x", time.Now().UnixNano())
	if len(t) >= n {
		return t[:n]
	}
	for len(t) < n {
		t += "0"
	}
	return t[:n]
}

// getCurrentUser: simple cookie-based session (session stores username)
func getCurrentUser(r *http.Request) (*User, error) {
	cookie, err := r.Cookie(cookieName)
	if err != nil {
		return nil, errors.New("not logged in")
	}
	username := cookie.Value
	u := &User{}
	row := sqldb.QueryRow("SELECT id, username, password FROM users WHERE username = ?", username)
	if err := row.Scan(&u.ID, &u.Username, &u.Password); err != nil {
		return nil, errors.New("user not found")
	}
	return u, nil
}

// zipDirectory writes a zip stream of dirPath (relative base) to writer
func zipDirectory(writer io.Writer, rootPath string) error {
	zipWriter := zip.NewWriter(writer)
	defer zipWriter.Close()

	return filepath.Walk(rootPath, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		// compute zip path relative to rootPath
		rel, err := filepath.Rel(rootPath, path)
		if err != nil {
			return err
		}
		// skip root
		if rel == "." {
			return nil
		}
		zipPath := filepath.ToSlash(rel)
		if info.IsDir() {
			_, err := zipWriter.Create(zipPath + "/")
			return err
		}
		f, err := os.Open(path)
		if err != nil {
			return err
		}
		defer f.Close()
		w, err := zipWriter.Create(zipPath)
		if err != nil {
			return err
		}
		_, err = io.Copy(w, f)
		return err
	})
}

// ========== DB Init ==========
func initStorageAndDB() error {
	if err := os.MkdirAll(baseDirectory, 0755); err != nil {
		return err
	}
	var err error
	sqldb, err = sql.Open("sqlite3", databaseFile)
	if err != nil {
		return err
	}
	createUsers := `
	CREATE TABLE IF NOT EXISTS users (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		username TEXT UNIQUE NOT NULL,
		password TEXT NOT NULL
	);`
	createShares := `
	CREATE TABLE IF NOT EXISTS shares (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		path TEXT NOT NULL,
		owner_id INTEGER NOT NULL,
		token TEXT UNIQUE NOT NULL,
		created_at DATETIME NOT NULL,
		active INTEGER NOT NULL DEFAULT 1,
		FOREIGN KEY(owner_id) REFERENCES users(id)
	);`
	if _, err := sqldb.Exec(createUsers); err != nil {
		return err
	}
	if _, err := sqldb.Exec(createShares); err != nil {
		return err
	}
	return nil
}

// ========== Handlers & API ==========
func serveIndex(w http.ResponseWriter, r *http.Request) {
	data := map[string]interface{}{}
	tpl.ExecuteTemplate(w, templatePattern, data)
}

// API: register
func apiRegister(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	if strings.TrimSpace(body.Username) == "" || body.Password == "" {
		http.Error(w, "username/password required", http.StatusBadRequest)
		return
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(body.Password), bcrypt.DefaultCost)
	if err != nil {
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	_, err = sqldb.Exec("INSERT INTO users (username, password) VALUES (?, ?)", body.Username, string(hash))
	if err != nil {
		http.Error(w, "username exists or db error", http.StatusBadRequest)
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name:  cookieName,
		Value: body.Username,
		Path:  "/",
	})
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(map[string]string{"username": body.Username})
}

// API: login
func apiLogin(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	u := &User{}
	row := sqldb.QueryRow("SELECT id, username, password FROM users WHERE username = ?", body.Username)
	if err := row.Scan(&u.ID, &u.Username, &u.Password); err != nil {
		http.Error(w, "invalid credentials", http.StatusUnauthorized)
		return
	}
	if err := bcrypt.CompareHashAndPassword([]byte(u.Password), []byte(body.Password)); err != nil {
		http.Error(w, "invalid credentials", http.StatusUnauthorized)
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name:  cookieName,
		Value: u.Username,
		Path:  "/",
	})
	json.NewEncoder(w).Encode(map[string]string{"username": u.Username})
}

// API: logout
func apiLogout(w http.ResponseWriter, r *http.Request) {
	http.SetCookie(w, &http.Cookie{
		Name:   cookieName,
		Value:  "",
		Path:   "/",
		MaxAge: -1,
	})
	w.WriteHeader(http.StatusOK)
}

// API: upload (supports multiple files). query param path for directory
func apiUpload(w http.ResponseWriter, r *http.Request) {
	_, err := getCurrentUser(r)
	if err != nil {
		http.Error(w, "unauthenticated", http.StatusUnauthorized)
		return
	}
	dirParam := r.URL.Query().Get("path")
	if dirParam == "" {
		dirParam = "/"
	}
	if err := r.ParseMultipartForm(maxUploadBytes); err != nil {
		http.Error(w, "could not parse multipart form", http.StatusBadRequest)
		return
	}
	form := r.MultipartForm
	files := form.File["files"]
	// allow field name "file" as single
	if len(files) == 0 {
		if f, _, ferr := r.FormFile("file"); ferr == nil {
			f.Close()
			http.Error(w, "use field name 'files' for multiple uploads", http.StatusBadRequest)
			return
		}
		http.Error(w, "no files", http.StatusBadRequest)
		return
	}
	targetDir, err := safeJoin(baseDirectory, dirParam)
	if err != nil {
		http.Error(w, "invalid path", http.StatusBadRequest)
		return
	}
	if err := os.MkdirAll(targetDir, 0755); err != nil {
		http.Error(w, "cannot create dir", http.StatusInternalServerError)
		return
	}
	var saved []string
	for _, fh := range files {
		src, err := fh.Open()
		if err != nil {
			continue
		}
		dstPath := filepath.Join(targetDir, filepath.Base(fh.Filename))
		out, err := os.Create(dstPath)
		if err != nil {
			src.Close()
			continue
		}
		io.Copy(out, src)
		out.Close()
		src.Close()
		rel := strings.TrimPrefix(strings.TrimPrefix(dstPath, baseDirectory), "/")
		saved = append(saved, rel)
	}
	json.NewEncoder(w).Encode(map[string]interface{}{"saved": saved})
}

// API: list directory
func apiList(w http.ResponseWriter, r *http.Request) {
	pathParam := r.URL.Query().Get("path")
	if pathParam == "" {
		pathParam = "/"
	}
	targetPath, err := safeJoin(baseDirectory, pathParam)
	if err != nil {
		http.Error(w, "invalid path", http.StatusBadRequest)
		return
	}
	entries, err := os.ReadDir(targetPath)
	if err != nil {
		http.Error(w, "cannot read dir", http.StatusInternalServerError)
		return
	}
	type Entry struct {
		Name  string `json:"name"`
		IsDir bool   `json:"is_dir"`
		Size  int64  `json:"size"`
	}
	var out []Entry
	for _, e := range entries {
		info, _ := e.Info()
		out = append(out, Entry{
			Name:  e.Name(),
			IsDir: e.IsDir(),
			Size:  info.Size(),
		})
	}
	json.NewEncoder(w).Encode(out)
}

// API: download by path query param
func apiDownload(w http.ResponseWriter, r *http.Request) {
	fileParam := r.URL.Query().Get("path")
	if fileParam == "" {
		http.Error(w, "path required", http.StatusBadRequest)
		return
	}
	targetPath, err := safeJoin(baseDirectory, fileParam)
	if err != nil {
		http.Error(w, "invalid path", http.StatusBadRequest)
		return
	}
	info, err := os.Stat(targetPath)
	if err != nil {
		http.Error(w, "file not found", http.StatusNotFound)
		return
	}
	if info.IsDir() {
		// stream as zip
		w.Header().Set("Content-Disposition", "attachment; filename=\""+filepath.Base(targetPath)+".zip\"")
		w.Header().Set("Content-Type", "application/zip")
		if err := zipDirectory(w, targetPath); err != nil {
			http.Error(w, "zip error", http.StatusInternalServerError)
		}
		return
	}
	f, err := os.Open(targetPath)
	if err != nil {
		http.Error(w, "cannot open", http.StatusInternalServerError)
		return
	}
	defer f.Close()
	w.Header().Set("Content-Disposition", "attachment; filename=\""+filepath.Base(targetPath)+"\"")
	http.ServeContent(w, r, filepath.Base(targetPath), info.ModTime(), f)
}

// API: rename {path, new_name}
func apiRename(w http.ResponseWriter, r *http.Request) {
	_, err := getCurrentUser(r)
	if err != nil {
		http.Error(w, "unauthenticated", http.StatusUnauthorized)
		return
	}
	var body struct {
		Path    string `json:"path"`
		NewName string `json:"new_name"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	if body.Path == "" || body.NewName == "" {
		http.Error(w, "path/new_name required", http.StatusBadRequest)
		return
	}
	oldPath, err := safeJoin(baseDirectory, body.Path)
	if err != nil {
		http.Error(w, "invalid path", http.StatusBadRequest)
		return
	}
	dir := filepath.Dir(oldPath)
	newPath := filepath.Join(dir, filepath.Base(body.NewName))
	// compute relative portion to pass to safeJoin
	newRel := strings.TrimPrefix(newPath, baseDirectory)
	newPathClean, err := safeJoin(baseDirectory, newRel)
	if err != nil {
		http.Error(w, "invalid new name", http.StatusBadRequest)
		return
	}
	if err := os.Rename(oldPath, newPathClean); err != nil {
		http.Error(w, "rename failed", http.StatusInternalServerError)
		return
	}
	json.NewEncoder(w).Encode(map[string]string{"old": body.Path, "new": filepath.Join(filepath.Dir(body.Path), filepath.Base(body.NewName))})
}

// API: delete {path}
func apiDelete(w http.ResponseWriter, r *http.Request) {
	_, err := getCurrentUser(r)
	if err != nil {
		http.Error(w, "unauthenticated", http.StatusUnauthorized)
		return
	}
	var body struct {
		Path string `json:"path"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	if body.Path == "" {
		http.Error(w, "path required", http.StatusBadRequest)
		return
	}
	targetPath, err := safeJoin(baseDirectory, body.Path)
	if err != nil {
		http.Error(w, "invalid path", http.StatusBadRequest)
		return
	}
	info, err := os.Stat(targetPath)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	if info.IsDir() {
		// try remove (only empty) for safety
		if err := os.Remove(targetPath); err != nil {
			http.Error(w, "delete dir failed (non-empty?)", http.StatusInternalServerError)
			return
		}
	} else {
		if err := os.Remove(targetPath); err != nil {
			http.Error(w, "delete file failed", http.StatusInternalServerError)
			return
		}
	}
	json.NewEncoder(w).Encode(map[string]string{"deleted": body.Path})
}

// API: move {src, dst} dst can be dir ending with / or full target
func apiMove(w http.ResponseWriter, r *http.Request) {
	_, err := getCurrentUser(r)
	if err != nil {
		http.Error(w, "unauthenticated", http.StatusUnauthorized)
		return
	}
	var body struct {
		Src string `json:"src"`
		Dst string `json:"dst"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	if body.Src == "" || body.Dst == "" {
		http.Error(w, "src/dst required", http.StatusBadRequest)
		return
	}
	srcPath, err := safeJoin(baseDirectory, body.Src)
	if err != nil {
		http.Error(w, "invalid src", http.StatusBadRequest)
		return
	}
	dstCandidate := body.Dst
	if strings.HasSuffix(dstCandidate, "/") {
		dstCandidate = filepath.Join(dstCandidate, filepath.Base(srcPath))
	}
	dstPath, err := safeJoin(baseDirectory, dstCandidate)
	if err != nil {
		http.Error(w, "invalid dst", http.StatusBadRequest)
		return
	}
	if err := os.MkdirAll(filepath.Dir(dstPath), 0755); err != nil {
		http.Error(w, "cannot create dst dir", http.StatusInternalServerError)
		return
	}
	if err := os.Rename(srcPath, dstPath); err != nil {
		// fallback copy+delete
		if info, ferr := os.Stat(srcPath); ferr == nil && !info.IsDir() {
			if err := copyFile(srcPath, dstPath); err != nil {
				http.Error(w, "move failed", http.StatusInternalServerError)
				return
			}
			if err := os.Remove(srcPath); err != nil {
				http.Error(w, "cleanup failed", http.StatusInternalServerError)
				return
			}
		} else {
			// for directories, use os.Rename only (copy recursive not implemented)
			http.Error(w, "move failed (directory move across filesystems not supported)", http.StatusInternalServerError)
			return
		}
	}
	relDst := strings.TrimPrefix(dstPath, baseDirectory)
	relDst = strings.TrimPrefix(relDst, "/")
	json.NewEncoder(w).Encode(map[string]string{"src": body.Src, "dst": relDst})
}

// API: share create {path} -- allows file or directory
func apiShareCreate(w http.ResponseWriter, r *http.Request) {
	user, err := getCurrentUser(r)
	if err != nil {
		http.Error(w, "unauthenticated", http.StatusUnauthorized)
		return
	}
	var body struct {
		Path string `json:"path"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Path == "" {
		http.Error(w, "path required", http.StatusBadRequest)
		return
	}
	targetPath, err := safeJoin(baseDirectory, body.Path)
	if err != nil {
		http.Error(w, "invalid path", http.StatusBadRequest)
		return
	}
	// ensure exists
	if _, err := os.Stat(targetPath); err != nil {
		http.Error(w, "file or directory not found", http.StatusBadRequest)
		return
	}
	token := generateToken(tokenLength)
	now := time.Now()
	_, err = sqldb.Exec("INSERT INTO shares (path, owner_id, token, created_at, active) VALUES (?, ?, ?, ?, 1)", strings.TrimPrefix(body.Path, "/"), user.ID, token, now)
	if err != nil {
		http.Error(w, "cannot create share", http.StatusInternalServerError)
		return
	}
	json.NewEncoder(w).Encode(map[string]interface{}{"token": token, "path": body.Path, "created_at": now})
}

// API: share cancel {token or id}
func apiShareCancel(w http.ResponseWriter, r *http.Request) {
	user, err := getCurrentUser(r)
	if err != nil {
		http.Error(w, "unauthenticated", http.StatusUnauthorized)
		return
	}
	var body map[string]interface{}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	if token, ok := body["token"].(string); ok && token != "" {
		res, err := sqldb.Exec("UPDATE shares SET active = 0 WHERE token = ? AND owner_id = ?", token, user.ID)
		if err != nil {
			http.Error(w, "db error", http.StatusInternalServerError)
			return
		}
		ra, _ := res.RowsAffected()
		json.NewEncoder(w).Encode(map[string]int64{"updated": ra})
		return
	}
	if idFloat, ok := body["id"].(float64); ok {
		id := int64(idFloat)
		res, err := sqldb.Exec("UPDATE shares SET active = 0 WHERE id = ? AND owner_id = ?", id, user.ID)
		if err != nil {
			http.Error(w, "db error", http.StatusInternalServerError)
			return
		}
		ra, _ := res.RowsAffected()
		json.NewEncoder(w).Encode(map[string]int64{"updated": ra})
		return
	}
	http.Error(w, "token or id required", http.StatusBadRequest)
}

// API: share list for current user
func apiShareList(w http.ResponseWriter, r *http.Request) {
	user, err := getCurrentUser(r)
	if err != nil {
		http.Error(w, "unauthenticated", http.StatusUnauthorized)
		return
	}
	rows, err := sqldb.Query("SELECT id, path, token, created_at, active FROM shares WHERE owner_id = ? ORDER BY created_at DESC", user.ID)
	if err != nil {
		http.Error(w, "db error", http.StatusInternalServerError)
		return
	}
	defer rows.Close()
	var list []Share
	for rows.Next() {
		var s Share
		var created string
		var activeInt int
		if err := rows.Scan(&s.ID, &s.Path, &s.Token, &created, &activeInt); err != nil {
			continue
		}
		tm, _ := time.Parse("2006-01-02 15:04:05", created)
		s.CreatedAt = tm
		s.Active = activeInt == 1
		list = append(list, s)
	}
	json.NewEncoder(w).Encode(list)
}

// API: public download by token (file or directory)
func apiPublicDownload(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	token := vars["token"]
	row := sqldb.QueryRow("SELECT path, active FROM shares WHERE token = ?", token)
	var path string
	var activeInt int
	if err := row.Scan(&path, &activeInt); err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	if activeInt != 1 {
		http.Error(w, "share not active", http.StatusGone)
		return
	}
	targetPath, err := safeJoin(baseDirectory, path)
	if err != nil {
		http.Error(w, "invalid path", http.StatusInternalServerError)
		return
	}
	info, err := os.Stat(targetPath)
	if err != nil {
		http.Error(w, "file not found", http.StatusNotFound)
		return
	}
	if info.IsDir() {
		w.Header().Set("Content-Disposition", "attachment; filename=\""+filepath.Base(targetPath)+".zip\"")
		w.Header().Set("Content-Type", "application/zip")
		if err := zipDirectory(w, targetPath); err != nil {
			http.Error(w, "zip error", http.StatusInternalServerError)
		}
		return
	}
	f, err := os.Open(targetPath)
	if err != nil {
		http.Error(w, "cannot open", http.StatusInternalServerError)
		return
	}
	defer f.Close()
	w.Header().Set("Content-Disposition", "attachment; filename=\""+filepath.Base(targetPath)+"\"")
	http.ServeContent(w, r, filepath.Base(targetPath), info.ModTime(), f)
}

// ========== Templates (single HTML with embedded JS & Bootstrap) ==========
const indexHTML = `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>File Manager</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding: 20px; background:#f8f9fa; }
    .file-item { padding: 10px; border-bottom: 1px solid #e9ecef; cursor: pointer; }
    .directory { font-weight: 700; color:#0d6efd; }
    .drop-target { background: #fff3cd; border: 1px dashed #ffc107; }
    .modal-backdrop-custom { position: fixed; inset:0; background: rgba(0,0,0,0.5); display:flex; align-items:center; justify-content:center; }
    .modal-custom { background:white; border-radius:8px; max-width:900px; width:90%; padding:18px; }
    .small-muted { font-size:0.85rem; color:#6c757d; }
  </style>
</head>
<body>
<div class="container">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h3 class="m-0">File Manager</h3>
    <div id="userInfo"></div>
  </div>

  <div class="card mb-3 shadow-sm">
    <div class="card-body">
      <div class="row g-2">
        <div class="col-md-3">
          <input id="username" class="form-control" placeholder="username">
        </div>
        <div class="col-md-3">
          <input id="password" type="password" class="form-control" placeholder="password">
        </div>
        <div class="col-md-6 text-end">
          <button id="btnRegister" class="btn btn-outline-primary me-1">Register</button>
          <button id="btnLogin" class="btn btn-primary me-1">Login</button>
          <button id="btnLogout" class="btn btn-secondary me-1">Logout</button>
          <button id="linkShares" class="btn btn-info">My Shares</button>
        </div>
      </div>
    </div>
  </div>

  <div class="row g-3 mb-3">
    <div class="col-md-8">
      <input id="currentPath" class="form-control" value="/" />
    </div>
    <div class="col-md-4 text-end">
      <input id="fileInput" type="file" multiple class="form-control d-inline-block w-auto" />
      <button id="btnUpload" class="btn btn-success">Upload</button>
      <button id="btnRefresh" class="btn btn-outline-secondary">Refresh</button>
    </div>
  </div>

  <div class="card mb-3 shadow-sm">
    <div class="card-body" id="browser" style="min-height:260px;">
      <div id="fileList" class="list-group"></div>
    </div>
  </div>

  <div class="card p-3 shadow-sm">
    <div class="row g-2 align-items-center">
      <div class="col-md-4">
        <input id="targetName" class="form-control" placeholder="select item or enter name">
      </div>
      <div class="col-md-8 text-end">
        <button id="btnDownload" class="btn btn-outline-primary me-1">Download</button>
        <button id="btnRename" class="btn btn-outline-warning me-1">Rename</button>
        <button id="btnDelete" class="btn btn-outline-danger me-1">Delete</button>
        <button id="btnMove" class="btn btn-outline-secondary me-1">Move</button>
        <button id="btnShare" class="btn btn-outline-info">Share</button>
      </div>
    </div>
  </div>
</div>

<div id="shareModal" style="display:none;"></div>

<script>
/* Frontend logic */
async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || res.statusText);
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res.text();
}

function setUserInfo(text) {
  document.getElementById('userInfo').innerHTML = text ? ('<span class="badge bg-success">User: '+text+'</span>') : '';
}

document.getElementById('btnRegister').onclick = async () => {
  const username = document.getElementById('username').value;
  const password = document.getElementById('password').value;
  try {
    await api('/api/register', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username,password}) });
    setUserInfo(username);
    alert('registered & logged in');
  } catch (e) { alert(e.message) }
};
document.getElementById('btnLogin').onclick = async () => {
  const username = document.getElementById('username').value;
  const password = document.getElementById('password').value;
  try {
    await api('/api/login', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username,password}) });
    setUserInfo(username);
    alert('logged in');
  } catch (e) { alert(e.message) }
};
document.getElementById('btnLogout').onclick = async () => {
  await fetch('/api/logout', { method:'POST' });
  setUserInfo('');
  alert('logged out');
};

document.getElementById('linkShares').onclick = (e) => {
  e.preventDefault();
  loadSharesModal();
};

async function listPath() {
  const path = document.getElementById('currentPath').value || '/';
  try {
    const data = await api('/api/list?path=' + encodeURIComponent(path));
    const ul = document.getElementById('fileList');
    ul.innerHTML = '';
    data.forEach(e => {
      const div = document.createElement('div');
      div.className = 'list-group-item file-item d-flex justify-content-between align-items-center';
      if (e.is_dir) div.classList.add('directory');
      div.draggable = true;
      div.dataset.name = e.name;
      div.dataset.isdir = e.is_dir;
      div.innerHTML = '<div><span>' + (e.is_dir ? '📁 ' : '📄 ') + e.name + (e.is_dir ? '' : ' <small class="small-muted">(' + e.size + ' bytes)</small>') + '</span></div>' +
                      '<div><button class="btn btn-sm btn-link select-btn">Select</button></div>';
      div.querySelector('.select-btn').onclick = () => {
        document.getElementById('targetName').value = e.name;
      };
      div.ondblclick = async () => {
        if (e.is_dir) {
          let cur = document.getElementById('currentPath').value || '/';
          cur = (cur + '/' + e.name).replace(/\/+/g,'/');
          document.getElementById('currentPath').value = cur;
          await listPath();
        } else {
          const cur = document.getElementById('currentPath').value || '/';
          window.location = '/api/download?path=' + encodeURIComponent((cur + '/' + e.name).replace(/\/+/g,'/'));
        }
      };
      div.addEventListener('dragstart', (ev) => {
        ev.dataTransfer.setData('text/plain', JSON.stringify({name: e.name, isDir: e.is_dir}));
      });
      div.addEventListener('dragover', (ev) => ev.preventDefault());
      div.addEventListener('drop', async (ev) => {
        ev.preventDefault();
        const src = JSON.parse(ev.dataTransfer.getData('text/plain'));
        const cur = document.getElementById('currentPath').value || '/';
        const srcPath = (cur + '/' + src.name).replace(/\/+/g,'/');
        const dstPath = (cur + '/' + e.name + '/').replace(/\/+/g,'/');
        try {
          await api('/api/move', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({src: srcPath, dst: dstPath}) });
          listPath();
        } catch (err) { alert(err.message) }
      });
      ul.appendChild(div);
    });
  } catch (err) {
    alert(err.message);
  }
}

document.getElementById('btnRefresh').onclick = listPath;

document.getElementById('btnUpload').onclick = async () => {
  const input = document.getElementById('fileInput');
  if (!input.files.length) { alert('select files'); return; }
  const path = document.getElementById('currentPath').value || '/';
  const form = new FormData();
  for (let i=0;i<input.files.length;i++) form.append('files', input.files[i]);
  const res = await fetch('/api/upload?path=' + encodeURIComponent(path), { method:'POST', body: form });
  if (!res.ok) { alert(await res.text()); return; }
  alert('uploaded');
  listPath();
};

document.getElementById('btnDownload').onclick = () => {
  const sel = document.getElementById('targetName').value;
  if (!sel) { alert('select item'); return; }
  const cur = document.getElementById('currentPath').value || '/';
  window.location = '/api/download?path=' + encodeURIComponent((cur + '/' + sel).replace(/\/+/g,'/'));
};

document.getElementById('btnRename').onclick = async () => {
  const sel = document.getElementById('targetName').value;
  const newName = prompt('New name for ' + sel);
  if (!sel || !newName) return;
  const cur = document.getElementById('currentPath').value || '/';
  const path = (cur + '/' + sel).replace(/\/+/g,'/');
  try {
    await api('/api/rename', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path, new_name: newName}) });
    listPath();
  } catch (e) { alert(e.message) }
};

document.getElementById('btnDelete').onclick = async () => {
  const sel = document.getElementById('targetName').value;
  if (!sel) { alert('select item'); return; }
  if (!confirm('Delete ' + sel + '?')) return;
  const cur = document.getElementById('currentPath').value || '/';
  const path = (cur + '/' + sel).replace(/\/+/g,'/');
  try {
    await api('/api/delete', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path}) });
    listPath();
  } catch (e) { alert(e.message) }
};

document.getElementById('btnMove').onclick = async () => {
  const sel = document.getElementById('targetName').value;
  const target = prompt('Move to (target dir) e.g. /new/dir/');
  if (!sel || !target) return;
  const cur = document.getElementById('currentPath').value || '/';
  const src = (cur + '/' + sel).replace(/\/+/g,'/');
  try {
    await api('/api/move', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({src, dst: target}) });
    listPath();
  } catch (e) { alert(e.message) }
};

document.getElementById('btnShare').onclick = async () => {
  const sel = document.getElementById('targetName').value;
  if (!sel) { alert('select file or directory'); return; }
  const cur = document.getElementById('currentPath').value || '/';
  const path = (cur + '/' + sel).replace(/\/+/g,'/');
  try {
    const res = await api('/api/share/create', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({path}) });
    alert('Share created. Token: ' + res.token + '\nPublic URL: ' + location.origin + '/public/' + res.token);
  } catch (e) { alert(e.message) }
};

// Shares modal and list
async function loadSharesModal() {
  try {
    const list = await api('/api/share/list');
    let html = '<div class="modal-backdrop-custom"><div class="modal-custom">';
    html += '<div class="d-flex justify-content-between align-items-center mb-2"><h5 class="m-0">My Shares</h5><button class="btn btn-sm btn-outline-secondary" onclick="closeModal()">Close</button></div>';
    if (!list.length) html += '<p>No shares</p>';
    else {
      html += '<ul class="list-group">';
      list.forEach(s => {
        html += '<li class="list-group-item d-flex justify-content-between align-items-center">';
        html += '<div><strong>' + s.path + '</strong><br/><small class="small-muted">token: ' + s.token + ' created: ' + s.created_at + ' active: ' + s.active + '</small></div>';
        html += '<div><a class="btn btn-sm btn-primary me-2" href="/public/' + s.token + '" target="_blank">Download</a>';
        html += '<button class="btn btn-sm btn-danger" onclick="cancelShare(\\'' + s.token + '\\')">Cancel</button></div></li>';
      });
      html += '</ul>';
    }
    html += '</div></div>';
    document.getElementById('shareModal').innerHTML = html;
    document.getElementById('shareModal').style.display = 'block';
  } catch (e) { alert(e.message) }
}
function closeModal() { document.getElementById('shareModal').style.display = 'none'; document.getElementById('shareModal').innerHTML = ''; }
async function cancelShare(token) {
  if (!confirm('Cancel share?')) return;
  try {
    await api('/api/share/cancel', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({token}) });
    loadSharesModal();
  } catch (e) { alert(e.message) }
}

// initial load and try to set username display if cookie present
(function init() {
  listPath();
  const cookies = document.cookie.split(';').map(s => s.trim());
  for (let c of cookies) {
    if (c.startsWith('session_user=')) {
      setUserInfo(c.split('=')[1]);
    }
  }
})();
</script>
</body>
</html>
`

// ========== Main ==========
func main() {
	// init
	if err := initStorageAndDB(); err != nil {
		log.Fatal(err)
	}
	defer sqldb.Close()

	tpl = template.Must(template.New(templatePattern).Parse(indexHTML))

	r := mux.NewRouter()
	// Serve UI
	r.HandleFunc("/", serveIndex).Methods("GET")

	// APIs
	r.HandleFunc("/api/register", apiRegister).Methods("POST")
	r.HandleFunc("/api/login", apiLogin).Methods("POST")
	r.HandleFunc("/api/logout", apiLogout).Methods("POST")

	r.HandleFunc("/api/upload", apiUpload).Methods("POST")
	r.HandleFunc("/api/list", apiList).Methods("GET")
	r.HandleFunc("/api/download", apiDownload).Methods("GET")
	r.HandleFunc("/api/rename", apiRename).Methods("POST")
	r.HandleFunc("/api/delete", apiDelete).Methods("POST")
	r.HandleFunc("/api/move", apiMove).Methods("POST")

	r.HandleFunc("/api/share/create", apiShareCreate).Methods("POST")
	r.HandleFunc("/api/share/cancel", apiShareCancel).Methods("POST")
	r.HandleFunc("/api/share/list", apiShareList).Methods("GET")
	r.HandleFunc("/public/{token}", apiPublicDownload).Methods("GET")

	log.Println("Listening on", listenAddress)
	if err := http.ListenAndServe(listenAddress, r); err != nil {
		log.Fatal(err)
	}
}
