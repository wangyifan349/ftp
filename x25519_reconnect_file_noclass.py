#!/usr/bin/env python3
"""
Refactored X25519 TCP chat with sequencing, key rotation, reconnect, and file transfer.

Main changes:
- Clearer, consistent English names.
- Session represented as a dataclass.
- Helper functions and constants renamed for readability.
- Behavior (protocol, crypto, message format) unchanged.
"""
import socket
import threading
import os
import struct
import sys
import time
import json
import pathlib
from typing import Optional, Tuple
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
# ---------------------------------------------------------------------------
# Configuration (constants)
# ---------------------------------------------------------------------------
KEY_LENGTH = 32
NONCE_LENGTH = 12
LENGTH_PREFIX_BYTES = 4
SEQUENCE_BYTES = 8
ROTATION_INTERVAL = 1000
RECONNECT_DELAY_SECONDS = 2.0
FILE_CHUNK_SIZE = 16 * 1024  # 16KB
# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def hkdf_derive_key(shared_secret: bytes, salt: bytes, info: bytes = b'handshake', length: int = KEY_LENGTH) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info)
    return hkdf.derive(shared_secret)
def pack_with_length_prefix(payload: bytes) -> bytes:
    return struct.pack('!I', len(payload)) + payload
def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed while reading")
        buf.extend(chunk)
    return bytes(buf)
def recv_length_prefixed_blob(sock: socket.socket) -> bytes:
    hdr = recv_exact(sock, LENGTH_PREFIX_BYTES)
    (length,) = struct.unpack('!I', hdr)
    return recv_exact(sock, length)
def int_to_sequence_bytes(n: int) -> bytes:
    return struct.pack('!Q', n)
def sequence_bytes_to_int(b: bytes) -> int:
    return struct.unpack('!Q', b)[0]
def aesgcm_encrypt_with_sequence(aesgcm: AESGCM, sequence: int, plaintext: bytes) -> bytes:
    nonce = os.urandom(NONCE_LENGTH)
    aad = int_to_sequence_bytes(sequence)
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
    return nonce + ciphertext
def aesgcm_decrypt_with_sequence(aesgcm: AESGCM, sequence: int, blob: bytes) -> bytes:
    if len(blob) < NONCE_LENGTH + 16:
        raise ValueError("ciphertext too short")
    nonce = blob[:NONCE_LENGTH]
    ciphertext = blob[NONCE_LENGTH:]
    aad = int_to_sequence_bytes(sequence)
    return aesgcm.decrypt(nonce, ciphertext, aad)
# ---------------------------------------------------------------------------
# Handshake: X25519 pubkey + salt exchange
# Protocol (unchanged): send pub(32) || salt_len(1) || salt; then receive peer same.
# Returns: (key_bytes, AESGCM instance)
# ---------------------------------------------------------------------------
def perform_handshake(sock: socket.socket, is_server: bool) -> Tuple[bytes, AESGCM]:
    private = x25519.X25519PrivateKey.generate()
    public = private.public_key().public_bytes()
    salt_local = os.urandom(16)
    out = public + struct.pack('!B', len(salt_local)) + salt_local
    sock.sendall(out)
    peer_pub = recv_exact(sock, 32)
    salt_len_b = recv_exact(sock, 1)
    salt_len = struct.unpack('!B', salt_len_b)[0]
    peer_salt = recv_exact(sock, salt_len)
    shared = private.exchange(x25519.X25519PublicKey.from_public_bytes(peer_pub))
    info = b"X25519-AESGCM-rotate" + (b"server" if is_server else b"client")
    combined_salt = bytes(a ^ b for a, b in zip(salt_local, peer_salt))
    key = hkdf_derive_key(shared, combined_salt, info=info)
    return key, AESGCM(key)
# ---------------------------------------------------------------------------
# File-transfer metadata helpers
# ---------------------------------------------------------------------------
def make_file_start_metadata(file_path: str, file_size: int, dest_name: Optional[str] = None) -> bytes:
    metadata = {
        "type": "FILE_START",
        "name": dest_name or pathlib.Path(file_path).name,
        "size": file_size,
    }
    return json.dumps(metadata).encode('utf-8')
