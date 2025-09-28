# app.py
from flask import Flask, render_template_string, redirect, url_for, flash, request, abort
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SubmitField, HiddenField
from wtforms.validators import DataRequired, Length, EqualTo
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import markdown
import bleach
# ---------------- Config ----------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FORUM_SECRET', 'change-this-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///forum.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
# Allowed tags/attrs for bleach (Markdown -> HTML sanitization)
ALLOWED_TAGS = [
    'a','abbr','acronym','b','blockquote','code','em','i','li','ol','strong','ul',
    'p','pre','span','h1','h2','h3','h4','h5','h6','br','hr','img','del'
]
ALLOWED_ATTRS = {
    '*': ['class'],
    'a': ['href','title','rel'],
    'img': ['src','alt','title'],
    'span': ['class'],
}
# ---------------- Models ----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    topics = db.relationship('Topic', backref='user', lazy=True)
    posts = db.relationship('Post', backref='user', lazy=True)

    def set_password(self,password): self.password_hash = generate_password_hash(password)
    def check_password(self,password): return check_password_hash(self.password_hash,password)
class Board(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(300))
    topics = db.relationship('Topic', backref='board', cascade="all, delete-orphan", lazy=True)
class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    closed = db.Column(db.Boolean, default=False)
    board_id = db.Column(db.Integer, db.ForeignKey('board.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    posts = db.relationship('Post', backref='topic', cascade="all, delete-orphan", lazy=True)
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    edited_at = db.Column(db.DateTime, nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('topic.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    children = db.relationship('Post', backref=db.backref('parent', remote_side=[id]), lazy=True, cascade="all, delete")
# Login helper
class LoginUser(UserMixin): pass
@login_manager.user_loader
def load_user(user_id):
    u = User.query.get(int(user_id))
    if not u: return None
    lu = LoginUser(); lu.id = u.id; return lu
# ---------------- Forms ----------------
class RegisterForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired(), Length(3,80)])
    password = PasswordField('密码', validators=[DataRequired(), Length(6,128)])
    confirm = PasswordField('确认密码', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('注册')
class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])
    submit = SubmitField('登录')
class TopicForm(FlaskForm):
    title = StringField('标题', validators=[DataRequired(), Length(1,200)])
    content = TextAreaField('内容', validators=[DataRequired()])
    submit = SubmitField('创建主题')
class PostForm(FlaskForm):
    content = TextAreaField('内容', validators=[DataRequired()])
    parent_id = HiddenField()
    submit = SubmitField('发布')
class EditPostForm(FlaskForm):
    content = TextAreaField('内容', validators=[DataRequired()])
    submit = SubmitField('保存修改')
# ---------------- DB init ----------------
@app.before_first_request
def create_tables():
    db.create_all()
    if Board.query.count() == 0:
        db.session.add_all([
            Board(title='综合讨论', description='General discussion / 综合话题'),
            Board(title='站点公告', description='Announcements and news / 公告'),
        ])
        db.session.commit()
# ---------------- Helpers ----------------
def render_markdown(md_text):
    html = markdown.markdown(md_text or '', extensions=['extra', 'sane_lists'])
    cleaned = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    # allow linking with rel="noopener noreferrer"
    cleaned = bleach.linkify(cleaned)
    return cleaned
def build_tree(posts):
    # posts: list of Post objects ordered by created_at asc
    nodes = {p.id: {'post': p, 'children': []} for p in posts}
    roots = []
    for p in posts:
        if p.parent_id and p.parent_id in nodes:
            nodes[p.parent_id]['children'].append(nodes[p.id])
        else:
            roots.append(nodes[p.id])
    return roots
# ---------------- Templates (single-file) ----------------
base_template = """
<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>简易论坛</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/simplemde/latest/simplemde.min.css">
<style>
:root{--brand-green:#0f9d58;--brand-gold:#c79a2b;--bg:#f8faf8}
body{background:var(--bg);color:#222}
.navbar{background:linear-gradient(90deg,var(--brand-green),#0b7a46)}
.navbar .navbar-brand, .navbar .nav-link, .navbar .btn { color: #fff !important; }
.card-topic { border-left:4px solid var(--brand-gold); }
.btn-primary { background:var(--brand-green); border-color:var(--brand-green); }
.btn-primary:hover { background:#0b7a46; border-color:#0b7a46; }
.text-accent { color:var(--brand-gold); }
.footer { font-size:.9rem; color:#555; padding:1rem 0; text-align:center; margin-top:2rem; }
.timestamp { color:#666; font-size:.85rem; }
.username-badge { color:#fff; background:var(--brand-green); padding:.15rem .5rem; border-radius:.25rem; }
.container-main { max-width:1100px; margin-top:1.5rem; }
.form-control:focus { box-shadow:0 0 0 .2rem rgba(15,157,88,.25); border-color:var(--brand-green); }
.reply-indent { margin-left:1rem; border-left:2px solid rgba(0,0,0,0.03); padding-left:1rem; }
.post-content { white-space:pre-wrap; }
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}"><strong>简易论坛</strong></a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav me-auto">
        <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">版块</a></li>
      </ul>
      <ul class="navbar-nav">
        {% if current_user.is_authenticated %}
          <li class="nav-item"><span class="nav-link">用户: <span class="username-badge">{{ current_user.id }}</span></span></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">登出</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>

<div class="container container-main">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for cat, msg in messages %}
        <div class="alert alert-{{ 'danger' if cat=='danger' else 'success' if cat=='success' else 'info' }} alert-dismissible fade show" role="alert">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
  <div class="footer">主题颜色：绿色 + 金色。部署时请设置环境变量 FORUM_SECRET 替换 SECRET_KEY。</div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script src="https://cdn.jsdelivr.net/simplemde/latest/simplemde.min.js"></script>
<script>
document.addEventListener('DOMContentLoaded', function(){
  document.querySelectorAll('textarea.simplemde').forEach(function(ta){
    new SimpleMDE({ element: ta, spellChecker: false, autosave: { enabled: false } });
  });
});
</script>
</body>
</html>
"""

index_template = """
{% extends base %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h3>版块</h3>
  {% if current_user.is_authenticated %}
    <a class="btn btn-sm btn-primary" href="{{ url_for('create_board') }}">新建版块</a>
  {% endif %}
</div>
<div class="row">
  {% for b in boards %}
  <div class="col-md-6 mb-3">
    <div class="card p-3">
      <h5><a href="{{ url_for('board_view', board_id=b.id) }}" class="text-decoration-none text-dark">{{ b.title }}</a></h5>
      <p class="mb-1 text-muted">{{ b.description }}</p>
      <small class="timestamp">主题：{{ b.topics|length }}</small>
    </div>
  </div>
  {% else %}
  <div class="col-12"><div class="card p-3">暂无版块</div></div>
  {% endfor %}
</div>
{% endblock %}
"""

board_template = """
{% extends base %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <div>
    <h4 class="mb-0">{{ board.title }} <small class="text-muted">- {{ board.description }}</small></h4>
  </div>
  <div>
    <a class="btn btn-sm btn-primary" href="{{ url_for('create_topic', board_id=board.id) }}">创建主题</a>
  </div>
</div>

{% for t in topics %}
<div class="card mb-2 card-topic">
  <div class="card-body">
    <div class="d-flex justify-content-between">
      <div>
        <h5 class="card-title mb-1"><a class="text-decoration-none" href="{{ url_for('topic_view', topic_id=t.id) }}">{{ t.title }}</a></h5>
        <div class="timestamp">由 <strong>{{ t.user.username if t.user else '匿名' }}</strong> 创建 • {{ t.created_at.strftime('%Y-%m-%d %H:%M') }}</div>
      </div>
      <div class="text-end">
        <small class="text-muted">{{ t.posts|length }} 回复</small>
      </div>
    </div>
  </div>
</div>
{% else %}
<div class="card p-3">暂无主题</div>
{% endfor %}
{% endblock %}
"""

topic_template = """
{% extends base %}
{% block content %}
<div class="mb-3">
  <a href="{{ url_for('board_view', board_id=topic.board.id) }}" class="text-decoration-none">&larr; 返回 {{ topic.board.title }}</a>
</div>
<div class="card mb-3">
  <div class="card-body">
    <h4>{{ topic.title }}</h4>
    <div class="timestamp">创建者 <strong>{{ topic.user.username if topic.user else '匿名' }}</strong> • {{ topic.created_at.strftime('%Y-%m-%d %H:%M') }}</div>
    <div class="mt-2">
      {% if current_user.is_authenticated and current_user.id==topic.user_id %}
        {% if topic.closed %}
          <a class="btn btn-sm btn-outline-success" href="{{ url_for('toggle_topic', topic_id=topic.id) }}">重新打开讨论</a>
        {% else %}
          <a class="btn btn-sm btn-outline-danger" href="{{ url_for('toggle_topic', topic_id=topic.id) }}">关闭讨论</a>
        {% endif %}
      {% endif %}
      {% if topic.closed %}
        <span class="badge bg-warning text-dark ms-2">已关闭</span>
      {% endif %}
    </div>
  </div>
</div>

<div class="mb-3">
  {% macro render_node(node, level=0) -%}
    <div class="card mb-2" style="margin-left:{{ level*20 }}px">
      <div class="card-body">
        <div class="d-flex justify-content-between">
          <div>
            <strong>{{ node.post.user.username if node.post.user else '匿名' }}</strong>
            <div class="timestamp">{{ node.post.created_at.strftime('%Y-%m-%d %H:%M') }}{% if node.post.edited_at %} • 编辑于 {{ node.post.edited_at.strftime('%Y-%m-%d %H:%M') }}{% endif %}</div>
          </div>
          <div>
            {% if current_user.is_authenticated and current_user.id==node.post.user_id %}
              <a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit_post', post_id=node.post.id) }}">编辑</a>
              <a class="btn btn-sm btn-outline-danger" href="{{ url_for('delete_post', post_id=node.post.id) }}" onclick="return confirm('确认删除该回复及其子回复？');">删除</a>
            {% endif %}
            {% if current_user.is_authenticated and (not topic.closed) %}
              <a class="btn btn-sm btn-outline-secondary" href="#" onclick="document.getElementById('parent_id').value='{{ node.post.id }}'; window.location.hash='reply';">回复</a>
            {% endif %}
          </div>
        </div>
        <hr>
        <div class="post-content">{{ node.post.content_html|safe }}</div>
      </div>
    </div>
    {% for ch in node.children %}
      {{ render_node(ch, level+1) }}
    {% endfor %}
  {%- endmacro %}

  {% for node in tree %}
    {{ render_node(node) }}
  {% else %}
    <div class="card p-3">暂无回复</div>
  {% endfor %}
</div>

<div class="card" id="reply">
  <div class="card-body">
    <h5>回复</h5>
    {% if topic.closed and not (current_user.is_authenticated and current_user.id==topic.user_id) %}
      <div class="alert alert-warning">该主题已关闭，不能再回复。</div>
    {% else %}
      <form method="post">
        {{ form.hidden_tag() }}
        {{ form.parent_id(id='parent_id') }}
        <div class="mb-2">
          {{ form.content(class_='form-control simplemde', id='id_content', rows=6) }}
          {% for err in form.content.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
        </div>
        <div><button class="btn btn-primary">{{ form.submit.label.text }}</button></div>
      </form>
    {% endif %}
  </div>
</div>
{% endblock %}
"""

create_topic_template = """
{% extends base %}
{% block content %}
<div class="mb-3">
  <a href="{{ url_for('board_view', board_id=board.id) }}" class="text-decoration-none">&larr; 返回 {{ board.title }}</a>
</div>
<div class="card">
  <div class="card-body">
    <h5>在 "{{ board.title }}" 创建主题</h5>
    <form method="post">
      {{ form.hidden_tag() }}
      <div class="mb-2">
        {{ form.title(class_='form-control') }}
        {% for err in form.title.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
      </div>
      <div class="mb-2">
        {{ form.content(class_='form-control simplemde', id='id_content_topic', rows=8) }}
        {% for err in form.content.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
      </div>
      <div>
        <button class="btn btn-primary">{{ form.submit.label.text }}</button>
      </div>
    </form>
  </div>
</div>
{% endblock %}
"""

create_board_template = """
{% extends base %}
{% block content %}
<div class="card">
  <div class="card-body">
    <h5>创建新版块</h5>
    <form method="post">
      <div class="mb-2">
        <input name="title" class="form-control" placeholder="版块标题" required maxlength="150">
      </div>
      <div class="mb-2">
        <input name="description" class="form-control" placeholder="简短描述" maxlength="300">
      </div>
      <div><button class="btn btn-primary">创建</button></div>
    </form>
  </div>
</div>
{% endblock %}
"""

auth_template = """
{% extends base %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <div class="card p-3">
      <h5 class="mb-3">{{ title }}</h5>
      <form method="post">
        {{ form.hidden_tag() }}
        {% for field in form if field.type!='CSRFToken' and field.name!='submit' %}
          <div class="mb-2">
            {{ field(class_='form-control', placeholder=field.label.text) }}
            {% for err in field.errors %}<div class="text-danger small">{{ err }}</div>{% endfor %}
          </div>
        {% endfor %}
        <div><button class="btn btn-primary">{{ form.submit.label.text }}</button></div>
      </form>
    </div>
  </div>
</div>
{% endblock %}
"""

edit_post_template = """
{% extends base %}
{% block content %}
<div class="mb-3">
  <a href="{{ url_for('topic_view', topic_id=post.topic.id) }}" class="text-decoration-none">&larr; 返回主题</a>
</div>
<div class="card">
  <div class="card-body">
    <h5>编辑回复</h5>
    <form method="post">
      {{ form.hidden_tag() }}
      <div class="mb-2">
        {{ form.content(class_='form-control simplemde', id='id_edit_content', rows=8) }}
      </div>
      <div><button class="btn btn-primary">{{ form.submit.label.text }}</button></div>
    </form>
  </div>
</div>
{% endblock %}
"""
# ---------------- Routes ----------------
@app.route('/')
def index():
    boards = Board.query.order_by(Board.id.asc()).all()
    return render_template_string(index_template, base=base_template, boards=boards)

@app.route('/board/<int:board_id>')
def board_view(board_id):
    board = Board.query.get_or_404(board_id)
    topics = Topic.query.filter_by(board_id=board.id).order_by(Topic.created_at.desc()).all()
    return render_template_string(board_template, base=base_template, board=board, topics=topics)
@app.route('/board/create', methods=['GET','POST'])
@login_required
def create_board():
    if request.method == 'POST':
        title = request.form.get('title','').strip()
        desc = request.form.get('description','').strip()
        if not title:
            flash('标题不能为空','danger')
            return redirect(url_for('create_board'))
        b = Board(title=title, description=desc)
        db.session.add(b)
        db.session.commit()
        flash('版块已创建','success')
        return redirect(url_for('board_view', board_id=b.id))
    return render_template_string(create_board_template, base=base_template)
@app.route('/board/<int:board_id>/create_topic', methods=['GET','POST'])
@login_required
def create_topic(board_id):
    board = Board.query.get_or_404(board_id)
    form = TopicForm()
    if form.validate_on_submit():
        topic = Topic(title=form.title.data.strip(), board=board, user_id=current_user.id)
        db.session.add(topic)
        db.session.commit()
        # create initial post as root (parent_id = None)
        content = form.content.data.strip()
        p = Post(content=content, topic=topic, user_id=current_user.id, parent_id=None)
        db.session.add(p)
        db.session.commit()
        flash('主题已创建','success')
        return redirect(url_for('topic_view', topic_id=topic.id))
    return render_template_string(create_topic_template, base=base_template, board=board, form=form)
@app.route('/topic/<int:topic_id>', methods=['GET','POST'])
def topic_view(topic_id):
    topic = Topic.query.get_or_404(topic_id)
    posts = Post.query.filter_by(topic_id=topic.id).order_by(Post.created_at.asc()).all()
    # prepare content_html for each post
    for p in posts:
        p.content_html = render_markdown(p.content)
    tree = build_tree(posts)
    form = PostForm()
    if form.validate_on_submit():
        if topic.closed and not (current_user.is_authenticated and current_user.id==topic.user_id):
            flash('该主题已关闭，无法回复','danger')
            return redirect(url_for('topic_view', topic_id=topic.id))
        if not current_user.is_authenticated:
            flash('请先登录再回复','warning')
            return redirect(url_for('login'))
        parent_id = form.parent_id.data or None
        try:
            parent_id = int(parent_id) if parent_id else None
        except:
            parent_id = None
        p = Post(content=form.content.data.strip(), topic=topic, user_id=current_user.id, parent_id=parent_id)
        db.session.add(p)
        db.session.commit()
        flash('回复已发布','success')
        return redirect(url_for('topic_view', topic_id=topic.id))
    return render_template_string(topic_template, base=base_template, topic=topic, posts=posts, tree=tree, form=form)
@app.route('/post/<int:post_id>/edit', methods=['GET','POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        abort(403)
    form = EditPostForm()
    if request.method == 'GET':
        form.content.data = post.content
    if form.validate_on_submit():
        post.content = form.content.data.strip()
        post.edited_at = datetime.utcnow()
        db.session.commit()
        flash('已保存修改','success')
        return redirect(url_for('topic_view', topic_id=post.topic_id))
    return render_template_string(edit_post_template, base=base_template, post=post, form=form)
@app.route('/post/<int:post_id>/delete')
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        abort(403)
    topic_id = post.topic_id
    # cascade delete will remove children
    db.session.delete(post)
    db.session.commit()
    flash('回复已删除（包含其子回复）','success')
    return redirect(url_for('topic_view', topic_id=topic_id))
@app.route('/topic/<int:topic_id>/toggle')
@login_required
def toggle_topic(topic_id):
    topic = Topic.query.get_or_404(topic_id)
    if topic.user_id != current_user.id:
        abort(403)
    topic.closed = not topic.closed
    db.session.commit()
    flash('操作已保存','success')
    return redirect(url_for('topic_view', topic_id=topic.id))
@app.route('/register', methods=['GET','POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        if User.query.filter_by(username=username).first():
            flash('用户名已存在','danger')
            return redirect(url_for('register'))
        u = User(username=username)
        u.set_password(form.password.data)
        db.session.add(u)
        db.session.commit()
        flash('注册成功，请登录','success')
        return redirect(url_for('login'))
    return render_template_string(auth_template, base=base_template, form=form, title='注册')
@app.route('/login', methods=['GET','POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        u = User.query.filter_by(username=username).first()
        if u and u.check_password(form.password.data):
            login_user(u)
            flash('登录成功','success')
            return redirect(url_for('index'))
        flash('用户名或密码错误','danger')
    return render_template_string(auth_template, base=base_template, form=form, title='登录')
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已登出','info')
    return redirect(url_for('index'))
# ---------------- Error handlers ----------------
@app.errorhandler(403)
def forbidden(e):
    flash('无权限操作','danger')
    return redirect(url_for('index'))
# ---------------- Run ----------------
if __name__ == '__main__':
    app.run(debug=True)
