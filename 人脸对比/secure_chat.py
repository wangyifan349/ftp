#!/usr/bin/env python3
"""
Secure TCP chat with interactive startup menu (no CLI args required).
Features:
- Interactive console menu to choose mode (server/client), host, port, cipher.
- X25519 key exchange -> HKDF -> 32-byte symmetric key
- AEAD per-message encryption (AES-GCM or ChaCha20-Poly1305)
- 64-bit message counters used as associated data and for nonce construction
- Message framing with 4-byte big-endian length prefix
- Independent sender/receiver threads with queue
- Optional persistent receive counter save/load
"""
import socket
import threading
import queue
import struct
import os
import sys
import signal
import json
from typing import Tuple

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
# --- Constants ---
KEY_LENGTH = 32
NONCE_LENGTH_AESGCM = 12
NONCE_LENGTH_CHACHA = 12
LENGTH_PREFIX_SIZE = 4
MAX_MESSAGE_BODY = 10 * 1024 * 1024
# --- Utilities ---
def generate_x25519_keypair() -> Tuple[x25519.X25519PrivateKey, x25519.X25519PublicKey]:
    private = x25519.X25519PrivateKey.generate()
    public = private.public_key()
    return private, public
def derive_symmetric_key(shared_secret: bytes, info: bytes = b"chat ae key") -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=KEY_LENGTH, salt=None, info=info)
    return hkdf.derive(shared_secret)
def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed while receiving exact bytes")
        buf += chunk
    return buf
def send_with_length_prefix(sock: socket.socket, data: bytes) -> None:
    length_prefix = struct.pack("!I", len(data))
    sock.sendall(length_prefix + data)
def recv_message_frame(sock: socket.socket) -> bytes:
    prefix = recv_exact(sock, LENGTH_PREFIX_SIZE)
    (length,) = struct.unpack("!I", prefix)
    if length > MAX_MESSAGE_BODY:
        raise ValueError("incoming message too large")
    body = recv_exact(sock, length)
    return body
# --- AEAD wrapper ---
class AEADCipher:
    def __init__(self, key: bytes, use_chacha: bool = False, persist_recv_counter_path: str = None):
        self.key = key
        self.use_chacha = use_chacha
        if use_chacha:
            self.aead = ChaCha20Poly1305(self.key)
            self.nonce_length = NONCE_LENGTH_CHACHA
        else:
            self.aead = AESGCM(self.key)
            self.nonce_length = NONCE_LENGTH_AESGCM
        self.send_counter = 0
        self.recv_counter = 0
        self.nonce_prefix = os.urandom(self.nonce_length - 8)
        self.persist_recv_counter_path = persist_recv_counter_path
        if persist_recv_counter_path:
            self._load_recv_counter()
    def _nonce(self, counter: int) -> bytes:
        return self.nonce_prefix + struct.pack("!Q", counter)
    def encrypt_message(self, plaintext: bytes, additional_data: bytes = b"") -> bytes:
        counter = self.send_counter
        nonce = self._nonce(counter)
        ciphertext = self.aead.encrypt(nonce, plaintext, additional_data)
        wire = struct.pack("!Q", counter) + nonce + ciphertext
        self.send_counter += 1
        return wire
    def decrypt_message(self, wire: bytes, additional_data: bytes = b"") -> bytes:
        if len(wire) < 8 + self.nonce_length:
            raise ValueError("wire too short for AEAD message")
        counter = struct.unpack("!Q", wire[:8])[0]
        nonce = wire[8:8 + self.nonce_length]
        ciphertext = wire[8 + self.nonce_length:]
        if counter < self.recv_counter:
            raise ValueError("message counter decreased (possible replay/reorder)")
        plaintext = self.aead.decrypt(nonce, ciphertext, additional_data)
        self.recv_counter = counter + 1
        if self.persist_recv_counter_path:
            self._save_recv_counter()
        return plaintext
    def _load_recv_counter(self):
        try:
            with open(self.persist_recv_counter_path, "r") as fh:
                data = json.load(fh)
                self.recv_counter = int(data.get("recv_counter", 0))
                # nonce prefix persistent optional: if stored, ensure match
                saved_prefix = data.get("nonce_prefix")
                if saved_prefix:
                    self.nonce_prefix = bytes.fromhex(saved_prefix)
        except FileNotFoundError:
            return
        except Exception:
            return
    def _save_recv_counter(self):
        try:
            data = {"recv_counter": self.recv_counter, "nonce_prefix": self.nonce_prefix.hex()}
            tmp = self.persist_recv_counter_path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(data, fh)
            os.replace(tmp, self.persist_recv_counter_path)
        except Exception:
            pass
