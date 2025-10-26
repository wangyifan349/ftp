#!/usr/bin/env python3
"""
secure_tcp.py - 稳定版 x25519 + AES-256-GCM TCP 工具（线程池、超时、日志、优雅关机）
依赖:
    pip install cryptography
特性:
- x25519 握手 + HKDF-SHA256 -> AES-256-GCM
- 4 字节长度前缀，12 字节 nonce
- ThreadPoolExecutor 管理客户端处理
- 连接与 I/O 超时
- 日志（可设置 DEBUG/INFO）
- 优雅关机（SIGINT/SIGTERM）
- 每连接消息大小限制与简单速率限制
- 非嵌套菜单，清晰注释
"""
import argparse
import logging
import os
import signal
import socket
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
# ------- Configuration constants -------
LENGTH_PREFIX = 4          # bytes
NONCE_SIZE = 12            # AES-GCM nonce
PUBKEY_SIZE = 32           # x25519 public key bytes
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # max plaintext/ciphertext payload allowed (10 MB)
SOCKET_TIMEOUT = 10.0      # seconds for socket read/write operations
HANDSHAKE_TIMEOUT = 5.0    # seconds for handshake steps
LISTEN_BACKLOG = 128
THREADPOOL_MAX_WORKERS = 32  # max concurrent client handlers
CONN_RATE_LIMIT_PER_SEC = 10  # simple per-connection messages per second
# ---------------------------------------
shutdown_event = threading.Event()
# Logging setup
logger = logging.getLogger("secure_tcp")
logger.setLevel(logging.INFO)
_log_handler = logging.StreamHandler()
_log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_log_handler.setFormatter(_log_formatter)
logger.addHandler(_log_handler)
# ---------- Low-level helpers ----------
def recv_all(conn: socket.socket, n: int) -> Optional[bytes]:
    """Read exactly n bytes or return None on EOF/timeout."""
    data = b""
    conn.settimeout(SOCKET_TIMEOUT)
    while len(data) < n:
        try:
            chunk = conn.recv(n - len(data))
        except socket.timeout:
            logger.debug("recv_all timeout")
            return None
        except Exception as e:
            logger.debug("recv_all error: %s", e)
            return None
        if not chunk:
            return None
        data += chunk
    return data
def send_all(conn: socket.socket, data: bytes) -> bool:
    """Send all bytes; return False on failure."""
    conn.settimeout(SOCKET_TIMEOUT)
    try:
        conn.sendall(data)
        return True
    except Exception as e:
        logger.debug("send_all error: %s", e)
        return False
def send_raw(conn: socket.socket, data: bytes) -> bool:
    """Send length-prefixed payload."""
    header = struct.pack("!I", len(data))
    return send_all(conn, header + data)
def recv_raw(conn: socket.socket) -> Optional[bytes]:
    """Receive length-prefixed payload; returns None on EOF/timeout."""
    hdr = recv_all(conn, LENGTH_PREFIX)
    if hdr is None:
        return None
    (length,) = struct.unpack("!I", hdr)
    if length < 0 or length > MAX_MESSAGE_SIZE:
        logger.debug("recv_raw invalid length: %d", length)
        return None
    return recv_all(conn, length)
# ---------- Crypto helpers ----------
def generate_x25519_keypair():
    """Generate ephemeral x25519 private key object and public bytes."""
    priv = x25519.X25519PrivateKey.generate()
    pubb = priv.public_key().public_bytes()
    return priv, pubb
def deserialize_public(pub_bytes: bytes):
    """Deserialize peer public bytes into X25519PublicKey."""
    return x25519.X25519PublicKey.from_public_bytes(pub_bytes)
def derive_shared_secret(priv: x25519.X25519PrivateKey, peer_pub) -> bytes:
    """Compute x25519 shared secret (32 bytes)."""
    return priv.exchange(peer_pub)
def derive_aes256_key(shared: bytes, info: bytes = b"tcp-x25519-aes256gcm") -> bytes:
    """Derive 32-byte AES-256 key via HKDF-SHA256."""
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info)
    return hkdf.derive(shared)
