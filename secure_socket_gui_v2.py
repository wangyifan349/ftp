#!/usr/bin/env python3
import socket
import threading
import struct
import os
import queue
import hashlib
import traceback
import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog, font, simpledialog
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 常量定义
PUBKEY_LEN = 32        # x25519 公钥长度（字节）
LEN_PREFIX = 4         # 帧长度前缀（4 字节，大端）
AES_KEY_LEN = 32       # AES 密钥长度（字节）
NONCE_LEN = 12         # AES-GCM 随机数长度（字节）
HKDF_INFO = b"secure-socket-v2"  # HKDF info 字段，用于派生密钥上下文

# 发送全部数据（处理短写）
def send_all(s, data):
    total = 0
    while total < len(data):
        sent = s.send(data[total:])
        if sent == 0:
            raise ConnectionError("socket broken")
        total += sent

# 接收精确长度的字节（阻塞直到读取到 n 字节或连接关闭）
def recv_exact(s, n):
    buf = []
    r = 0
    while r < n:
        ch = s.recv(n - r)
        if not ch:
            raise ConnectionError("socket broken")
        buf.append(ch)
        r += len(ch)
    return b"".join(buf)

# 发送一帧：先 4 字节长度前缀（大端），再是载荷
def send_frame(s, p):
    send_all(s, struct.pack(">I", len(p)) + p)

# 接收一帧：读取长度前缀，再读取对应长度的载荷
def recv_frame(s):
    h = recv_exact(s, LEN_PREFIX)
    (L,) = struct.unpack(">I", h)
    return b"" if L == 0 else recv_exact(s, L)

# 使用 HKDF 从共享 secret 派生两个密钥：发送密钥（sk）和接收密钥（rk）
def derive_keys(secret, role):
    # 这里我们使用 SHA-256，长度 64 字节，然后分为两个 32 字节的密钥
    hk = HKDF(algorithm=hashes.SHA256(), length=64, salt=None, info=HKDF_INFO + b"|" + role)
    km = hk.derive(secret)
    return km[:AES_KEY_LEN], km[AES_KEY_LEN:]

# 执行 x25519 握手：生成本地私钥/公钥，交换公钥，导出共享 secret 并派生对称密钥
def perform_handshake(conn, is_server, log):
    # 生成 x25519 私钥并导出原始公钥字节
    priv = x25519.X25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(encoding=serialization.Encoding.Raw,
                                         format=serialization.PublicFormat.Raw)
    try:
        # 如果是服务器先接收对端公钥再发送本地公钥；客户端相反
        if is_server:
            peer = recv_exact(conn, PUBKEY_LEN)
            send_all(conn, pub)
        else:
            send_all(conn, pub)
            peer = recv_exact(conn, PUBKEY_LEN)
    except Exception as e:
        log(f"Handshake I/O error: {e}")
        raise

    # 从对端公钥字节重建公钥对象，计算共享 secret
    peerpk = x25519.X25519PublicKey.from_public_bytes(peer)
    secret = priv.exchange(peerpk)

    # 根据角色（server/client）派生两个密钥（用于发送和接收）
    role = b"server" if is_server else b"client"
    sk, rk = derive_keys(secret, role)
    return sk, rk, secret
class SenderThread(threading.Thread):
    """发送线程：从队列取出文本消息，加密后以帧形式通过 socket 发送"""
    def __init__(self, sock, key, q, log, stop):
        super().__init__(daemon=True)
        self.sock = sock
        self.aes = AESGCM(key)
        self.q = q
        self.log = log
        self.stop = stop

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    msg = self.q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if msg is None:
                    break
                try:
                    pt = msg.encode()
                except Exception:
                    pt = b''
                nonce = os.urandom(NONCE_LEN)
                try:
                    ct = self.aes.encrypt(nonce, pt, None)
                    send_frame(self.sock, nonce + ct)
                except Exception as e:
                    self.log(f"Sender error: {e}")
                    self.stop.set()
                    break
        except Exception as e:
            self.log(f"Sender thread exc: {e}\n{traceback.format_exc()}")
            self.stop.set()