def make_file_end_metadata() -> bytes:
    return json.dumps({"type": "FILE_END"}).encode('utf-8')
def is_metadata_message(b: bytes) -> bool:
    try:
        obj = json.loads(b.decode('utf-8'))
        return isinstance(obj, dict) and 'type' in obj
    except Exception:
        return False
def parse_metadata(b: bytes) -> dict:
    return json.loads(b.decode('utf-8'))
# ---------------------------------------------------------------------------
# Session dataclass (replaces ad-hoc dict)
# ---------------------------------------------------------------------------
@dataclass
class Session:
    connection: socket.socket
    peer_addr: tuple
    is_server: bool
    lock: threading.Lock = field(default_factory=threading.Lock)
    key: Optional[bytes] = None
    aesgcm: Optional[AESGCM] = None
    send_sequence: int = 0
    recv_sequence: int = 0
    send_count_since_rotation: int = 0
    recv_count_since_rotation: int = 0
    alive_event: threading.Event = field(default_factory=threading.Event)
    thread_recv: Optional[threading.Thread] = None
    thread_send: Optional[threading.Thread] = None
    file_receive: Optional[dict] = None  # dict: name,size,received,handle
def create_session(connection: socket.socket, peer_addr, is_server: bool) -> Session:
    s = Session(connection=connection, peer_addr=peer_addr, is_server=is_server)
    s.alive_event.set()
    return s
# ---------------------------------------------------------------------------
# Handshake wrapper to initialize session keys/state
# ---------------------------------------------------------------------------
def initialize_session_handshake(session: Session):
    with session.lock:
        key, aesgcm = perform_handshake(session.connection, session.is_server)
        session.key = key
        session.aesgcm = aesgcm
        session.send_sequence = 0
        session.recv_sequence = 0
        session.send_count_since_rotation = 0
        session.recv_count_since_rotation = 0
    print(f"[+] Handshake complete with {session.peer_addr}")
# ---------------------------------------------------------------------------
# Key rotation (performs a new handshake)
# ---------------------------------------------------------------------------
def rotate_session_keys(session: Session):
    try:
        print("[*] Performing key rotation handshake...")
        initialize_session_handshake(session)
        print("[*] Key rotation complete.")
    except Exception as exc:
        print("[!] Key rotation failed:", exc)
        session.alive_event.clear()
# ---------------------------------------------------------------------------
# Close session (cleanup)
# ---------------------------------------------------------------------------
def close_session(session: Session):
    try:
        session.alive_event.clear()
        try:
            session.connection.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        session.connection.close()
    except Exception:
        pass
    fr = session.file_receive
    if fr and 'handle' in fr:
        try:
            fr['handle'].close()
        except Exception:
            pass
        session.file_receive = None
