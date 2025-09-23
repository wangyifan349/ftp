# app.py
"""
Single-file Flask notes app (English names).
Features:
- User registration/login (Flask-Login)
- Per-user notes CRUD (create/read/update/delete)
- Robust DB handling with SQLAlchemy transactions
- Search: uses SQLite FTS5 if available, otherwise falls back to LIKE (safe)
- Markdown rendering (safe) for display; client-side preview with marked.js
- Bootstrap 5 UI (templates saved to files by developer)
- All backend names in English
"""
import os
from datetime import datetime
from contextlib import contextmanager
from flask import (
    Flask, render_template, redirect, url_for, flash,
    request, abort, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Email, EqualTo
from werkzeug.security import generate_password_hash, check_password_hash
from markupsafe import Markup, escape
import markdown
# --- Configuration ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'notes.db')
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f"sqlite:///{DB_PATH}")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'templates'), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'static'), exist_ok=True)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'
# --- Models ---
class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.relationship('Note', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
class Note(db.Model):
    __tablename__ = 'note'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False, index=True)
    body = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
# --- Forms ---
class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(3,80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(6,128)])
    confirm = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')
class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')
class NoteForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(1,255)])
    body = TextAreaField('Body (Markdown)')
    submit = SubmitField('Save')
# --- DB Utilities ---
@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    session = db.session
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def supports_fts5():
    """Return True if SQLite has FTS5 support."""
    if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        return False
    try:
        with db.engine.connect() as conn:
            res = conn.execute(text("SELECT sqlite_version()")).fetchone()
            # try create virtual table in temp; cleanup after
            conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS temp.test_fts USING fts5(content)"))
            conn.execute(text("DROP TABLE IF EXISTS temp.test_fts"))
            return True
    except OperationalError:
        return False
    except Exception:
        return False
# If using SQLite, optionally create FTS virtual table for notes
USE_FTS = supports_fts5()
def create_fts_table():
    if not USE_FTS:
        return
    # create FTS table that indexes title and body, with content='note' to keep in sync
    try:
        with db.engine.begin() as conn:
            conn.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
                  title, body, content='note', content_rowid='id'
                );
            """))
            # populate missing rows
            conn.execute(text("""
                INSERT INTO note_fts(rowid, title, body)
                SELECT id, title, body FROM note
                WHERE id NOT IN (SELECT rowid FROM note_fts);
            """))
    except Exception:
        pass
# Keep FTS table in sync via triggers (only for SQLite + FTS5)
def create_fts_triggers():
    if not USE_FTS:
        return
    try:
        with db.engine.begin() as conn:
            conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS note_ai AFTER INSERT ON note BEGIN
              INSERT INTO note_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
            END;
            """))
            conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS note_ad AFTER DELETE ON note BEGIN
              INSERT INTO note_fts(note_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body);
            END;
            """))
            conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS note_au AFTER UPDATE ON note BEGIN
              INSERT INTO note_fts(note_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body);
              INSERT INTO note_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
            END;
            """))
    except Exception:
        pass
# --- App Initialization ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
@app.before_first_request
def initialize_database():
    db.create_all()
    create_fts_table()
    create_fts_triggers()
# --- Helpers ---
def render_markdown_safe(text: str) -> Markup:
    """Render markdown to HTML; escape input first to avoid raw HTML injection except allowed."""
    if not text:
        return Markup('')
    # escape raw HTML, then convert markdown -> HTML
    escaped = escape(text)
    html = markdown.markdown(escaped, extensions=['extra', 'codehilite'])
    return Markup(html)
# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = RegisterForm()
    if form.validate_on_submit():
        with session_scope() as s:
            exists = s.query(User).filter(
                (User.username == form.username.data) | (User.email == form.email.data)
            ).first()
            if exists:
                flash('Username or email already exists.', 'warning')
                return redirect(url_for('register'))
            user = User(username=form.username.data, email=form.email.data)
            user.set_password(form.password.data)
            s.add(user)
        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('auth.html', form=form, title='Register', show_email=True, show_confirm=True)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash('Logged in.', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('auth.html', form=form, title='Login', show_email=False, show_confirm=False)
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'info')
    return redirect(url_for('index'))
@app.route('/dashboard')
@login_required
def dashboard():
    q = request.args.get('q', '').strip()
    notes = []
    if q:
        # If FTS available, use match query for better relevance
        if USE_FTS:
            # Use parameterized query to avoid injection
            sql = text("""
                SELECT n.*
                FROM note n
                JOIN note_fts f ON f.rowid = n.id
                WHERE note_fts MATCH :term AND n.user_id = :uid
                ORDER BY n.updated_at DESC
            """)
            param = {'term': q, 'uid': current_user.id}
            with db.engine.connect() as conn:
                result = conn.execute(sql, param)
                notes = [Note(**dict(row)) for row in result.mappings()]
        else:
            # Fallback: safe LIKE with parameterization (case-insensitive)
            like = f"%{q}%"
            notes = Note.query.filter(Note.user_id==current_user.id).filter(
                (Note.title.ilike(like)) | (Note.body.ilike(like))
            ).order_by(Note.updated_at.desc()).all()
    else:
        notes = Note.query.filter_by(user_id=current_user.id).order_by(Note.updated_at.desc()).all()
    return render_template('dashboard.html', notes=notes, q=q)