class ReceiverThread(threading.Thread):
    """接收线程：读取帧，解析 nonce 与密文，解密并将明文放入入队列"""
    def __init__(self, sock, key, in_q, log, stop):
        super().__init__(daemon=True)
        self.sock = sock
        self.aes = AESGCM(key)
        self.in_q = in_q
        self.log = log
        self.stop = stop

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    payload = recv_frame(self.sock)
                except ConnectionError:
                    self.log("Receiver: connection closed")
                    self.stop.set()
                    break
                except Exception as e:
                    self.log(f"Receiver frame error: {e}")
                    self.stop.set()
                    break

                # 验证最小长度：nonce + tag 至少为 NONCE_LEN + 16
                if len(payload) < NONCE_LEN + 16:
                    self.log("Receiver: short frame")
                    self.stop.set()
                    break

                nonce = payload[:NONCE_LEN]
                ct = payload[NONCE_LEN:]
                try:
                    pt = self.aes.decrypt(nonce, ct, None)
                    text = pt.decode('utf-8', errors='replace')
                except Exception as e:
                    self.log(f"Receiver decrypt error: {e}")
                    self.stop.set()
                    break

                try:
                    self.in_q.put_nowait(text)
                except queue.Full:
                    self.log("Incoming queue full")
        except Exception as e:
            self.log(f"Receiver thread exc: {e}\n{traceback.format_exc()}")
            self.stop.set()

