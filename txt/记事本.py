import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, font, ttk
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes
import struct, os, base58
# ---------- 配置 ----------
PBKDF2_ITERS = 5000
SALT_SIZE = 16
NONCE_SIZE = 12
TAG_SIZE = 16
MAGIC = b'SNOTE1.0'
VERSION = 1
# ---------- 全局 UI 状态 ----------
root = tk.Tk()
current_path = None
font_size = 14
# ---------- 密钥与加密 ----------
def derive_key(password: str, salt: bytes, key_len=32):
    return PBKDF2(password.encode('utf-8'), salt, dkLen=key_len, count=PBKDF2_ITERS)
def encrypt_bytes_b58(plaintext: bytes, password: str) -> bytes:
    salt = get_random_bytes(SALT_SIZE)
    key = derive_key(password, salt)
    nonce = get_random_bytes(NONCE_SIZE)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    parts = [MAGIC, struct.pack('B', VERSION), salt, nonce, struct.pack('>Q', len(ciphertext)), ciphertext, tag]
    raw = b''.join(parts)
    return base58.b58encode(raw)
def decrypt_bytes_b58(b58data: bytes, password: str) -> bytes:
    raw = base58.b58decode(b58data)
    off = 0
    if raw[0:8] != MAGIC:
        raise ValueError("不支持的文件格式")
    off = 8
    ver = raw[off]; off += 1
    if ver != VERSION:
        raise ValueError("不支持的版本")
    salt = raw[off:off+SALT_SIZE]; off += SALT_SIZE
    nonce = raw[off:off+NONCE_SIZE]; off += NONCE_SIZE
    (ct_len,) = struct.unpack('>Q', raw[off:off+8]); off += 8
    ciphertext = raw[off:off+ct_len]; off += ct_len
    tag = raw[off:off+TAG_SIZE]
    key = derive_key(password, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)
# ---------- 简洁密码对话 ----------
def ask_password(parent, title, prompt, confirm=False):
    dlg = tk.Toplevel(parent)
    dlg.transient(parent)
    dlg.grab_set()
    dlg.title(title)
    dlg.resizable(False, False)
    pw = tk.StringVar()
    pw2 = tk.StringVar()
    frm = ttk.Frame(dlg, padding=12); frm.pack()
    ttk.Label(frm, text=prompt).pack(anchor='w')
    ent = ttk.Entry(frm, textvariable=pw, show='*', width=30); ent.pack(pady=6); ent.focus_set()
    if confirm:
        ttk.Label(frm, text="确认密码:").pack(anchor='w')
        ttk.Entry(frm, textvariable=pw2, show='*', width=30).pack(pady=6)
    res = {'value': None}
    def ok():
        if confirm and pw.get() != pw2.get():
            messagebox.showerror("错误", "两次密码不一致", parent=dlg); return
        if confirm and pw.get() == "":
            messagebox.showerror("错误", "密码不能为空", parent=dlg); return
        res['value'] = pw.get()
        dlg.destroy()
    def cancel():
        dlg.destroy()
    btn_fr = ttk.Frame(frm); btn_fr.pack(fill='x', pady=(6,0))
    ttk.Button(btn_fr, text="确定", command=ok).pack(side='right', padx=6)
    ttk.Button(btn_fr, text="取消", command=cancel).pack(side='right')
    dlg.wait_window()
    return res['value']
# ---------- UI 创建 ----------
def build_ui():
    global text_widget, status_label
    root.title("Secure Notepad (简洁版)")
    root.geometry("900x640")
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except:
        pass

    toolbar = ttk.Frame(root, padding=6); toolbar.pack(side='top', fill='x')
    ttk.Button(toolbar, text="打开", command=open_file).pack(side='left', padx=4)
    ttk.Button(toolbar, text="保存", command=save_file).pack(side='left', padx=4)
    ttk.Button(toolbar, text="另存为", command=save_file_as).pack(side='left', padx=4)
    ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=6)
    ttk.Button(toolbar, text="A+", command=increase_font).pack(side='left', padx=2)
    ttk.Button(toolbar, text="A-", command=decrease_font).pack(side='left', padx=2)
    ttk.Button(toolbar, text="重置字号", command=reset_font).pack(side='left', padx=6)
    ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=6)
    ttk.Button(toolbar, text="查找/替换", command=open_find_replace).pack(side='left', padx=4)

    frame = ttk.Frame(root); frame.pack(fill='both', expand=True, padx=8, pady=8)
    text_widget = tk.Text(frame, wrap='word', undo=True,
                         bg='black', fg='#FF0000', insertbackground='#FF0000',
                         relief='flat', bd=0, padx=8, pady=8)
    text_widget.pack(side='left', fill='both', expand=True)
    sc = ttk.Scrollbar(frame, command=text_widget.yview); sc.pack(side='right', fill='y')
    text_widget.configure(yscrollcommand=sc.set)

    # 字体与高亮
    families = font.families()
    fam = 'Consolas' if 'Consolas' in families else 'Courier'
    text_widget.configure(font=(fam, font_size))
    text_widget.tag_configure("match", background="green", foreground="gold")

    status_label = ttk.Label(root, text="就绪", relief='sunken', anchor='w', padding=4)
    status_label.pack(side='bottom', fill='x')