@app.route('/note/new', methods=['GET', 'POST'])
@login_required
def note_new():
    form = NoteForm()
    if form.validate_on_submit():
        with session_scope() as s:
            note = Note(title=form.title.data.strip(), body=form.body.data, user_id=current_user.id)
            s.add(note)
        flash('Note saved.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('note_form.html', form=form, action='New')
@app.route('/note/<int:note_id>')
@login_required
def note_view(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != current_user.id:
        abort(403)
    rendered_body = render_markdown_safe(note.body)
    return render_template('note_view.html', note=note, rendered_body=rendered_body)
@app.route('/note/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required
def note_edit(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != current_user.id:
        abort(403)
    form = NoteForm(obj=note)
    if form.validate_on_submit():
        with session_scope() as s:
            n = s.get(Note, note.id)
            if not n:
                abort(404)
            n.title = form.title.data.strip()
            n.body = form.body.data
            # updated_at auto-handled by SQLAlchemy on update
            s.add(n)
        flash('Note updated.', 'success')
        return redirect(url_for('note_view', note_id=note.id))
    return render_template('note_form.html', form=form, action='Edit')
@app.route('/note/<int:note_id>/delete', methods=['POST'])
@login_required
def note_delete(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != current_user.id:
        abort(403)
    with session_scope() as s:
        n = s.get(Note, note.id)
        if n:
            s.delete(n)
    flash('Note deleted.', 'info')
    return redirect(url_for('dashboard'))
@app.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
# --- Template files creation (if not exist) ---
# For convenience: create minimal required templates if they don't exist.
# You can replace these files with your own templates in templates/ folder.
def ensure_template(path, content):
    full = os.path.join(BASE_DIR, 'templates', path)
    if not os.path.exists(full):
        with open(full, 'w', encoding='utf-8') as f:
            f.write(content)
# base.html
ensure_template('base.html', """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Notes App</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body{padding-top:70px;}
      .truncate-3{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
      pre code{background:#f6f8fa;padding:6px;border-radius:4px;display:block;}
      .markdown-body{background:#fff;padding:1rem;border-radius:6px;}
    </style>
    {% block head_extra %}{% endblock %}
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark fixed-top">
      <div class="container">
        <a class="navbar-brand" href="{{ url_for('index') }}">Notes</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbars">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbars">
          <ul class="navbar-nav me-auto">
            {% if current_user.is_authenticated %}
              <li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}">Dashboard</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('note_new') }}">New</a></li>
            {% endif %}
          </ul>
          <form class="d-flex" action="{{ url_for('dashboard') }}" method="get">
            <input class="form-control form-control-sm me-2" name="q" placeholder="Search" value="{{ q if q is defined else '' }}">
            <button class="btn btn-outline-light btn-sm" type="submit">Search</button>
          </form>
          <ul class="navbar-nav ms-3">
            {% if current_user.is_authenticated %}
              <li class="nav-item"><span class="nav-link">Hi, {{ current_user.username }}</span></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></li>
            {% else %}
              <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">Login</a></li>
              <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">Register</a></li>
            {% endif %}
          </ul>
        </div>
      </div>
    </nav>

    <main class="container">
      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          {% for category, msg in messages %}
            <div class="alert alert-{{ 'info' if category=='info' else category }} alert-dismissible fade show" role="alert">
              {{ msg }}
              <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
          {% endfor %}
        {% endif %}
      {% endwith %}
      {% block content %}{% endblock %}
    </main>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
    {% block scripts %}{% endblock %}
  </body>
</html>
""")

# index.html
ensure_template('index.html', """{% extends "base.html" %}
{% block content %}
  <div class="row">
    <div class="col-md-8">
      <div class="p-4 mb-4 bg-light rounded-3">
        <h2>Welcome to Notes App</h2>
        <p>Create private notes, edit and search them. Markdown supported.</p>
        {% if not current_user.is_authenticated %}
          <a class="btn btn-primary" href="{{ url_for('register') }}">Register</a>
          <a class="btn btn-outline-primary" href="{{ url_for('login') }}">Login</a>
        {% else %}
          <a class="btn btn-primary" href="{{ url_for('dashboard') }}">My Notes</a>
        {% endif %}
      </div>
    </div>
  </div>
{% endblock %}""")

# auth.html
ensure_template('auth.html', """{% extends "base.html" %}
{% block content %}
  <div class="row justify-content-center">
    <div class="col-md-6">
      <div class="card shadow-sm">
        <div class="card-body">
          <h4 class="card-title mb-3">{{ title }}</h4>
          <form method="post" novalidate>
            {{ form.hidden_tag() }}
            <div class="mb-3">
              {{ form.username.label(class_="form-label") }}
              {{ form.username(class_="form-control") }}
              {% for e in form.username.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}
            </div>
            {% if show_email %}
            <div class="mb-3">
              {{ form.email.label(class_="form-label") }}
              {{ form.email(class_="form-control") }}
              {% for e in form.email.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}
            </div>
            {% endif %}
            <div class="mb-3">
              {{ form.password.label(class_="form-label") }}
              {{ form.password(class_="form-control") }}
              {% for e in form.password.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}
            </div>
            {% if show_confirm %}
            <div class="mb-3">
              {{ form.confirm.label(class_="form-label") }}
              {{ form.confirm(class_="form-control") }}
              {% for e in form.confirm.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}
            </div>
            {% endif %}
            <div class="d-grid">
              {{ form.submit(class_="btn btn-primary") }}
            </div>
          </form>
        </div>
      </div>
    </div>
  </div>
{% endblock %}""")

# dashboard.html
ensure_template('dashboard.html', """{% extends "base.html" %}
{% block content %}
  <div class="d-flex justify-content-between mb-3">
    <h3>My Notes</h3>
    <a class="btn btn-success" href="{{ url_for('note_new') }}">New Note</a>
  </div>

  {% if notes %}
    <div class="row g-3">
      {% for note in notes %}
        <div class="col-md-6">
          <div class="card h-100">
            <div class="card-body d-flex flex-column">
              <h5 class="card-title"><a href="{{ url_for('note_view', note_id=note.id) }}">{{ note.title }}</a></h5>
              <p class="card-text truncate-3">{{ note.body[:400] }}</p>
              <div class="mt-auto d-flex justify-content-between align-items-center">
                <small class="text-muted">Updated {{ note.updated_at.strftime('%Y-%m-%d %H:%M') }}</small>
                <div>
                  <a class="btn btn-sm btn-outline-primary" href="{{ url_for('note_edit', note_id=note.id) }}">Edit</a>
                  <form method="post" action="{{ url_for('note_delete', note_id=note.id) }}" class="d-inline" onsubmit="return confirm('Delete this note?');">
                    <button class="btn btn-sm btn-outline-danger">Delete</button>
                  </form>
                </div>
              </div>
            </div>
          </div>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="alert alert-secondary">No notes yet.</div>
  {% endif %}
{% endblock %}""")

# note_form.html
ensure_template('note_form.html', """{% extends "base.html" %}
{% block head_extra %}
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/styles/default.min.css">
{% endblock %}
{% block content %}
  <div class="row">
    <div class="col-md-7">
      <div class="card mb-3">
        <div class="card-body">
          <h5>{{ action }} Note</h5>
          <form method="post">
            {{ form.hidden_tag() }}
            <div class="mb-3">
              {{ form.title.label(class_="form-label") }}
              {{ form.title(class_="form-control") }}
              {% for e in form.title.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}
            </div>
            <div class="mb-3">
              {{ form.body.label(class_="form-label") }}
              {{ form.body(class_="form-control", rows="12", id="note-body") }}
              {% for e in form.body.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}
            </div>
            <div class="d-flex gap-2">
              {{ form.submit(class_="btn btn-primary") }}
              <a class="btn btn-secondary" href="{{ url_for('dashboard') }}">Cancel</a>
            </div>
          </form>
        </div>
      </div>
    </div>

    <div class="col-md-5">
      <div class="card mb-3">
        <div class="card-body">
          <h6>Preview</h6>
          <div id="preview" class="markdown-body"></div>
        </div>
      </div>
      <div class="card">
        <div class="card-body small text-muted">
          Markdown supported. Live preview on the right.
        </div>
      </div>
    </div>
  </div>
{% endblock %}
{% block scripts %}
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
  const ta = document.getElementById('note-body');
  const preview = document.getElementById('preview');
  function updatePreview(){
    const md = ta.value || '';
    preview.innerHTML = marked.parse(md);
  }
  if(ta){ ta.addEventListener('input', updatePreview); updatePreview(); }
</script>
{% endblock %}
""")

# note_view.html
ensure_template('note_view.html', """{% extends "base.html" %}
{% block content %}
  <div class="mb-3">
    <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('dashboard') }}">← Back</a>
    <a class="btn btn-sm btn-outline-primary" href="{{ url_for('note_edit', note_id=note.id) }}">Edit</a>
    <form method="post" action="{{ url_for('note_delete', note_id=note.id) }}" class="d-inline" onsubmit="return confirm('Delete this note?');">
      <button class="btn btn-sm btn-outline-danger">Delete</button>
    </form>
  </div>

  <h2>{{ note.title }}</h2>
  <p class="text-muted">Created {{ note.created_at.strftime('%Y-%m-%d %H:%M') }} · Updated {{ note.updated_at.strftime('%Y-%m-%d %H:%M') }}</p>

  <div class="markdown-body card p-3 mb-3">
    {{ rendered_body }}
  </div>
{% endblock %}""")
# --- Run ---
if __name__ == '__main__':
    # For development only. In production use a proper WSGI server and set SECRET_KEY.
    app.run(debug=True, host='127.0.0.1', port=5000)
