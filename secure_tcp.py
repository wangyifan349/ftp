#!/usr/bin/env python3
"""
secure_tcp.py
简单的 x25519 + AES-256-GCM TCP 工具，带命令行菜单（非嵌套）与注释。

依赖:
    pip install cryptography

用法:
    python secure_tcp.py        # 进入菜单
    python secure_tcp.py server --host 0.0.0.0 --port 9000
    python secure_tcp.py client --host 127.0.0.1 --port 9000 --message "hello"
"""

import argparse
import os
import socket
import struct
import threading
import sys
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Constants
LENGTH_PREFIX = 4      # 4 bytes network-order length prefix
NONCE_SIZE = 12        # AES-GCM nonce size (recommended)
PUBKEY_SIZE = 32       # x25519 public key size

# Utility: read exactly n bytes or return None if EOF
def recv_all(conn: socket.socket, n: int):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf

# Send length-prefixed raw bytes
def send_raw(conn: socket.socket, data: bytes):
    header = struct.pack("!I", len(data))
    conn.sendall(header + data)

# Receive length-prefixed raw bytes
def recv_raw(conn: socket.socket):
    hdr = recv_all(conn, LENGTH_PREFIX)
    if hdr is None:
        return None
    (length,) = struct.unpack("!I", hdr)
    if length == 0:
        return b""
    return recv_all(conn, length)
# Generate x25519 keypair (private object + public bytes)
def generate_x25519_keypair():
    priv = x25519.X25519PrivateKey.generate()
    pub = priv.public_key()
    pubb = pub.public_bytes()  # 32 bytes
    return priv, pubb
# Deserialize peer public bytes to X25519PublicKey object
def deserialize_public(pub_bytes: bytes):
    return x25519.X25519PublicKey.from_public_bytes(pub_bytes)
# Derive shared secret via X25519
def derive_shared_secret(priv: x25519.X25519PrivateKey, peer_pub):
    return priv.exchange(peer_pub)  # returns 32-byte shared secret
# Derive AES-256 key via HKDF-SHA256
def derive_aes256_key(shared: bytes, info: bytes = b"tcp-x25519-aes256gcm"):
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info)
    return hkdf.derive(shared)
# Perform handshake on conn; is_server controls pubkey send/recv order.
# Returns AESGCM object on success.
def perform_handshake(conn: socket.socket, is_server: bool):
    # Generate ephemeral keypair
    priv, pubb = generate_x25519_keypair()
    if is_server:
        # Server: receive client pub first, then send server pub
        client_pub_bytes = recv_all(conn, PUBKEY_SIZE)
        if client_pub_bytes is None:
            raise ConnectionError("Failed to read client public key")
        send_all(conn, pubb)
        client_pub = deserialize_public(client_pub_bytes)
        shared = derive_shared_secret(priv, client_pub)
    else:
        # Client: send client pub first, then receive server pub
        send_all(conn, pubb)
        server_pub_bytes = recv_all(conn, PUBKEY_SIZE)
        if server_pub_bytes is None:
            raise ConnectionError("Failed to read server public key")
        server_pub = deserialize_public(server_pub_bytes)
        shared = derive_shared_secret(priv, server_pub)
    key = derive_aes256_key(shared)
    aead = AESGCM(key)
    return aead
# Helper to send raw bytes without length prefix (used for pubkey exchange)
def send_all(conn: socket.socket, data: bytes):
    conn.sendall(data)
# Encrypt plaintext with AES-GCM and send nonce||ciphertext as length-prefixed payload
def encrypt_and_send(conn: socket.socket, aead: AESGCM, plaintext: bytes):
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = aead.encrypt(nonce, plaintext, None)
    payload = nonce + ciphertext
    send_raw(conn, payload)
# Receive length-prefixed payload, split nonce and ciphertext, decrypt and return plaintext
def recv_and_decrypt(conn: socket.socket, aead: AESGCM):
    data = recv_raw(conn)
    if data is None:
        return None
    if len(data) < NONCE_SIZE:
        raise ValueError("Malformed message: too short")
    nonce = data[:NONCE_SIZE]
    ciphertext = data[NONCE_SIZE:]
    plaintext = aead.decrypt(nonce, ciphertext, None)
    return plaintext
