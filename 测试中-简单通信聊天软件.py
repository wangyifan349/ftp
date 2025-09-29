#!/usr/bin/env python3
"""
secure_gui_fixed.py

Tkinter GUI + X25519 + AES-GCM secure pipe — 修正版。
修复点：
- 正确的公钥序列化/反序列化（raw 32 bytes）
- 严格的 recv_exact，握手出错处理
- Connection 封装：stop_event, 非 daemon 线程, join, 并发关闭协调
- server accept 循环支持多连接（为每个连接创建 Connection 对象）
- 发送队列终止机制 (None 哨兵)，线程在 stop_event 下优雅退出
"""

import socket
import threading
import struct
import os
import queue
import sys
import traceback
import tkinter as tk
from tkinter import scrolledtext, messagebox
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from typing import Optional

# ---- 配置 ----
NONCE_SIZE = 12
KEY_SIZE = 32
BUFFER_SIZE = 4096
THREAD_JOIN_TIMEOUT = 2.0  # seconds

# ---- 工具 ----
def log_print(s):
    print(s)

def recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    data = b''
    try:
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data
    except Exception:
        return None

def send_all(sock: socket.socket, data: bytes) -> None:
    totalsent = 0
    while totalsent < len(data):
        sent = sock.send(data[totalsent:])
        if sent == 0:
            raise RuntimeError("socket connection broken")
        totalsent += sent

# ---- X25519 握手（使用 raw serialzation） ----
def x25519_initiator(sock: socket.socket):
    priv = X25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    if len(pub) != 32:
        raise RuntimeError("unexpected public key length")
    send_all(sock, pub)
    peer = recv_exact(sock, 32)
    if peer is None or len(peer) != 32:
        raise RuntimeError("failed to receive 32-byte peer public key")
    peer_pub = X25519PublicKey.from_public_bytes(peer)
    shared = priv.exchange(peer_pub)
    hkdf = HKDF(algorithm=hashes.SHA256(), length=KEY_SIZE, salt=None, info=b"secure-gui-fixed")
    key = hkdf.derive(shared)
    return AESGCM(key)

def x25519_responder(sock: socket.socket):
    peer = recv_exact(sock, 32)
    if peer is None or len(peer) != 32:
        raise RuntimeError("failed to receive 32-byte peer public key")
    peer_pub = X25519PublicKey.from_public_bytes(peer)
    priv = X25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    if len(pub) != 32:
        raise RuntimeError("unexpected public key length")
    send_all(sock, pub)
    shared = priv.exchange(peer_pub)
    hkdf = HKDF(algorithm=hashes.SHA256(), length=KEY_SIZE, salt=None, info=b"secure-gui-fixed")
    key = hkdf.derive(shared)
    return AESGCM(key)

# ---- 包装/解包 ----
def encrypt_pack(aesgcm: AESGCM, plaintext: bytes) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    payload = nonce + ct
    return struct.pack("!I", len(payload)) + payload

def unpack_and_decrypt(aesgcm: AESGCM, sock: socket.socket) -> Optional[bytes]:
    hdr = recv_exact(sock, 4)
    if hdr is None:
        return None
    length = struct.unpack("!I", hdr)[0]
    if length == 0:
        return b''
    payload = recv_exact(sock, length)
    if payload is None or len(payload) != length:
        return None
    nonce = payload[:NONCE_SIZE]
    ct = payload[NONCE_SIZE:]
    pt = aesgcm.decrypt(nonce, ct, None)
    return pt