class SecureSocketGUI:
    """主 GUI 应用类：负责界面、启动服务器/客户端、管理连接和线程"""
    def __init__(self, master):
        self.master = master
        master.title("Secure Socket v2")

        # 调整默认字体大小
        f = font.nametofont("TkDefaultFont")
        f.configure(size=10)

        # 顶部控制区：模式、主机、端口、启动/断开按钮
        top = tk.Frame(master, pady=6)
        top.pack(fill=tk.X, padx=8)
        tk.Label(top, text="Mode:").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="Server")
        self.mode_menu = tk.OptionMenu(top, self.mode_var, "Server", "Client")
        self.mode_menu.pack(side=tk.LEFT, padx=(4, 8))
        tk.Label(top, text="Host:").pack(side=tk.LEFT)
        self.entry_host = tk.Entry(top, width=16)
        self.entry_host.insert(0, "127.0.0.1")
        self.entry_host.pack(side=tk.LEFT, padx=(4, 8))
        tk.Label(top, text="Port:").pack(side=tk.LEFT)
        self.entry_port = tk.Entry(top, width=6)
        self.entry_port.insert(0, "9000")
        self.entry_port.pack(side=tk.LEFT, padx=(4, 8))
        self.btn_start = tk.Button(top, text="Start", width=12, command=self.start)
        self.btn_start.pack(side=tk.LEFT, padx=4)
        self.btn_disconnect = tk.Button(top, text="Disconnect", width=12, command=self.disconnect, state=tk.DISABLED)
        self.btn_disconnect.pack(side=tk.LEFT, padx=4)

        # 中间：显示共享 secret 与指纹，以及日志区
        mid = tk.Frame(master, pady=4)
        mid.pack(fill=tk.X, padx=8)
        tk.Label(mid, text="Shared Secret (hex):").pack(side=tk.LEFT)
        self.shared_var = tk.StringVar()
        self.entry_shared = tk.Entry(mid, textvariable=self.shared_var, state='readonly', width=48)
        self.entry_shared.pack(side=tk.LEFT, padx=(6, 8), fill=tk.X, expand=True)
        tk.Label(mid, text="FP:").pack(side=tk.LEFT)
        self.fpr_var = tk.StringVar()
        self.entry_fpr = tk.Entry(mid, textvariable=self.fpr_var, state='readonly', width=18)
        self.entry_fpr.pack(side=tk.LEFT, padx=(6, 0))

        self.log_area = scrolledtext.ScrolledText(master, height=16, state=tk.DISABLED, wrap=tk.WORD)
        self.log_area.pack(fill=tk.BOTH, padx=8, pady=(6, 0), expand=True)

        # 底部：消息输入、发送、导出日志
        bottom = tk.Frame(master, pady=6)
        bottom.pack(fill=tk.X, padx=8)
        self.entry_message = tk.Entry(bottom)
        self.entry_message.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.entry_message.bind("<Return>", lambda e: self.send_message())
        self.btn_send = tk.Button(bottom, text="Send", width=12, command=self.send_message, state=tk.DISABLED)
        self.btn_send.pack(side=tk.LEFT, padx=4)
        self.btn_export = tk.Button(bottom, text="Export Log", width=12, command=self.export_log)
        self.btn_export.pack(side=tk.LEFT, padx=4)

        # 状态栏
        self.status_var = tk.StringVar(value="Idle")
        tk.Label(master, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W).pack(side=tk.BOTTOM, fill=tk.X)

        # 连接/线程/队列状态
        self.server_socket = None
        self.accept_thread = None
        self.conn_sock = None
        self.conn_thread = None
        self.send_queue = queue.Queue()
        self.in_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.sender = None
        self.receiver = None
        self.conn_lock = threading.Lock()

        # 定期轮询入队列消息以显示在日志区
        self.master.after(100, self._poll_incoming)

    def log(self, t):
        """将日志写入滚动文本区（异步安全）"""
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {t}"

        def a():
            self.log_area.configure(state=tk.NORMAL)
            self.log_area.insert(tk.END, line + "\n")
            self.log_area.see(tk.END)
            self.log_area.configure(state=tk.DISABLED)

        self.master.after(0, a)

    def export_log(self):
        """导出日志到文件"""
        try:
            c = self.log_area.get("1.0", tk.END)
            if not c.strip():
                messagebox.showinfo("Export Log", "Log is empty.")
                return
            p = filedialog.asksaveasfilename(title="Save Log", defaultextension=".txt",
                                             filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
            if not p:
                return
            with open(p, "w", encoding="utf-8") as f:
                f.write(c)
            messagebox.showinfo("Export Log", f"Exported to: {p}")
        except Exception as e:
            messagebox.showerror("Export Log", f"Failed: {e}")

    def start(self):
        """根据选择的模式启动服务器或连接到服务器（客户端）"""
        mode = self.mode_var.get()
        host = self.entry_host.get().strip()
        port = int(self.entry_port.get().strip())

        if mode == "Server":
            if self.server_socket:
                messagebox.showinfo("Server", "Already running")
                return
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                s.listen(5)
                self.server_socket = s
                self.accept_thread = threading.Thread(target=self._accept_loop, name="AcceptThread", daemon=True)
                self.accept_thread.start()
                self.status_var.set(f"Server listening {host}:{port}")
                self.log(f"Server started {host}:{port}")
                self.btn_start.config(state=tk.DISABLED)
                self.btn_disconnect.config(state=tk.NORMAL)
            except Exception as e:
                messagebox.showerror("Server Error", f"Failed: {e}")
        else:
            with self.conn_lock:
                if self.conn_sock:
                    messagebox.showinfo("Connect", "Already connected")
                    return
            try:
                conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                conn.connect((host, port))
            except Exception as e:
                messagebox.showerror("Connect Error", f"Failed: {e}")
                return
            self.log(f"Connected to {host}:{port}")
            with self.conn_lock:
                self.conn_sock = conn
                self.conn_thread = threading.Thread(target=self._handle_connection, args=(conn, False),
                                                    name="ConnHandler", daemon=True)
                self.conn_thread.start()
            self.btn_start.config(state=tk.DISABLED)
            self.btn_disconnect.config(state=tk.NORMAL)
    def _accept_loop(self):
        """接受循环：接受入站连接，若已有活动连接则拒绝"""
        try:
            while self.server_socket:
                try:
                    conn, addr = self.server_socket.accept()
                except Exception:
                    break
                self.log(f"Accepted {addr}")
                with self.conn_lock:
                    if self.conn_sock:
                        self.log("Active connection exists; rejecting")
                        try:
                            conn.close()
                        except Exception:
                            pass
                        continue
                    self.conn_sock = conn
                    self.conn_thread = threading.Thread(target=self._handle_connection, args=(conn, True),
                                                        name="ConnHandler", daemon=True)
                    self.conn_thread.start()
        finally:
            self.log("Accept loop ended")
    def disconnect(self):
        """主动断开：停止事件、关闭 sockets、重置 UI"""
        self.log("Disconnect requested")
        self.status_var.set("Disconnecting...")
        self.stop_event.set()
        with self.conn_lock:
            if self.conn_sock:
                try:
                    self.conn_sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self.conn_sock.close()
                except Exception:
                    pass
                self.conn_sock = None
            if self.server_socket:
                try:
                    self.server_socket.close()
                except Exception:
                    pass
                self.server_socket = None
        # 恢复 UI 状态
        self.master.after(0, lambda: (
            self.btn_start.config(state=tk.NORMAL),
            self.btn_disconnect.config(state=tk.DISABLED),
            self.btn_send.config(state=tk.DISABLED),
            self.shared_var.set(""),
            self.fpr_var.set("")
        ))
        self.log("Disconnected")
        # 清除停止事件以允许再次连接
        self.stop_event.clear()
    def send_message(self):
        """将文本消息放入发送队列，供 SenderThread 加密并发送"""
        txt = self.entry_message.get().strip()
        if not txt:
            return
        with self.conn_lock:
            if not self.conn_sock or not self.sender or not self.sender.is_alive():
                messagebox.showwarning("Send", "No active connection")
                return
        try:
            self.send_queue.put_nowait(txt)
            self.log(f"You: {txt}")
            self.entry_message.delete(0, tk.END)
        except queue.Full:
            messagebox.showwarning("Send", "Send queue full")

    def _handle_connection(self, conn, is_server):
        """连接处理：握手、启动收发线程、监控线程运行状态并清理连接"""
        try:
            sk, rk, secret = perform_handshake(conn, is_server, self.log)
        except Exception as e:
            self.log(f"Handshake failed: {e}")
            with self.conn_lock:
                try:
                    conn.close()
                except Exception:
                    pass
                self.conn_sock = None
            self.master.after(0, lambda: (self.btn_start.config(state=tk.NORMAL), self.btn_disconnect.config(state=tk.DISABLED)))
            return

        # 握手成功：显示共享 secret（hex）与指纹（sha256 前 16 hex）
        sh_hex = secret.hex()
        fpr = hashlib.sha256(secret).hexdigest()[:16]
        self.log(f"Handshake done. Shared: {sh_hex}")
        self.log(f"Fingerprint: {fpr}")
        self.master.after(0, lambda: (self.shared_var.set(sh_hex), self.fpr_var.set(fpr), self.status_var.set("Connected")))
        # 重置队列和停止事件，启动发送/接收线程
        self.stop_event.clear()
        self.send_queue = queue.Queue()
        self.in_queue = queue.Queue()
        self.sender = SenderThread(conn, sk, self.send_queue, self.log, self.stop_event)
        self.receiver = ReceiverThread(conn, rk, self.in_queue, self.log, self.stop_event)
        self.sender.start()
        self.receiver.start()
        self.master.after(0, lambda: self.btn_send.config(state=tk.NORMAL))
        try:
            # 监控工作线程状态，若任一线程退出则终止连接
            while not self.stop_event.is_set():
                if self.stop_event.wait(0.2):
                    break
                if not self.sender.is_alive() or not self.receiver.is_alive():
                    self.log("Worker thread exited")
                    self.stop_event.set()
                    break
        finally:
            # 清理连接：关闭 socket、清空队列、重置 UI
            self.log("Cleaning connection")
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            self.stop_event.set()
            try:
                while not self.send_queue.empty():
                    self.send_queue.get_nowait()
            except Exception:
                pass
            self.master.after(0, lambda: (
                self.btn_send.config(state=tk.DISABLED),
                self.btn_start.config(state=tk.NORMAL),
                self.btn_disconnect.config(state=tk.DISABLED),
                self.shared_var.set(""),
                self.fpr_var.set(""),
                self.status_var.set("Idle")
            ))
            with self.conn_lock:
                self.conn_sock = None
            self.log("Connection handler finished")
    def _poll_incoming(self):
        """定期轮询入队列并将收到的消息写到日志"""
        try:
            while True:
                try:
                    m = self.in_queue.get_nowait()
                except queue.Empty:
                    break
                self.log(f"Peer: {m}")
        except Exception as e:
            self.log(f"Poll error: {e}")
        finally:
            self.master.after(100, self._poll_incoming)
def main():
    root = tk.Tk()
    app = SecureSocketGUI(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.disconnect(), root.destroy()))
    root.mainloop()
if __name__ == "__main__":
    main()
