# app.py
import os
from flask import Flask, render_template_string, request, redirect, url_for, flash, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
# Configuration
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'ogg'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-change-me'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    def set_password(self, password_text):
        self.password_hash = generate_password_hash(password_text)
    def check_password(self, password_text):
        return check_password_hash(self.password_hash, password_text)
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text)  # For article type
    post_type = db.Column(db.String(10), nullable=False)  # 'video' or 'article'
    filename = db.Column(db.String(260))  # stored filename for media
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    author = db.relationship('User', backref='posts')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
with app.app_context():
    db.create_all()
# Login loader
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
# Helpers
def allowed_file(filename, media_type):
    if '.' not in filename:
        return False
    extension = filename.rsplit('.', 1)[1].lower()
    if media_type == 'video':
        return extension in ALLOWED_VIDEO_EXTENSIONS
    if media_type == 'image':
        return extension in ALLOWED_IMAGE_EXTENSIONS
    return False
def save_uploaded_file(file_storage):
    filename = secure_filename(file_storage.filename)
    if filename == '':
        return None
    timestamped_name = f"{int(datetime.utcnow().timestamp())}_{filename}"
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], timestamped_name)
    file_storage.save(save_path)
    return timestamped_name
def remove_file_if_exists(stored_filename):
    if not stored_filename:
        return
    path = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
# LCS algorithm
def longest_common_subsequence(string_a: str, string_b: str):
    len_a, len_b = len(string_a), len(string_b)
    dp = [[0] * (len_b + 1) for _ in range(len_a + 1)]
    for index_a in range(len_a - 1, -1, -1):
        for index_b in range(len_b - 1, -1, -1):
            if string_a[index_a] == string_b[index_b]:
                dp[index_a][index_b] = dp[index_a + 1][index_b + 1] + 1
            else:
                dp[index_a][index_b] = max(dp[index_a + 1][index_b], dp[index_a][index_b + 1])
    # reconstruct
    i, j = 0, 0
    sequence_chars = []
    while i < len_a and j < len_b:
        if string_a[i] == string_b[j]:
            sequence_chars.append(string_a[i]); i += 1; j += 1
        else:
            if dp[i + 1][j] >= dp[i][j + 1]:
                i += 1
            else:
                j += 1
    return dp[0][0], ''.join(sequence_chars)
# Templates (base + pages)
BASE_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>MediaSite</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { padding-top: 4.5rem; }
      .card-media { max-height: 360px; object-fit: cover; }
      .tiny-muted { font-size:0.9rem; color:#6c757d; }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark fixed-top">
      <div class="container-fluid">
        <a class="navbar-brand" href="{{ url_for('index') }}">MediaSite</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navCol">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navCol">
          <ul class="navbar-nav me-auto mb-2 mb-lg-0">
            <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">Home</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('create_post') }}">Create</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('manage_posts') }}">My Posts</a></li>
          </ul>
          <form class="d-flex" method="get" action="{{ url_for('search') }}">
            <input class="form-control me-2" name="q" placeholder="Search title" value="{{ request.args.get('q','') }}">
            <button class="btn btn-outline-light" type="submit">Search</button>
          </form>
          <ul class="navbar-nav ms-3">
            {% if current_user.is_authenticated %}
              <li class="nav-item"><a class="nav-link disabled">User: {{ current_user.username }}</a></li>
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
            <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
              {{ msg }}
              <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
          {% endfor %}
        {% endif %}
      {% endwith %}

      {% block body %}{% endblock %}
    </main>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""