# ---- Connection 封装 ----
class Connection:
    def __init__(self, sock: socket.socket, peer, is_initiator: bool, app_logger):
        self.sock = sock
        self.peer = peer
        self.is_initiator = is_initiator
        self.app_logger = app_logger
        self.send_q = queue.Queue()
        self.recv_q = queue.Queue()
        self.stop_event = threading.Event()
        self.threads = []  # list of threading.Thread
        self.aesgcm: Optional[AESGCM] = None
        self.lock = threading.Lock()  # protect socket close

    def start(self):
        th = threading.Thread(target=self._handshake_and_start_workers, daemon=False)
        th.start()
        self.threads.append(th)

    def _handshake_and_start_workers(self):
        try:
            if self.is_initiator:
                self.aesgcm = x25519_initiator(self.sock)
                self.app_logger(f"[{self.peer}] Handshake complete (initiator).")
            else:
                self.aesgcm = x25519_responder(self.sock)
                self.app_logger(f"[{self.peer}] Handshake complete (responder).")
        except Exception as e:
            self.app_logger(f"[{self.peer}] Handshake failed: {e}")
            self.close()
            # ensure recv_q gets termination
            self.recv_q.put(None)
            return

        # start send/recv worker threads (non-daemon)
        t_send = threading.Thread(target=self._send_worker, daemon=False, name=f"send-{self.peer}")
        t_recv = threading.Thread(target=self._recv_worker, daemon=False, name=f"recv-{self.peer}")
        t_send.start()
        t_recv.start()
        self.threads.extend([t_send, t_recv])
        self.app_logger(f"[{self.peer}] Send/Recv workers started.")

    def _send_worker(self):
        try:
            while not self.stop_event.is_set():
                try:
                    item = self.send_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if item is None:
                    # termination sentinel
                    break
                if not isinstance(item, bytes):
                    item = item.encode()
                # pack & send
                try:
                    packet = encrypt_pack(self.aesgcm, item)
                    with self.lock:
                        send_all(self.sock, packet)
                    self.app_logger(f"[{self.peer}] Sent {len(item)} bytes")
                except Exception as e:
                    self.app_logger(f"[{self.peer}] Send error: {e}")
                    break
        finally:
            # attempt to shutdown write side once
            try:
                with self.lock:
                    try:
                        self.sock.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass
            except Exception:
                pass
            self.app_logger(f"[{self.peer}] Send worker exiting")

    def _recv_worker(self):
        try:
            while not self.stop_event.is_set():
                try:
                    pt = unpack_and_decrypt(self.aesgcm, self.sock)
                except Exception as e:
                    self.app_logger(f"[{self.peer}] Decrypt/recv error: {e}")
                    pt = None
                if pt is None:
                    break
                self.recv_q.put(pt)
                self.app_logger(f"[{self.peer}] Received {len(pt)} bytes")
        finally:
            # mark closed
            try:
                with self.lock:
                    try:
                        self.sock.shutdown(socket.SHUT_RD)
                    except Exception:
                        pass
            except Exception:
                pass
            # signal receiver end
            self.recv_q.put(None)
            self.app_logger(f"[{self.peer}] Recv worker exiting")

    def send(self, data: bytes):
        if self.stop_event.is_set():
            raise RuntimeError("connection stopping")
        self.send_q.put(data)

    def close(self):
        # idempotent close
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        # place sentinel to unblock send worker
        try:
            self.send_q.put(None)
        except Exception:
            pass
        # close socket safely
        with self.lock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
        # join threads
        for t in self.threads:
            try:
                if t.is_alive():
                    t.join(timeout=THREAD_JOIN_TIMEOUT)
            except Exception:
                pass
        self.app_logger(f"[{self.peer}] Connection closed and threads joined")

# ---- Server accept loop (persistent) ----
def server_accept_loop(listen_host: str, listen_port: int, app_logger, connections_list, stop_event: threading.Event):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((listen_host, listen_port))
        srv.listen(10)
    except Exception as e:
        app_logger(f"Server bind/listen error: {e}")
        return
    app_logger(f"Server listening on {listen_host}:{listen_port}")
    srv.settimeout(1.0)
    try:
        while not stop_event.is_set():
            try:
                client, addr = srv.accept()
            except socket.timeout:
                continue
            except Exception as e:
                app_logger(f"Accept error: {e}")
                continue
            app_logger(f"Accepted {addr}")
            conn = Connection(client, addr, is_initiator=False, app_logger=app_logger)
            connections_list.append(conn)
            conn.start()
    finally:
        try:
            srv.close()
        except:
            pass
        app_logger("Server accept loop exiting")

# ---- Client connect routine ----
def client_connect(remote_host: str, remote_port: int, app_logger, connections_list):
    try:
        sock = socket.create_connection((remote_host, remote_port), timeout=10)
    except Exception as e:
        app_logger(f"Client connect error: {e}")
        return
    addr = (remote_host, remote_port)
    app_logger(f"Connected to {addr}")
    conn = Connection(sock, addr, is_initiator=True, app_logger=app_logger)
    connections_list.append(conn)
    conn.start()