# ---------- Handshake & message ops ----------
def perform_handshake(conn: socket.socket, is_server: bool) -> Optional[AESGCM]:
    """
    Perform x25519 handshake. Server: recv client pub then send server pub.
    Client: send client pub then recv server pub.
    Returns AESGCM instance or None on failure.
    """
    conn.settimeout(HANDSHAKE_TIMEOUT)
    priv, pubb = generate_x25519_keypair()
    try:
        if is_server:
            client_pub_bytes = recv_all(conn, PUBKEY_SIZE)
            if client_pub_bytes is None or len(client_pub_bytes) != PUBKEY_SIZE:
                logger.debug("Handshake: failed to read client pub")
                return None
            if not send_all(conn, pubb):
                logger.debug("Handshake: failed to send server pub")
                return None
            client_pub = deserialize_public(client_pub_bytes)
            shared = derive_shared_secret(priv, client_pub)
        else:
            if not send_all(conn, pubb):
                logger.debug("Handshake: client failed to send pub")
                return None
            server_pub_bytes = recv_all(conn, PUBKEY_SIZE)
            if server_pub_bytes is None or len(server_pub_bytes) != PUBKEY_SIZE:
                logger.debug("Handshake: client failed to read server pub")
                return None
            server_pub = deserialize_public(server_pub_bytes)
            shared = derive_shared_secret(priv, server_pub)
    except Exception as e:
        logger.debug("Handshake exception: %s", e)
        return None
    finally:
        conn.settimeout(SOCKET_TIMEOUT)
    try:
        key = derive_aes256_key(shared)
        aead = AESGCM(key)
        return aead
    except Exception as e:
        logger.debug("HKDF/AES init failed: %s", e)
        return None
def encrypt_and_send(conn: socket.socket, aead: AESGCM, plaintext: bytes) -> bool:
    """Encrypt plaintext and send nonce||ciphertext as length-prefixed payload."""
    if len(plaintext) > MAX_MESSAGE_SIZE:
        logger.debug("Message too large to send")
        return False
    nonce = os.urandom(NONCE_SIZE)
    try:
        ct = aead.encrypt(nonce, plaintext, None)
    except Exception as e:
        logger.debug("Encryption error: %s", e)
        return False
    return send_raw(conn, nonce + ct)
def recv_and_decrypt(conn: socket.socket, aead: AESGCM) -> Optional[bytes]:
    """Receive length-prefixed payload, parse nonce, decrypt and return plaintext."""
    data = recv_raw(conn)
    if data is None:
        return None
    if len(data) < NONCE_SIZE:
        logger.debug("Malformed incoming payload (too short)")
        return None
    nonce = data[:NONCE_SIZE]
    ct = data[NONCE_SIZE:]
    try:
        pt = aead.decrypt(nonce, ct, None)
        return pt
    except Exception as e:
        logger.debug("Decryption failed: %s", e)
        return None
# ---------- Connection handler (per-client) ----------
def client_handler(conn: socket.socket, addr):
    """
    Handle a single client connection.
    - perform handshake
    - loop: recv message, log, send ACK
    - implement simple per-connection rate limiting
    """
    logger.info("Handling connection %s", addr)
    conn.settimeout(SOCKET_TIMEOUT)
    aead = perform_handshake(conn, is_server=True)
    if aead is None:
        logger.info("Handshake failed for %s", addr)
        conn.close()
        return
    logger.info("Handshake complete with %s", addr)
    tokens = CONN_RATE_LIMIT_PER_SEC
    last_ts = time.time()
    try:
        while not shutdown_event.is_set():
            # simple token bucket refill
            now = time.time()
            elapsed = now - last_ts
            if elapsed >= 1.0:
                tokens = CONN_RATE_LIMIT_PER_SEC
                last_ts = now
            if tokens <= 0:
                time.sleep(0.05)
                continue
            pt = recv_and_decrypt(conn, aead)
            if pt is None:
                # treat None as connection closed or error
                logger.info("Connection %s closed or error", addr)
                break
            tokens -= 1
            # Log message safely
            try:
                text = pt.decode(errors="replace")
            except Exception:
                text = repr(pt)
            logger.info("Received from %s: %s", addr, text)
            # Respond with ACK
            resp = b"ACK: " + pt
            ok = encrypt_and_send(conn, aead, resp)
            if not ok:
                logger.info("Failed to send response to %s", addr)
                break
    except Exception as e:
        logger.exception("Exception in client_handler for %s: %s", addr, e)
    finally:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        conn.close()
        logger.info("Connection %s closed", addr)
# ---------- Server lifecycle ----------
def run_server(listen_host: str, listen_port: int, max_workers: int):
    """Start listening socket, accept connections, dispatch to thread pool."""
    logger.info("Starting server on %s:%d", listen_host, listen_port)
    listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen_sock.bind((listen_host, listen_port))
    listen_sock.listen(LISTEN_BACKLOG)
    listen_sock.settimeout(1.0)  # short timeout for accept loop to check shutdown
    executor = ThreadPoolExecutor(max_workers=max_workers)
    futures = set()
    try:
        while not shutdown_event.is_set():
            try:
                conn, addr = listen_sock.accept()
            except socket.timeout:
                continue
            except Exception as e:
                logger.error("Accept failed: %s", e)
                break
            logger.info("Accepted connection from %s", addr)
            conn.settimeout(SOCKET_TIMEOUT)
            future = executor.submit(client_handler, conn, addr)
            futures.add(future)
            # Clean up done futures to avoid memory growth
            done = {f for f in futures if f.done()}
            futures -= done

        logger.info("Server shutting down, waiting for handlers to finish...")
    finally:
        shutdown_event.set()
        listen_sock.close()
        # Wait for running handlers to finish with timeout
        executor.shutdown(wait=True)
        logger.info("Server stopped")