INDEX_TEMPLATE = """
{% extends base %}
{% block body %}
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h2>Latest Posts</h2>
    <small class="tiny-muted">Total {{ posts|length }}</small>
  </div>

  <div class="row">
    {% for post in posts %}
      <div class="col-md-4 mb-4">
        <div class="card h-100">
          {% if post.post_type == 'video' and post.filename %}
            <video class="card-img-top card-media" src="{{ url_for('uploaded_file', filename=post.filename) }}" controls></video>
          {% elif post.post_type == 'article' and post.filename %}
            <img src="{{ url_for('uploaded_file', filename=post.filename) }}" class="card-img-top card-media" alt="image">
          {% endif %}
          <div class="card-body d-flex flex-column">
            <h5 class="card-title">{{ post.title }}</h5>
            <p class="card-text small text-muted mb-2">by {{ post.author.username }} · {{ post.created_at.strftime('%Y-%m-%d %H:%M') }}</p>
            <p class="card-text text-truncate" style="max-height:4.5rem;">{{ post.content or '' }}</p>
            <div class="mt-auto">
              <a href="{{ url_for('view_post', post_id=post.id) }}" class="btn btn-primary btn-sm">View</a>
            </div>
          </div>
        </div>
      </div>
    {% else %}
      <p>No posts yet.</p>
    {% endfor %}
  </div>
{% endblock %}
"""

REGISTER_TEMPLATE = """
{% extends base %}
{% block body %}
  <div class="row justify-content-center">
    <div class="col-md-6">
      <h3>Register</h3>
      <form method="post">
        <div class="mb-3">
          <label class="form-label">Username</label>
          <input class="form-control" name="username" required>
        </div>
        <div class="mb-3">
          <label class="form-label">Password</label>
          <input class="form-control" type="password" name="password" required>
        </div>
        <button class="btn btn-success">Register</button>
      </form>
    </div>
  </div>
{% endblock %}
"""

LOGIN_TEMPLATE = """
{% extends base %}
{% block body %}
  <div class="row justify-content-center">
    <div class="col-md-6">
      <h3>Login</h3>
      <form method="post">
        <div class="mb-3">
          <label class="form-label">Username</label>
          <input class="form-control" name="username" required>
        </div>
        <div class="mb-3">
          <label class="form-label">Password</label>
          <input class="form-control" type="password" name="password" required>
        </div>
        <button class="btn btn-primary">Login</button>
      </form>
    </div>
  </div>
{% endblock %}
"""

CREATE_POST_TEMPLATE = """
{% extends base %}
{% block body %}
  <div class="row justify-content-center">
    <div class="col-md-8">
      <h3>Create New Post</h3>
      <form method="post" enctype="multipart/form-data">
        <div class="mb-3">
          <label class="form-label">Title</label>
          <input class="form-control" name="title" required>
        </div>
        <div class="mb-3">
          <label class="form-label">Type</label>
          <select class="form-select" name="post_type" id="post_type" onchange="toggleFields()">
            <option value="video">Video</option>
            <option value="article">Article</option>
          </select>
        </div>

        <div id="content_div" class="mb-3" style="display:none;">
          <label class="form-label">Content</label>
          <textarea class="form-control" name="content" rows="4"></textarea>
        </div>

        <div id="file_div" class="mb-3">
          <label class="form-label">Upload file (video or image)</label>
          <input class="form-control" type="file" name="file" required>
          <div class="form-text">Video: mp4 / webm / ogg. Image: png / jpg / jpeg / gif.</div>
        </div>

        <button class="btn btn-primary">Publish</button>
      </form>
    </div>
  </div>

  <script>
    function toggleFields(){
      const type = document.getElementById('post_type').value;
      document.getElementById('content_div').style.display = (type==='article') ? 'block' : 'none';
    }
    document.addEventListener('DOMContentLoaded', toggleFields);
  </script>
{% endblock %}
"""

MANAGE_POSTS_TEMPLATE = """
{% extends base %}
{% block body %}
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h3>My Posts</h3>
    <a class="btn btn-success" href="{{ url_for('create_post') }}">Create New</a>
  </div>

  <div class="list-group">
    {% for post in posts %}
      <div class="list-group-item">
        <div class="d-flex w-100 justify-content-between">
          <h5 class="mb-1">{{ post.title }}</h5>
          <small class="tiny-muted">{{ post.created_at.strftime('%Y-%m-%d') }}</small>
        </div>
        <p class="mb-1 text-truncate">{{ post.content or '' }}</p>
        <div class="mt-2">
          <a class="btn btn-sm btn-primary" href="{{ url_for('view_post', post_id=post.id) }}">View</a>
          <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('edit_post', post_id=post.id) }}">Edit</a>
          <a class="btn btn-sm btn-danger" href="{{ url_for('delete_post', post_id=post.id) }}" onclick="return confirm('Delete this post?');">Delete</a>
        </div>
      </div>
    {% else %}
      <p>No posts yet.</p>
    {% endfor %}
  </div>
{% endblock %}
"""