# ---------------------------------------------------------------------------
# Receive loop (thread target)
# ---------------------------------------------------------------------------
def receive_loop(session: Session):
    conn = session.connection
    try:
        while session.alive_event.is_set():
            blob = recv_length_prefixed_blob(conn)
            if len(blob) < SEQUENCE_BYTES + NONCE_LENGTH + 16:
                print("[!] Received too-short message blob")
                continue
            seq_bytes = blob[:SEQUENCE_BYTES]
            seq = sequence_bytes_to_int(seq_bytes)
            cipher_blob = blob[SEQUENCE_BYTES:]
            if seq != session.recv_sequence:
                print(f"[!] Sequence mismatch: expected {session.recv_sequence}, got {seq}. Dropping.")
                continue
            try:
                plaintext = aesgcm_decrypt_with_sequence(session.aesgcm, seq, cipher_blob)
            except Exception as exc:
                print("[!] Decrypt failed:", exc)
                continue
            # File-transfer handling
            if is_metadata_message(plaintext):
                meta = parse_metadata(plaintext)
                mtype = meta.get('type')
                if mtype == 'FILE_START':
                    fname = meta.get('name')
                    fsize = int(meta.get('size', 0))
                    out_name = fname
                    i = 1
                    while os.path.exists(out_name):
                        out_name = f"{fname}.recv{i}"
                        i += 1
                    try:
                        fh = open(out_name, 'wb')
                    except Exception as e:
                        print("[!] Failed to open file for writing:", e)
                        session.file_receive = None
                    else:
                        session.file_receive = {'name': out_name, 'size': fsize, 'received': 0, 'handle': fh}
                        print(f"[+] Receiving file {out_name} ({fsize} bytes)")
                elif mtype == 'FILE_END':
                    fr = session.file_receive
                    if fr:
                        try:
                            fr['handle'].close()
                        except Exception:
                            pass
                        print(f"[+] File received: {fr['name']} ({fr['received']}/{fr['size']})")
                        session.file_receive = None
                    else:
                        print("[!] FILE_END received but no active file transfer")
                else:
                    print("[!] Unknown metadata message:", meta)
            else:
                fr = session.file_receive
                if fr:
                    try:
                        fr['handle'].write(plaintext)
                        fr['received'] += len(plaintext)
                        if fr['size'] > 0:
                            pct = (fr['received'] * 100) // fr['size']
                            print(f"\r[Receiving {fr['name']}] {fr['received']}/{fr['size']} bytes ({pct}%)",
                                  end='', flush=True)
                            if fr['received'] >= fr['size']:
                                print("\n[+] Awaiting FILE_END to finalize file")
                    except Exception as e:
                        print("[!] Error writing file chunk:", e)
                else:
                    try:
                        text = plaintext.decode('utf-8')
                    except Exception:
                        text = repr(plaintext)
                    print(f"\n[Peer {session.peer_addr}] {text}")

            session.recv_sequence += 1
            session.recv_count_since_rotation += 1
            if session.recv_count_since_rotation >= ROTATION_INTERVAL:
                print("[*] Triggering key rotation due to recv count.")
                rotate_session_keys(session)
    except ConnectionError:
        print("[*] Connection closed by peer.")
        session.alive_event.clear()
    except Exception as exc:
        print("[!] Receive loop exception:", exc)
        session.alive_event.clear()
    finally:
        close_session(session)
# ---------------------------------------------------------------------------
# Send loop (thread target) - supports /sendfile <path>
# ---------------------------------------------------------------------------
def send_loop(session: Session):
    conn = session.connection
    try:
        stdin = sys.stdin
        while session.alive_event.is_set():
            line = stdin.readline()
            if not line:
                session.alive_event.clear()
                break
            line = line.rstrip('\n')
            if line.startswith("/sendfile "):
                file_path = line[len("/sendfile "):].strip()
                if not os.path.isfile(file_path):
                    print("[!] File not found:", file_path)
                    continue
                file_size = os.path.getsize(file_path)
                # Send FILE_START metadata
                meta = make_file_start_metadata(file_path, file_size)
                with session.lock:
                    seq = session.send_sequence
                    blob = aesgcm_encrypt_with_sequence(session.aesgcm, seq, meta)
                    out = int_to_sequence_bytes(seq) + blob
                    conn.sendall(pack_with_length_prefix(out))
                    session.send_sequence += 1
                    session.send_count_since_rotation += 1
                # Send file chunks
                try:
                    with open(file_path, 'rb') as fh:
                        while True:
                            chunk = fh.read(FILE_CHUNK_SIZE)
                            if not chunk:
                                break
                            with session.lock:
                                seq = session.send_sequence
                                blob = aesgcm_encrypt_with_sequence(session.aesgcm, seq, chunk)
                                out = int_to_sequence_bytes(seq) + blob
                                conn.sendall(pack_with_length_prefix(out))
                                session.send_sequence += 1
                                session.send_count_since_rotation += 1
                            if session.send_count_since_rotation >= ROTATION_INTERVAL:
                                print("[*] Triggering key rotation due to send count.")
                                rotate_session_keys(session)
                except Exception as exc:
                    print("[!] Error reading/sending file:", exc)
                    continue

                # Send FILE_END metadata
                meta_end = make_file_end_metadata()
                with session.lock:
                    seq = session.send_sequence
                    blob = aesgcm_encrypt_with_sequence(session.aesgcm, seq, meta_end)
                    out = int_to_sequence_bytes(seq) + blob
                    conn.sendall(pack_with_length_prefix(out))
                    session.send_sequence += 1
                    session.send_count_since_rotation += 1

                print(f"[+] Sent file {file_path} ({file_size} bytes)")
                continue

            # Normal text message
            msg_bytes = line.encode('utf-8')
            with session.lock:
                seq = session.send_sequence
                blob = aesgcm_encrypt_with_sequence(session.aesgcm, seq, msg_bytes)
                out = int_to_sequence_bytes(seq) + blob
                conn.sendall(pack_with_length_prefix(out))
                session.send_sequence += 1
                session.send_count_since_rotation += 1

            if session.send_count_since_rotation >= ROTATION_INTERVAL:
                print("[*] Triggering key rotation due to send count.")
                rotate_session_keys(session)
    except ConnectionError:
        print("[*] Connection closed while sending.")
        session.alive_event.clear()
    except Exception as exc:
        print("[!] Send loop exception:", exc)
        session.alive_event.clear()
    finally:
        close_session(session)