# ---------- Client operations ----------
def run_client(server_host: str, server_port: int, one_message: Optional[bytes] = None):
    """Connect to server, perform handshake, optionally send one message or interactive loop."""
    addr = (server_host, server_port)
    logger.info("Connecting to %s:%d", server_host, server_port)
    try:
        conn = socket.create_connection(addr, timeout=SOCKET_TIMEOUT)
    except Exception as e:
        logger.error("Failed to connect: %s", e)
        return
    conn.settimeout(SOCKET_TIMEOUT)
    try:
        aead = perform_handshake(conn, is_server=False)
        if aead is None:
            logger.error("Handshake failed with server")
            conn.close()
            return
        logger.info("Handshake complete with server")

        if one_message is not None:
            ok = encrypt_and_send(conn, aead, one_message)
            if not ok:
                logger.error("Send failed")
                conn.close()
                return
            resp = recv_and_decrypt(conn, aead)
            if resp is None:
                logger.error("No response or decryption failed")
            else:
                logger.info("Server response: %s", resp.decode(errors="replace"))
            conn.close()
            return

        # interactive mode
        try:
            while True:
                line = input("> ")
                if not line:
                    continue
                if line.lower() in ("quit", "exit"):
                    break
                ok = encrypt_and_send(conn, aead, line.encode())
                if not ok:
                    logger.error("Send failed")
                    break
                resp = recv_and_decrypt(conn, aead)
                if resp is None:
                    logger.error("Server closed connection or decryption failed")
                    break
                print("Server:", resp.decode(errors="replace"))
        except (KeyboardInterrupt, EOFError):
            logger.info("Client exiting")
    finally:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        conn.close()
# ---------- Menu and CLI ----------
def menu():
    """Non-nested menu loop; single-level choices."""
    while True:
        print("\n=== x25519 TCP 稳定版 ===")
        print("1) 启动 server (监听)")
        print("2) 启动 client 并交互")
        print("3) client 发送一次消息后退出")
        print("4) 退出")
        choice = input("选择 (1-4): ").strip()
        if choice == "1":
            host = input("监听地址 (默认 0.0.0.0): ").strip() or "0.0.0.0"
            port_s = input("监听端口 (默认 9000): ").strip() or "9000"
            workers_s = input(f"线程池大小 (默认 {THREADPOOL_MAX_WORKERS}): ").strip() or str(THREADPOOL_MAX_WORKERS)
            try:
                port = int(port_s)
                workers = int(workers_s)
            except ValueError:
                print("端口/线程数必须为数字")
                continue
            # Start server in main thread; will block until shutdown
            run_server(host, port, max_workers=workers)
            return
        elif choice == "2":
            host = input("服务器地址 (默认 127.0.0.1): ").strip() or "127.0.0.1"
            port_s = input("服务器端口 (默认 9000): ").strip() or "9000"
            try:
                port = int(port_s)
            except ValueError:
                print("端口必须为数字")
                continue
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
# ---------- Signal handling for graceful shutdown ----------
def _signal_handler(signum, frame):
    logger.info("Received signal %s, shutting down...", signum)
    shutdown_event.set()
signal.signal(signal.SIGINT, _signal_handler)
try:
    signal.signal(signal.SIGTERM, _signal_handler)
except Exception:
    # Windows may not support SIGTERM
    pass
# ---------- Argument parsing and entrypoint ----------
def parse_args_and_run():
    parser = argparse.ArgumentParser(description="x25519 TCP 稳定工具（线程池、超时、日志）")
    parser.add_argument("--log", choices=["DEBUG", "INFO"], default="INFO", help="日志级别")
    sub = parser.add_subparsers(dest="mode")
    srv = sub.add_parser("server", help="直接以 server 模式运行")
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=9000)
    srv.add_argument("--workers", type=int, default=THREADPOOL_MAX_WORKERS)
    cli = sub.add_parser("client", help="直接以 client 模式运行")
    cli.add_argument("--host", default="127.0.0.1")
    cli.add_argument("--port", type=int, default=9000)
    cli.add_argument("--message", help="发送一次消息后退出")
    args = parser.parse_args()
    # configure logging level
    lvl = logging.DEBUG if args.log == "DEBUG" else logging.INFO
    logger.setLevel(lvl)
    _log_handler.setLevel(lvl)
    if args.mode == "server":
        # Run server directly
        run_server(args.host, args.port, max_workers=args.workers)
    elif args.mode == "client":
        one_msg = args.message.encode() if args.message else None
        run_client(args.host, args.port, one_message=one_msg)
    else:
        # Interactive menu
        menu()
if __name__ == "__main__":
    parse_args_and_run()