EDIT_POST_TEMPLATE = """
{% extends base %}
{% block body %}
  <div class="row justify-content-center">
    <div class="col-md-8">
      <h3>Edit Post</h3>
      <form method="post" enctype="multipart/form-data">
        <div class="mb-3">
          <label class="form-label">Title</label>
          <input class="form-control" name="title" required value="{{ post.title }}">
        </div>
        <div class="mb-3">
          <label class="form-label">Type</label>
          <select class="form-select" name="post_type" id="post_type" onchange="toggleFields()" disabled>
            <option value="video" {% if post.post_type=='video' %}selected{% endif %}>Video</option>
            <option value="article" {% if post.post_type=='article' %}selected{% endif %}>Article</option>
          </select>
        </div>

        <div id="content_div" class="mb-3" style="display:{{ 'block' if post.post_type=='article' else 'none' }};">
          <label class="form-label">Content</label>
          <textarea class="form-control" name="content" rows="4">{{ post.content or '' }}</textarea>
        </div>

        <div id="file_div" class="mb-3">
          <label class="form-label">Replace file (optional)</label>
          <input class="form-control" type="file" name="file">
          <div class="form-text">Upload to replace existing media. Leave empty to keep current file.</div>
          {% if post.filename %}
            <div class="mt-2">
              <strong>Current file:</strong> <a href="{{ url_for('uploaded_file', filename=post.filename) }}" target="_blank">{{ post.filename }}</a>
            </div>
          {% endif %}
        </div>

        <button class="btn btn-primary">Save Changes</button>
        <a class="btn btn-secondary" href="{{ url_for('manage_posts') }}">Cancel</a>
      </form>
    </div>
  </div>

  <script>
    function toggleFields(){
      const type = document.getElementById('post_type').value;
      document.getElementById('content_div').style.display = (type==='article') ? 'block' : 'none';
    }
    document.addEventListener('DOMContentLoaded', toggleFields);
  </script>
{% endblock %}
"""