# ---------------------------------------------------------------------------
# Session start helper: spawn threads
# ---------------------------------------------------------------------------
def start_session_threads(session: Session):
    session.alive_event.set()
    t_recv = threading.Thread(target=receive_loop, args=(session,), daemon=True)
    t_send = threading.Thread(target=send_loop, args=(session,), daemon=True)
    session.thread_recv = t_recv
    session.thread_send = t_send
    t_recv.start()
    t_send.start()
# ---------------------------------------------------------------------------
# Server interactive loop
# ---------------------------------------------------------------------------
def run_server_interactive(bind_host: str, bind_port: int):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((bind_host, bind_port))
    listener.listen(5)
    print(f"[+] Server listening on {bind_host}:{bind_port}")
    print("Type /sendfile <path> to send a file")
    sessions = []
    try:
        while True:
            conn, addr = listener.accept()
            print(f"[+] Accepted connection from {addr}")
            session = create_session(conn, addr, is_server=True)
            try:
                initialize_session_handshake(session)
            except Exception as exc:
                print("[!] Handshake failed for", addr, exc)
                conn.close()
                continue
            start_session_threads(session)
            sessions.append(session)
            sessions = [s for s in sessions if s.alive_event.is_set()]
    except KeyboardInterrupt:
        print("Server shutting down.")
    finally:
        for s in sessions:
            close_session(s)
        listener.close()
# ---------------------------------------------------------------------------
# Client interactive with auto-reconnect
# ---------------------------------------------------------------------------
def run_client_interactive(server_host: str, server_port: int):
    print("Type /sendfile <path> to send a file")
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            print(f"[*] Connecting to {server_host}:{server_port} ...")
            sock.connect((server_host, server_port))
            print("[+] Connected.")
            session = create_session(sock, (server_host, server_port), is_server=False)
            try:
                initialize_session_handshake(session)
            except Exception as exc:
                print("[!] Handshake failed:", exc)
                sock.close()
                time.sleep(RECONNECT_DELAY_SECONDS)
                continue
            start_session_threads(session)
            while session.alive_event.is_set():
                time.sleep(0.5)
            print("[*] Session ended.")
        except Exception as exc:
            print("[!] Connection error:", exc)
        print(f"[*] Reconnecting in {RECONNECT_DELAY_SECONDS} seconds...")
        time.sleep(RECONNECT_DELAY_SECONDS)
# ---------------------------------------------------------------------------
# Prompt helpers and main
# ---------------------------------------------------------------------------
def prompt_input(prompt_text: str, default: Optional[str] = None) -> str:
    if default:
        return input(f"{prompt_text} [{default}]: ") or default
    return input(f"{prompt_text}: ")
def main():
    print("X25519 TCP chat (refactored) with sequencing, rotation, reconnect, and file transfer")
    role = ''
    while role.lower() not in ('s', 'c', 'server', 'client'):
        role = input("Run as (s)erver or (c)lient? ").strip().lower()
    if role.startswith('s'):
        host = prompt_input("Bind host", "0.0.0.0")
        port = int(prompt_input("Bind port", "5555"))
        run_server_interactive(host, port)
    else:
        host = prompt_input("Server host", "127.0.0.1")
        port = int(prompt_input("Server port", "5555"))
        run_client_interactive(host, port)
if __name__ == '__main__':
    main()