# ---- GUI 应用 ----
class SecureGUIFixed:
    def __init__(self, root):
        self.root = root
        root.title("Secure Pipe Fixed (X25519 + AES-GCM)")
        # UI
        frm = tk.Frame(root)
        frm.pack(padx=6, pady=6, fill='x')

        tk.Label(frm, text="Mode:").grid(row=0, column=0, sticky='w')
        self.mode_var = tk.StringVar(value="server")
        tk.Radiobutton(frm, text="Server", variable=self.mode_var, value="server").grid(row=0, column=1, sticky='w')
        tk.Radiobutton(frm, text="Client", variable=self.mode_var, value="client").grid(row=0, column=2, sticky='w')

        tk.Label(frm, text="Listen IP:").grid(row=1, column=0, sticky='w')
        self.listen_entry = tk.Entry(frm); self.listen_entry.grid(row=1, column=1, columnspan=2, sticky='we')
        self.listen_entry.insert(0, "0.0.0.0")

        tk.Label(frm, text="Port:").grid(row=2, column=0, sticky='w')
        self.port_entry = tk.Entry(frm, width=8); self.port_entry.grid(row=2, column=1, sticky='w')
        self.port_entry.insert(0, "12345")

        tk.Label(frm, text="Remote Host:").grid(row=3, column=0, sticky='w')
        self.remote_entry = tk.Entry(frm); self.remote_entry.grid(row=3, column=1, columnspan=2, sticky='we')
        self.remote_entry.insert(0, "127.0.0.1")

        tk.Label(frm, text="Remote Port:").grid(row=4, column=0, sticky='w')
        self.remote_port_entry = tk.Entry(frm, width=8); self.remote_port_entry.grid(row=4, column=1, sticky='w')
        self.remote_port_entry.insert(0, "12345")

        self.start_btn = tk.Button(frm, text="Start", command=self.start)
        self.start_btn.grid(row=5, column=0, pady=6)
        self.stop_btn = tk.Button(frm, text="Stop", command=self.stop, state='disabled')
        self.stop_btn.grid(row=5, column=1, pady=6)

        tk.Label(root, text="Log:").pack(anchor='w', padx=6)
        self.log_box = scrolledtext.ScrolledText(root, height=10, state='disabled')
        self.log_box.pack(fill='both', padx=6, pady=4, expand=True)

        bot = tk.Frame(root); bot.pack(fill='x', padx=6, pady=6)
        tk.Label(bot, text="Send:").grid(row=0, column=0, sticky='w')
        self.send_entry = tk.Entry(bot); self.send_entry.grid(row=0, column=1, sticky='we')
        self.send_btn = tk.Button(bot, text="Send", command=self.gui_send, state='disabled'); self.send_btn.grid(row=0, column=2, padx=4)
        bot.columnconfigure(1, weight=1)

        tk.Label(root, text="Received:").pack(anchor='w', padx=6)
        self.recv_box = scrolledtext.ScrolledText(root, height=8, state='disabled')
        self.recv_box.pack(fill='both', padx=6, pady=4, expand=True)

        # internals
        self.server_stop_event = threading.Event()
        self.server_thread = None
        self.connections = []  # list[Connection]
        self.active_conn: Optional[Connection] = None
        self.poll_ms = 200
        self.running = False

    def app_logger(self, msg: str):
        log_print(msg)
        self.log_box.configure(state='normal')
        self.log_box.insert('end', msg + "\n")
        self.log_box.see('end')
        self.log_box.configure(state='disabled')

    def start(self):
        mode = self.mode_var.get()
        port = int(self.port_entry.get())
        if mode == 'server':
            host = self.listen_entry.get()
            self.server_stop_event.clear()
            self.server_thread = threading.Thread(target=server_accept_loop, args=(host, port, self.app_logger, self.connections, self.server_stop_event), daemon=True)
            self.server_thread.start()
            self.app_logger(f"Server started on {host}:{port}")
        else:
            remote = self.remote_entry.get()
            rport = int(self.remote_port_entry.get())
            t = threading.Thread(target=client_connect, args=(remote, rport, self.app_logger, self.connections), daemon=True)
            t.start()
            self.app_logger(f"Client connecting to {remote}:{rport}")

        self.running = True
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.send_btn.config(state='normal')
        self.root.after(self.poll_ms, self.poll_connections)

    def stop(self):
        self.running = False
        # stop server accept loop
        self.server_stop_event.set()
        # close all connections
        for conn in list(self.connections):
            try:
                conn.close()
            except Exception:
                pass
        self.connections.clear()
        self.active_conn = None
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.send_btn.config(state='disabled')
        self.app_logger("Stopped all activities")

    def poll_connections(self):
        if not self.running:
            return
        # pick an active connection if not set
        if self.active_conn is None and self.connections:
            # pick the last added that has not been closed
            for c in reversed(self.connections):
                if not c.stop_event.is_set():
                    self.active_conn = c
                    self.app_logger(f"Active connection set to {c.peer}")
                    break

        # poll recv_q from active_conn
        if self.active_conn:
            try:
                while True:
                    item = self.active_conn.recv_q.get_nowait()
                    if item is None:
                        self.app_logger(f"Peer {self.active_conn.peer} closed connection")
                        # remove from list
                        try:
                            self.connections.remove(self.active_conn)
                        except ValueError:
                            pass
                        self.active_conn = None
                        break
                    try:
                        s = item.decode()
                    except Exception:
                        s = repr(item)
                    self.recv_box.configure(state='normal')
                    self.recv_box.insert('end', s + "\n")
                    self.recv_box.see('end')
                    self.recv_box.configure(state='disabled')
            except queue.Empty:
                pass
        self.root.after(self.poll_ms, self.poll_connections)
    def gui_send(self):
        text = self.send_entry.get()
        if not text:
            return
        if not self.active_conn:
            messagebox.showwarning("No connection", "No active connection to send")
            return
        try:
            self.active_conn.send(text.encode())
            self.app_logger(f"Queued {len(text)} bytes to send to {self.active_conn.peer}")
            self.send_entry.delete(0, 'end')
        except Exception as e:
            self.app_logger(f"Send failed: {e}")
def main():
    root = tk.Tk()
    app = SecureGUIFixed(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop(), root.destroy()))
    root.mainloop()
if __name__ == "__main__":
    main()