VIEW_POST_TEMPLATE = """
{% extends base %}
{% block body %}
  <div class="row">
    <div class="col-md-8">
      <h3>{{ post.title }}</h3>
      <p class="tiny-muted">by {{ post.author.username }} · {{ post.created_at.strftime('%Y-%m-%d %H:%M') }}</p>

      {% if post.post_type == 'video' and post.filename %}
        <video controls style="width:100%; max-height:520px;">
          <source src="{{ url_for('uploaded_file', filename=post.filename) }}">
          Your browser does not support the video tag.
        </video>
      {% elif post.post_type == 'article' and post.filename %}
        <img src="{{ url_for('uploaded_file', filename=post.filename) }}" class="img-fluid mb-3" alt="image">
        <p>{{ post.content }}</p>
      {% else %}
        <p>{{ post.content or '' }}</p>
      {% endif %}

      <hr>
      <h5>Longest Common Subsequence (Example)</h5>
      <p class="tiny-muted">Compare post title with an input string (or username if logged in).</p>

      <form method="post" action="{{ url_for('compute_lcs', post_id=post.id) }}" class="row g-2 align-items-center mb-3">
        <div class="col-auto">
          <input class="form-control" name="text_b" placeholder="Enter comparison string (leave blank to use username)">
        </div>
        <div class="col-auto">
          <button class="btn btn-outline-primary">Compute LCS</button>
        </div>
      </form>

      {% if lcs_result is defined %}
        <div class="card">
          <div class="card-body">
            <p><strong>String A (post title):</strong> {{ title_a }}</p>
            <p><strong>String B (comparison):</strong> {{ title_b }}</p>
            <p><strong>LCS length:</strong> {{ lcs_result[0] }}</p>
            <p><strong>LCS sequence:</strong> <code>{{ lcs_result[1] }}</code></p>
          </div>
        </div>
      {% endif %}
    </div>

    <div class="col-md-4">
      <h6>Other posts by author</h6>
      {% for other in others %}
        <div class="mb-2">
          <a href="{{ url_for('view_post', post_id=other.id) }}">{{ other.title }}</a>
          <div class="tiny-muted">{{ other.created_at.strftime('%Y-%m-%d') }}</div>
        </div>
      {% else %}
        <p class="tiny-muted">None</p>
      {% endfor %}
    </div>
  </div>
{% endblock %}
"""
SEARCH_TEMPLATE = """
{% extends base %}
{% block body %}
  <h3>Search results: "{{ q }}"</h3>
  <p class="tiny-muted">Total {{ posts|length }}</p>
  <div class="list-group">
    {% for post in posts %}
      <a class="list-group-item list-group-item-action" href="{{ url_for('view_post', post_id=post.id) }}">
        <div class="d-flex w-100 justify-content-between">
          <h5 class="mb-1">{{ post.title }}</h5>
          <small class="tiny-muted">{{ post.created_at.strftime('%Y-%m-%d') }}</small>
        </div>
        <p class="mb-1 text-truncate">{{ post.content or '' }}</p>
        <small class="tiny-muted">by {{ post.author.username }}</small>
      </a>
    {% else %}
      <p class="mt-3">No matches found.</p>
    {% endfor %}
  </div>
{% endblock %}
"""
# Routes
@app.route('/')
def index():
    posts = Post.query.order_by(Post.created_at.desc()).limit(30).all()
    return render_template_string(INDEX_TEMPLATE, base=BASE_TEMPLATE, posts=posts)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username_input = request.form.get('username', '').strip()
        password_input = request.form.get('password', '')
        if not username_input or not password_input:
            flash('Username and password are required', 'warning')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username_input).first():
            flash('Username already exists', 'warning')
            return redirect(url_for('register'))
        user = User(username=username_input)
        user.set_password(password_input)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful, please login', 'success')
        return redirect(url_for('login'))
    return render_template_string(REGISTER_TEMPLATE, base=BASE_TEMPLATE)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username_input = request.form.get('username', '').strip()
        password_input = request.form.get('password', '')
        user = User.query.filter_by(username=username_input).first()
        if user and user.check_password(password_input):
            login_user(user)
            flash('Login successful', 'success')
            return redirect(url_for('index'))
        flash('Invalid username or password', 'danger')
        return redirect(url_for('login'))
    return render_template_string(LOGIN_TEMPLATE, base=BASE_TEMPLATE)
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out', 'info')
    return redirect(url_for('index'))
@app.route('/post/create', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        title_input = request.form.get('title', '').strip()
        post_type_input = request.form.get('post_type')
        content_input = request.form.get('content', '').strip()
        file_storage = request.files.get('file')
        if not title_input:
            flash('Title is required', 'warning')
            return redirect(url_for('create_post'))
        stored_filename = None
        if file_storage:
            original_filename = secure_filename(file_storage.filename)
            if original_filename == '':
                flash('Invalid file name', 'warning')
                return redirect(url_for('create_post'))
            if post_type_input == 'video':
                if not allowed_file(original_filename, 'video'):
                    flash('Only video files allowed (mp4/webm/ogg)', 'warning'); return redirect(url_for('create_post'))
            elif post_type_input == 'article':
                if not allowed_file(original_filename, 'image'):
                    flash('Only image files allowed (png/jpg/jpeg/gif)', 'warning'); return redirect(url_for('create_post'))
            stored_filename = save_uploaded_file(file_storage)
        new_post = Post(title=title_input, post_type=post_type_input,
                        content=content_input if post_type_input=='article' else None,
                        filename=stored_filename, author=current_user)
        db.session.add(new_post)
        db.session.commit()
        flash('Post created', 'success')
        return redirect(url_for('view_post', post_id=new_post.id))
    return render_template_string(CREATE_POST_TEMPLATE, base=BASE_TEMPLATE)

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=False)