# Server: handler for each client connection (echo with ACK)
def handle_client(conn: socket.socket, addr):
    try:
        aead = perform_handshake(conn, is_server=True)
        print(f"Handshake complete: {addr}")
        while True:
            pt = recv_and_decrypt(conn, aead)
            if pt is None:
                print(f"Connection closed by {addr}")
                break
            # Print received message (replace errors)
            print(f"[{addr}] {pt.decode(errors='replace')}")
            # Send back ACK message
            resp = b"ACK: " + pt
            encrypt_and_send(conn, aead, resp)
    except Exception as e:
        print(f"[{addr}] Error: {e}")
    finally:
        conn.close()
# Start server: listen and accept connections, spawn thread per client
def run_server(listen_host: str, listen_port: int):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((listen_host, listen_port))
    s.listen(5)
    print(f"Listening on {listen_host}:{listen_port}")
    try:
        while True:
            conn, addr = s.accept()
            print(f"Accepted {addr}")
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    finally:
        s.close()
# Run client: handshake then interactive or one-shot message
def run_client(server_host: str, server_port: int, one_message: bytes = None):
    with socket.create_connection((server_host, server_port)) as conn:
        aead = perform_handshake(conn, is_server=False)
        print("Handshake complete with server")
        if one_message is not None:
            encrypt_and_send(conn, aead, one_message)
            resp = recv_and_decrypt(conn, aead)
            if resp is None:
                print("No response from server")
            else:
                print("Server response:", resp.decode(errors="replace"))
            return
        # Interactive loop
        try:
            while True:
                line = input("> ")
                if not line:
                    continue
                if line.lower() in ("quit", "exit"):
                    break
                encrypt_and_send(conn, aead, line.encode())
                resp = recv_and_decrypt(conn, aead)
                if resp is None:
                    print("Server closed connection")
                    break
                print("Server:", resp.decode(errors="replace"))
        except (KeyboardInterrupt, EOFError):
            print("\nExiting client")
# Simple non-nested menu printed to stdout; user selects action
def menu():
    while True:
        print("\n=== x25519 TCP 工具 ===")
        print("1) 启动 server (监听)")
        print("2) 启动 client 并交互")
        print("3) client 发送一次消息后退出")
        print("4) 退出")
        choice = input("选择 (1-4): ").strip()
        if choice == "1":
            host = input("监听地址 (默认 0.0.0.0): ").strip() or "0.0.0.0"
            port_s = input("监听端口 (默认 9000): ").strip() or "9000"
            try:
                port = int(port_s)
            except ValueError:
                print("端口必须为数字")
                continue
            print(f"启动 server {host}:{port} (按 Ctrl+C 停止)")
            run_server(host, port)
            return
        elif choice == "2":
            host = input("服务器地址 (默认 127.0.0.1): ").strip() or "127.0.0.1"
            port_s = input("服务器端口 (默认 9000): ").strip() or "9000"
            try:
                port = int(port_s)
            except ValueError:
                print("端口必须为数字")
                continue
            print(f"连接到 {host}:{port}")
            run_client(host, port, one_message=None)
            return
        elif choice == "3":
            host = input("服务器地址 (默认 127.0.0.1): ").strip() or "127.0.0.1"
            port_s = input("服务器端口 (默认 9000): ").strip() or "9000"
            msg = input("要发送的消息: ")
            try:
                port = int(port_s)
            except ValueError:
                print("端口必须为数字")
                continue
            run_client(host, port, one_message=msg.encode())
            return
        elif choice == "4":
            print("退出")
            return
        else:
            print("无效选择，请重试")
# CLI entry: supports direct server/client flags or menu
def parse_args_and_run():
    parser = argparse.ArgumentParser(description="x25519 TCP 工具（菜单或直接模式）")
    sub = parser.add_subparsers(dest="mode")
    srv = sub.add_parser("server", help="直接以 server 模式运行")
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=9000)
    cli = sub.add_parser("client", help="直接以 client 模式运行")
    cli.add_argument("--host", default="127.0.0.1")
    cli.add_argument("--port", type=int, default=9000)
    cli.add_argument("--message", help="发送一次消息后退出")
    args = parser.parse_args()
    if args.mode == "server":
        run_server(args.host, args.port)
    elif args.mode == "client":
        one_msg = args.message.encode() if args.message else None
        run_client(args.host, args.port, one_message=one_msg)
    else:
        menu()
if __name__ == "__main__":
    parse_args_and_run()