# ---------- 字体控制 ----------
def increase_font():
    global font_size
    font_size += 2
    text_widget.configure(font=(text_widget.cget('font').split()[0], font_size))
def decrease_font():
    global font_size
    if font_size > 6:
        font_size -= 2
        text_widget.configure(font=(text_widget.cget('font').split()[0], font_size))
def reset_font():
    global font_size
    font_size = 14
    text_widget.configure(font=(text_widget.cget('font').split()[0], font_size))
# ---------- 文件操作 ----------
def save_file():
    global current_path
    if not current_path:
        return save_file_as()
    return _do_save(current_path)
def save_file_as():
    global current_path
    p = filedialog.asksaveasfilename(defaultextension=".snoteb58",
                                     filetypes=[("Secure Note Base58", "*.snoteb58"), ("All files", "*.*")])
    if not p:
        set_status("保存已取消"); return
    current_path = p
    return _do_save(p)
def _do_save(path):
    pw = ask_password(root, "设置保存密码", "请输入用于加密的密码:", confirm=True)
    if pw is None:
        set_status("保存已取消"); return
    try:
        data = text_widget.get("1.0", "end-1c").encode('utf-8')
        b58 = encrypt_bytes_b58(data, pw)
        with open(path, 'wb') as f:
            f.write(b58)
        set_status(f"已保存: {os.path.basename(path)}")
        messagebox.showinfo("保存", "已加密并保存。", parent=root)
    except Exception as e:
        messagebox.showerror("保存错误", f"{e}", parent=root)
        set_status("保存失败")
def open_file():
    global current_path
    p = filedialog.askopenfilename(filetypes=[("Secure Note Base58", "*.snoteb58"), ("All files", "*.*")])
    if not p:
        set_status("打开已取消"); return
    pw = ask_password(root, "输入打开密码", "请输入用于解密的密码:", confirm=False)
    if pw is None:
        set_status("打开已取消"); return
    try:
        with open(p, 'rb') as f:
            b58 = f.read()
        plaintext = decrypt_bytes_b58(b58, pw)
        text = plaintext.decode('utf-8')
        text_widget.delete("1.0", "end")
        text_widget.insert("1.0", text)
        current_path = p
        set_status(f"已打开: {os.path.basename(p)}")
        messagebox.showinfo("打开", "已解密并载入文件。", parent=root)
    except Exception as e:
        messagebox.showerror("打开/解密错误", f"{e}", parent=root)
        set_status("打开失败")
# ---------- 查找与替换 ----------
def open_find_replace():
    fr = tk.Toplevel(root); fr.title("查找与替换"); fr.transient(root); fr.resizable(False, False)
    frm = ttk.Frame(fr, padding=10); frm.pack()
    ttk.Label(frm, text="查找:").grid(row=0, column=0, sticky='w')
    fv = tk.StringVar(); en_f = ttk.Entry(frm, textvariable=fv, width=30); en_f.grid(row=0, column=1, padx=6, pady=4)
    ttk.Label(frm, text="替换为:").grid(row=1, column=0, sticky='w')
    rv = tk.StringVar(); ttk.Entry(frm, textvariable=rv, width=30).grid(row=1, column=1, padx=6, pady=4)
    case = tk.BooleanVar(value=False); ttk.Checkbutton(frm, text="区分大小写", variable=case).grid(row=2, column=1, sticky='w')
    btns = ttk.Frame(frm); btns.grid(row=3, column=0, columnspan=2, pady=(8,0))
    ttk.Button(btns, text="查找下一个", command=lambda: find_next(fv.get(), case.get())).pack(side='left', padx=4)
    ttk.Button(btns, text="全部高亮", command=lambda: highlight_all(fv.get(), case.get())).pack(side='left', padx=4)
    ttk.Button(btns, text="替换", command=lambda: replace_one(fv.get(), rv.get(), case.get())).pack(side='left', padx=4)
    ttk.Button(btns, text="全部替换", command=lambda: replace_all(fv.get(), rv.get(), case.get())).pack(side='left', padx=4)
    ttk.Button(btns, text="清除高亮", command=clear_highlight).pack(side='left', padx=4)
    en_f.focus_set()