@app.route('/post/<int:post_id>')
def view_post(post_id):
    post = Post.query.get_or_404(post_id)
    other_posts = Post.query.filter(Post.author_id==post.author_id, Post.id!=post.id) \
                    .order_by(Post.created_at.desc()).limit(5).all()
    return render_template_string(VIEW_POST_TEMPLATE, base=BASE_TEMPLATE, post=post, others=other_posts)
@app.route('/post/<int:post_id>/lcs', methods=['POST'])
def compute_lcs(post_id):
    post = Post.query.get_or_404(post_id)
    text_b_input = request.form.get('text_b', '').strip()
    if not text_b_input:
        if current_user.is_authenticated:
            text_b_input = current_user.username
        else:
            text_b_input = "example"
    string_a = post.title or ''
    result = longest_common_subsequence(string_a, text_b_input)
    other_posts = Post.query.filter(Post.author_id==post.author_id, Post.id!=post.id) \
                    .order_by(Post.created_at.desc()).limit(5).all()
    return render_template_string(VIEW_POST_TEMPLATE, base=BASE_TEMPLATE, post=post, others=other_posts,
                                  lcs_result=result, title_a=string_a, title_b=text_b_input)
@app.route('/search')
def search():
    query_text = request.args.get('q', '').strip()
    if not query_text:
        posts = []
    else:
        like_pattern = f"%{query_text}%"
        posts = Post.query.filter(Post.title.like(like_pattern)).order_by(Post.created_at.desc()).all()
    return render_template_string(SEARCH_TEMPLATE, base=BASE_TEMPLATE, posts=posts, q=query_text)
# Manage routes: edit & delete (only owner)
@app.route('/manage')
@login_required
def manage_posts():
    user_posts = Post.query.filter_by(author_id=current_user.id).order_by(Post.created_at.desc()).all()
    return render_template_string(MANAGE_POSTS_TEMPLATE, base=BASE_TEMPLATE, posts=user_posts)
@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author_id != current_user.id:
        abort(403)
    if request.method == 'POST':
        title_input = request.form.get('title', '').strip()
        content_input = request.form.get('content', '').strip()
        file_storage = request.files.get('file')
        if not title_input:
            flash('Title is required', 'warning')
            return redirect(url_for('edit_post', post_id=post.id))
        # If new file uploaded, validate and replace
        if file_storage and file_storage.filename:
            original_filename = secure_filename(file_storage.filename)
            if original_filename:
                if post.post_type == 'video':
                    if not allowed_file(original_filename, 'video'):
                        flash('Only video files allowed (mp4/webm/ogg)', 'warning'); return redirect(url_for('edit_post', post_id=post.id))
                elif post.post_type == 'article':
                    if not allowed_file(original_filename, 'image'):
                        flash('Only image files allowed (png/jpg/jpeg/gif)', 'warning'); return redirect(url_for('edit_post', post_id=post.id))
                # remove old file
                remove_file_if_exists(post.filename)
                post.filename = save_uploaded_file(file_storage)
        # Update fields
        post.title = title_input
        if post.post_type == 'article':
            post.content = content_input
        db.session.commit()
        flash('Post updated', 'success')
        return redirect(url_for('view_post', post_id=post.id))
    return render_template_string(EDIT_POST_TEMPLATE, base=BASE_TEMPLATE, post=post)
@app.route('/post/<int:post_id>/delete', methods=['GET', 'POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author_id != current_user.id:
        abort(403)
    # Delete file from disk
    remove_file_if_exists(post.filename)
    db.session.delete(post)
    db.session.commit()
    flash('Post deleted', 'info')
    return redirect(url_for('manage_posts'))
# Run
if __name__ == '__main__':
    app.run(debug=True)