# --- ChatPeer base ---
class ChatPeer:
    def __init__(self, sock: socket.socket, aead: AEADCipher):
        self.socket = sock
        self.aead = aead
        self.send_queue = queue.Queue()
        self.receiver_thread = None
        self.sender_thread = None
        self.stop_event = threading.Event()
    def start_io_threads(self):
        self.receiver_thread = threading.Thread(target=self._receiver_loop, daemon=True, name="ReceiverThread")
        self.sender_thread = threading.Thread(target=self._sender_loop, daemon=True, name="SenderThread")
        self.receiver_thread.start()
        self.sender_thread.start()
    def stop(self):
        self.stop_event.set()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.socket.close()
        except Exception:
            pass
    def _sender_loop(self):
        try:
            while not self.stop_event.is_set():
                try:
                    user_message = self.send_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if user_message is None:
                    break
                ad = struct.pack("!Q", self.aead.send_counter)
                wire = self.aead.encrypt_message(user_message.encode("utf-8"), additional_data=ad)
                send_with_length_prefix(self.socket, wire)
        except (ConnectionError, OSError) as e:
            print(f"Sender loop exiting due to connection error: {e}", file=sys.stderr)
        except Exception as e:
            print(f"Sender loop unexpected error: {e}", file=sys.stderr)
        finally:
            self.stop_event.set()
    def _receiver_loop(self):
        try:
            while not self.stop_event.is_set():
                try:
                    wire = recv_message_frame(self.socket)
                except ConnectionError:
                    print("Receiver: connection closed by peer", file=sys.stderr)
                    break
                except Exception as e:
                    print(f"Receiver: frame read error: {e}", file=sys.stderr)
                    break

                if len(wire) < 8:
                    print("Receiver: wire too short", file=sys.stderr)
                    break
                counter_bytes = wire[:8]
                ad = counter_bytes
                try:
                    plaintext = self.aead.decrypt_message(wire, additional_data=ad)
                except Exception as e:
                    print(f"Decryption/verification failed: {e}", file=sys.stderr)
                    break

                try:
                    text = plaintext.decode("utf-8")
                except Exception:
                    text = repr(plaintext)
                print(f"[peer] {text}")
        finally:
            self.stop_event.set()
# --- Server / Client runners ---
def run_server(listen_host: str, listen_port: int, use_chacha: bool, persist_path: str = None):
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((listen_host, listen_port))
    server_sock.listen(1)
    print(f"Server listening on {listen_host}:{listen_port}")
    client_sock, addr = server_sock.accept()
    print(f"Accepted connection from {addr}")
    server_private, server_public = generate_x25519_keypair()
    client_sock.sendall(server_public.public_bytes(encoding=serialization.Encoding.Raw,
                                                   format=serialization.PublicFormat.Raw))
    client_public_bytes = recv_exact(client_sock, 32)
    client_public = x25519.X25519PublicKey.from_public_bytes(client_public_bytes)
    shared_secret = server_private.exchange(client_public)
    symmetric_key = derive_symmetric_key(shared_secret)
    aead = AEADCipher(symmetric_key, use_chacha=use_chacha, persist_recv_counter_path=persist_path)
    peer = ChatPeer(client_sock, aead)
    peer.start_io_threads()
    try:
        while not peer.stop_event.is_set():
            try:
                user_input = input()
            except EOFError:
                break
            if user_input.strip().lower() == "exit":
                break
            peer.send_queue.put(user_input)
    except KeyboardInterrupt:
        pass
    finally:
        peer.send_queue.put(None)
        peer.stop()
        server_sock.close()
def run_client(server_host: str, server_port: int, use_chacha: bool, persist_path: str = None):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((server_host, server_port))
    print(f"Connected to server {server_host}:{server_port}")
    server_public_bytes = recv_exact(sock, 32)
    server_public = x25519.X25519PublicKey.from_public_bytes(server_public_bytes)
    client_private, client_public = generate_x25519_keypair()
    sock.sendall(client_public.public_bytes(encoding=serialization.Encoding.Raw,
                                            format=serialization.PublicFormat.Raw))
    shared_secret = client_private.exchange(server_public)
    symmetric_key = derive_symmetric_key(shared_secret)
    aead = AEADCipher(symmetric_key, use_chacha=use_chacha, persist_recv_counter_path=persist_path)
    peer = ChatPeer(sock, aead)
    peer.start_io_threads()
    try:
        while not peer.stop_event.is_set():
            try:
                user_input = input()
            except EOFError:
                break
            if user_input.strip().lower() == "exit":
                break
            peer.send_queue.put(user_input)
    except KeyboardInterrupt:
        pass
    finally:
        peer.send_queue.put(None)
        peer.stop()
        try:
            sock.close()
        except Exception:
            pass
# --- Interactive menu ---
def prompt_input(prompt: str, default: str = None) -> str:
    if default is None:
        return input(prompt)
    else:
        v = input(f"{prompt} [{default}]: ")
        return v.strip() or default
def interactive_menu():
    print("==== Secure Chat 启动菜单 ====")
    print("1) Run as Server")
    print("2) Run as Client")
    print("q) Quit")
    choice = input("请选择 (1/2/q): ").strip().lower()
    if choice == "q":
        print("退出")
        sys.exit(0)
    if choice == "1":
        mode = "server"
        host = prompt_input("监听地址 (默认 0.0.0.0)", "0.0.0.0")
    else:
        mode = "client"
        host = prompt_input("服务器地址 (默认 127.0.0.1)", "127.0.0.1")
    port_str = prompt_input("端口 (默认 12345)", "12345")
    try:
        port = int(port_str)
    except ValueError:
        port = 12345
    chacha_choice = input("Use ChaCha20-Poly1305 instead of AES-GCM? (y/N): ").strip().lower()
    use_chacha = chacha_choice == "y"
    persist_choice = input("Enable persistent receive counter? (saves recv counter to disk) (y/N): ").strip().lower()
    persist_path = None
    if persist_choice == "y":
        default_path = "recv_counter.json"
        persist_path = prompt_input("Path to persistence file", default_path)
    return mode, host, port, use_chacha, persist_path
def main():
    def handle_sigterm(signum, frame):
        print("Terminated, exiting...", file=sys.stderr)
        sys.exit(0)
    signal.signal(signal.SIGINT, handle_sigterm)
    signal.signal(signal.SIGTERM, handle_sigterm)
    mode, host, port, use_chacha, persist_path = interactive_menu()
    if mode == "server":
        run_server(host, port, use_chacha, persist_path)
    else:
        run_client(host, port, use_chacha, persist_path)
if __name__ == "__main__":
    main()