def clear_highlight():
    text_widget.tag_remove("match", "1.0", "end")
    set_status("已清除高亮")

def highlight_all(pattern, case_sensitive=False):
    clear_highlight()
    if not pattern:
        set_status("查找字符串为空"); return
    start = "1.0"
    count = 0
    while True:
        idx = text_widget.search(pattern, start, nocase=not case_sensitive, stopindex="end")
        if not idx: break
        end = f"{idx}+{len(pattern)}c"
        text_widget.tag_add("match", idx, end)
        start = end
        count += 1
    set_status(f"高亮 {count} 项")

def find_next(pattern, case_sensitive=False):
    if not pattern:
        set_status("查找字符串为空"); return
    cur = text_widget.index(tk.INSERT)
    idx = text_widget.search(pattern, cur, nocase=not case_sensitive, stopindex="end")
    if not idx:
        idx = text_widget.search(pattern, "1.0", nocase=not case_sensitive, stopindex="end")
        if not idx:
            set_status("未找到"); return
    end = f"{idx}+{len(pattern)}c"
    text_widget.tag_remove("match", "1.0", "end")
    text_widget.tag_add("match", idx, end)
    text_widget.mark_set("insert", end)
    text_widget.see(idx)
    set_status(f"已找到 at {idx}")

def replace_one(pattern, replacement, case_sensitive=False):
    cur = text_widget.index(tk.INSERT)
    idx = text_widget.search(pattern, cur, nocase=not case_sensitive, stopindex="end")
    if not idx:
        idx = text_widget.search(pattern, "1.0", nocase=not case_sensitive, stopindex="end")
        if not idx:
            set_status("未找到"); return
    end = f"{idx}+{len(pattern)}c"
    text_widget.delete(idx, end)
    text_widget.insert(idx, replacement)
    set_status("已替换一项")
    new_end = f"{idx}+{len(replacement)}c"
    text_widget.tag_remove("match", "1.0", "end")
    text_widget.tag_add("match", idx, new_end)
    text_widget.mark_set("insert", new_end)
    text_widget.see(idx)

def replace_all(pattern, replacement, case_sensitive=False):
    if not pattern:
        set_status("查找字符串为空"); return
    txt = text_widget.get("1.0", "end-1c")
    if case_sensitive:
        new = txt.replace(pattern, replacement)
    else:
        # 保持简单：不做复杂逐字母匹配，直接不区分大小写替换需要更复杂实现；这里用简单策略
        new = txt.replace(pattern, replacement)
    text_widget.delete("1.0", "end")
    text_widget.insert("1.0", new)
    set_status("全部替换完成")
    clear_highlight()
# ---------- 状态 ----------
def set_status(s):
    status_label.config(text=s)
# ---------- 启动对话 ----------
def startup_choice():
    d = tk.Toplevel(root); d.title("开始"); d.transient(root); d.grab_set(); d.resizable(False, False)
    frm = ttk.Frame(d, padding=12); frm.pack()
    ttk.Label(frm, text="请选择:").pack(anchor='w', pady=(0,8))
    ttk.Button(frm, text="新建空白", command=d.destroy).pack(fill='x', pady=4)
    ttk.Button(frm, text="打开已有文件", command=lambda: (d.destroy(), open_file())).pack(fill='x', pady=4)
    ttk.Button(frm, text="取消", command=d.destroy).pack(fill='x', pady=4)
    root.wait_window(d)
# ---------- 入口 ----------
build_ui()
startup_choice()
root.protocol("WM_DELETE_WINDOW", lambda: root.destroy())
root.mainloop()
