#!/usr/bin/env python3
"""
x25519_reconnect_file_noclass.py

Single-file interactive TCP chat (client/server) with:
- X25519 + HKDF -> AES-256-GCM
- Message sequencing (8-byte seq as AAD)
- Key rotation every ROTATE_INTERVAL messages
- Client auto-reconnect; server accepts connections
- No classes; session state stored in dicts
- File transfer: send via "/sendfile <path>" from stdin
- Send/receive in separate threads

Requires: cryptography
pip install cryptography
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
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
KEY_LEN = 32
NONCE_LEN = 12
MSG_LEN_PREFIX = 4
SEQ_LEN = 8
ROTATE_INTERVAL = 1000
RECONNECT_DELAY = 2.0
# File transfer
FILE_CHUNK_SIZE = 16 * 1024  # 16KB per chunk
# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------
def derive_key(shared_secret: bytes, salt: bytes, info: bytes = b'handshake', length: int = KEY_LEN) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info)
    return hkdf.derive(shared_secret)
def pack_message_blob(blob: bytes) -> bytes:
    return struct.pack('!I', len(blob)) + blob
def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed while reading")
        buf.extend(chunk)
    return bytes(buf)
def recv_blob(sock: socket.socket) -> bytes:
    hdr = recv_exact(sock, MSG_LEN_PREFIX)
    (length,) = struct.unpack('!I', hdr)
    return recv_exact(sock, length)
def int_to_seq(n: int) -> bytes:
    return struct.pack('!Q', n)
def seq_to_int(b: bytes) -> int:
    return struct.unpack('!Q', b)[0]
def encrypt_with_seq(aesgcm: AESGCM, seq: int, plaintext: bytes) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    aad = int_to_seq(seq)
    ct = aesgcm.encrypt(nonce, plaintext, aad)
    return nonce + ct
def decrypt_with_seq(aesgcm: AESGCM, seq: int, blob: bytes) -> bytes:
    if len(blob) < NONCE_LEN + 16:
        raise ValueError("ciphertext too short")
    nonce = blob[:NONCE_LEN]
    ct = blob[NONCE_LEN:]
    aad = int_to_seq(seq)
    return aesgcm.decrypt(nonce, ct, aad)
# ---------------------------------------------------------------------------
# Handshake (X25519 pubkey + salt exchange) -> returns (key_bytes, AESGCM)
# Protocol: send pub(32) || salt_len(1) || salt; then receive peer same.
# ---------------------------------------------------------------------------
def do_handshake(sock: socket.socket, is_server: bool) -> Tuple[bytes, AESGCM]:
    priv = x25519.X25519PrivateKey.generate()
    pub = priv.public_key().public_bytes()
    salt = os.urandom(16)
    out = pub + struct.pack('!B', len(salt)) + salt
    sock.sendall(out)
    peer_pub = recv_exact(sock, 32)
    salt_len_b = recv_exact(sock, 1)
    salt_len = struct.unpack('!B', salt_len_b)[0]
    peer_salt = recv_exact(sock, salt_len)
    shared = priv.exchange(x25519.X25519PublicKey.from_public_bytes(peer_pub))
    info = b"X25519-AESGCM-rotate" + (b"server" if is_server else b"client")
    combined_salt = bytes(a ^ b for a, b in zip(salt, peer_salt))
    key = derive_key(shared, combined_salt, info=info)
    return key, AESGCM(key)
# ---------------------------------------------------------------------------
# Helper for file-transfer meta messages
# ---------------------------------------------------------------------------
def make_file_start_meta(path: str, filesize: int, dest_name: Optional[str] = None) -> bytes:
    meta = {
        "type": "FILE_START",
        "name": dest_name or pathlib.Path(path).name,
        "size": filesize,
    }
    return json.dumps(meta).encode('utf-8')
def make_file_end_meta() -> bytes:
    return json.dumps({"type": "FILE_END"}).encode('utf-8')
def is_meta_message(b: bytes) -> bool:
    try:
        obj = json.loads(b.decode('utf-8'))
        return isinstance(obj, dict) and 'type' in obj
    except Exception:
        return False
def parse_meta(b: bytes) -> dict:
    return json.loads(b.decode('utf-8'))
# ---------------------------------------------------------------------------
# Session state (no class)
# ---------------------------------------------------------------------------
def make_session_state(conn: socket.socket, addr, is_server: bool):
    ev = threading.Event()
    ev.set()
    return {
        'conn': conn,
        'addr': addr,
        'is_server': is_server,
        'lock': threading.Lock(),
        'key': None,
        'aesgcm': None,
        'send_seq': 0,
        'recv_seq': 0,
        'sent_count_since_rotate': 0,
        'recv_count_since_rotate': 0,
        'alive': ev,
        't_recv': None,
        't_send': None,
        'file_recv': None,  # dict: name,size,received,handle
    }
# ---------------------------------------------------------------------------
# Handshake wrapper to initialize state
# ---------------------------------------------------------------------------
def session_handshake(state: dict):
    with state['lock']:
        key, aesgcm = do_handshake(state['conn'], state['is_server'])
        state['key'] = key
        state['aesgcm'] = aesgcm
        state['send_seq'] = 0
        state['recv_seq'] = 0
        state['sent_count_since_rotate'] = 0
        state['recv_count_since_rotate'] = 0
    print(f"[+] Handshake complete with {state['addr']}")
# ---------------------------------------------------------------------------
# Rotate keys (performs a new handshake)
# ---------------------------------------------------------------------------
def rotate_keys(state: dict):
    try:
        print("[*] Performing key rotation handshake...")
        session_handshake(state)
        print("[*] Key rotation complete.")
    except Exception as e:
        print("[!] Key rotation failed:", e)
        state['alive'].clear()
# ---------------------------------------------------------------------------
# Close session
# ---------------------------------------------------------------------------
def close_session(state: dict):
    try:
        state['alive'].clear()
        try:
            state['conn'].shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        state['conn'].close()
    except Exception:
        pass
    # cleanup file handle if any
    fr = state.get('file_recv')
    if fr and 'handle' in fr:
        try:
            fr['handle'].close()
        except Exception:
            pass
        state['file_recv'] = None
# ---------------------------------------------------------------------------
# Receive loop (thread target)
# ---------------------------------------------------------------------------
def recv_loop(state: dict):
    conn = state['conn']
    try:
        while state['alive'].is_set():
            blob = recv_blob(conn)
            if len(blob) < SEQ_LEN + NONCE_LEN + 16:
                print("[!] Received too-short message blob")
                continue
            seq_b = blob[:SEQ_LEN]
            seq = seq_to_int(seq_b)
            cipher_blob = blob[SEQ_LEN:]
            if seq != state['recv_seq']:
                print(f"[!] Sequence mismatch: expected {state['recv_seq']}, got {seq}. Dropping.")
                continue
            try:
                pt = decrypt_with_seq(state['aesgcm'], seq, cipher_blob)
            except Exception as e:
                print("[!] Decrypt failed:", e)
                continue

            # File-transfer handling
            if is_meta_message(pt):
                meta = parse_meta(pt)
                mtype = meta.get('type')
                if mtype == 'FILE_START':
                    fname = meta.get('name')
                    fsize = int(meta.get('size', 0))
                    out_name = fname
                    i = 1
                    while os.path.exists(out_name):
                        out_name = f"{fname}.recv{ i }"
                        i += 1
                    try:
                        fh = open(out_name, 'wb')
                    except Exception as e:
                        print("[!] Failed to open file for writing:", e)
                        state['file_recv'] = None
                    else:
                        state['file_recv'] = {'name': out_name, 'size': fsize, 'received': 0, 'handle': fh}
                        print(f"[+] Receiving file {out_name} ({fsize} bytes)")
                elif mtype == 'FILE_END':
                    fr = state.get('file_recv')
                    if fr:
                        try:
                            fr['handle'].close()
                        except Exception:
                            pass
                        print(f"[+] File received: {fr['name']} ({fr['received']}/{fr['size']})")
                        state['file_recv'] = None
                    else:
                        print("[!] FILE_END received but no active file transfer")
                else:
                    print("[!] Unknown meta message:", meta)
            else:
                fr = state.get('file_recv')
                if fr:
                    try:
                        fr['handle'].write(pt)
                        fr['received'] += len(pt)
                        # optional: show progress occasionally
                        if fr['size'] > 0:
                            pct = (fr['received'] * 100) // fr['size']
                            print(f"\r[Receiving {fr['name']}] {fr['received']}/{fr['size']} bytes ({pct}%)", end='', flush=True)
                            if fr['received'] >= fr['size']:
                                print("\n[+] Awaiting FILE_END to finalize file")
                    except Exception as e:
                        print("[!] Error writing file chunk:", e)
                else:
                    try:
                        text = pt.decode('utf-8')
                    except Exception:
                        text = repr(pt)
                    print(f"\n[Peer {state['addr']}] {text}")

            state['recv_seq'] += 1
            state['recv_count_since_rotate'] += 1
            if state['recv_count_since_rotate'] >= ROTATE_INTERVAL:
                print("[*] Triggering key rotation due to recv count.")
                rotate_keys(state)
    except ConnectionError:
        print("[*] Connection closed by peer.")
        state['alive'].clear()
    except Exception as e:
        print("[!] Receive loop exception:", e)
        state['alive'].clear()
    finally:
        close_session(state)
# ---------------------------------------------------------------------------
# Send loop (thread target) - supports /sendfile <path>
# ---------------------------------------------------------------------------
def send_loop(state: dict):
    conn = state['conn']
    try:
        stdin = sys.stdin
        while state['alive'].is_set():
            line = stdin.readline()
            if not line:
                state['alive'].clear()
                break
            line = line.rstrip('\n')
            if line.startswith("/sendfile "):
                path = line[len("/sendfile "):].strip()
                if not os.path.isfile(path):
                    print("[!] File not found:", path)
                    continue
                filesize = os.path.getsize(path)
                # send FILE_START meta
                meta = make_file_start_meta(path, filesize)
                with state['lock']:
                    seq = state['send_seq']
                    blob = encrypt_with_seq(state['aesgcm'], seq, meta)
                    out = int_to_seq(seq) + blob
                    conn.sendall(pack_message_blob(out))
                    state['send_seq'] += 1
                    state['sent_count_since_rotate'] += 1
                # send file chunks
                try:
                    with open(path, 'rb') as f:
                        while True:
                            chunk = f.read(FILE_CHUNK_SIZE)
                            if not chunk:
                                break
                            with state['lock']:
                                seq = state['send_seq']
                                blob = encrypt_with_seq(state['aesgcm'], seq, chunk)
                                out = int_to_seq(seq) + blob
                                conn.sendall(pack_message_blob(out))
                                state['send_seq'] += 1
                                state['sent_count_since_rotate'] += 1
                            if state['sent_count_since_rotate'] >= ROTATE_INTERVAL:
                                print("[*] Triggering key rotation due to send count.")
                                rotate_keys(state)
                except Exception as e:
                    print("[!] Error reading/sending file:", e)
                    continue
                # send FILE_END meta
                meta_end = make_file_end_meta()
                with state['lock']:
                    seq = state['send_seq']
                    blob = encrypt_with_seq(state['aesgcm'], seq, meta_end)
                    out = int_to_seq(seq) + blob
                    conn.sendall(pack_message_blob(out))
                    state['send_seq'] += 1
                    state['sent_count_since_rotate'] += 1
                print(f"[+] Sent file {path} ({filesize} bytes)")
                continue
            # normal text message
            msg = line.encode('utf-8')
            with state['lock']:
                seq = state['send_seq']
                blob = encrypt_with_seq(state['aesgcm'], seq, msg)
                out = int_to_seq(seq) + blob
                conn.sendall(pack_message_blob(out))
                state['send_seq'] += 1
                state['sent_count_since_rotate'] += 1
            if state['sent_count_since_rotate'] >= ROTATE_INTERVAL:
                print("[*] Triggering key rotation due to send count.")
                rotate_keys(state)
    except ConnectionError:
        print("[*] Connection closed while sending.")
        state['alive'].clear()
    except Exception as e:
        print("[!] Send loop exception:", e)
        state['alive'].clear()
    finally:
        close_session(state)
# ---------------------------------------------------------------------------
# Start session: set alive and spawn threads
# ---------------------------------------------------------------------------
def start_session(state: dict):
    state['alive'].set()
    t_recv = threading.Thread(target=recv_loop, args=(state,), daemon=True)
    t_send = threading.Thread(target=send_loop, args=(state,), daemon=True)
    state['t_recv'] = t_recv
    state['t_send'] = t_send
    t_recv.start()
    t_send.start()
# ---------------------------------------------------------------------------
# Server interactive loop
# ---------------------------------------------------------------------------
def run_server_interactive(bind_host: str, bind_port: int):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((bind_host, bind_port))
    s.listen(5)
    print(f"[+] Server listening on {bind_host}:{bind_port}")
    print("Type /sendfile <path> to send a file")
    sessions = []
    try:
        while True:
            conn, addr = s.accept()
            print(f"[+] Accepted connection from {addr}")
            state = make_session_state(conn, addr, is_server=True)
            try:
                session_handshake(state)
            except Exception as e:
                print("[!] Handshake failed for", addr, e)
                conn.close()
                continue
            start_session(state)
            sessions.append(state)
            sessions = [ss for ss in sessions if ss['alive'].is_set()]
    except KeyboardInterrupt:
        print("Server shutting down.")
    finally:
        for ss in sessions:
            close_session(ss)
        s.close()
# ---------------------------------------------------------------------------
# Client interactive with auto-reconnect
# ---------------------------------------------------------------------------
def run_client_interactive(server_host: str, server_port: int):
    print("Type /sendfile <path> to send a file")
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            print(f"[*] Connecting to {server_host}:{server_port} ...")
            s.connect((server_host, server_port))
            print("[+] Connected.")
            state = make_session_state(s, (server_host, server_port), is_server=False)
            try:
                session_handshake(state)
            except Exception as e:
                print("[!] Handshake failed:", e)
                s.close()
                time.sleep(RECONNECT_DELAY)
                continue
            start_session(state)
            while state['alive'].is_set():
                time.sleep(0.5)
            print("[*] Session ended.")
        except Exception as e:
            print("[!] Connection error:", e)
        print(f"[*] Reconnecting in {RECONNECT_DELAY} seconds...")
        time.sleep(RECONNECT_DELAY)
# ---------------------------------------------------------------------------
# Prompt helpers and main
# ---------------------------------------------------------------------------
def prompt(prompt_text: str, default: Optional[str] = None) -> str:
    if default:
        return input(f"{prompt_text} [{default}]: ") or default
    return input(f"{prompt_text}: ")
def main():
    print("X25519 TCP chat (no-class) with sequencing, rotation, reconnect, and file transfer")
    role = ''
    while role.lower() not in ('s', 'c', 'server', 'client'):
        role = input("Run as (s)erver or (c)lient? ").strip().lower()
    if role.startswith('s'):
        host = prompt("Bind host", "0.0.0.0")
        port = int(prompt("Bind port", "5555"))
        run_server_interactive(host, port)
    else:
        host = prompt("Server host", "127.0.0.1")
        port = int(prompt("Server port", "5555"))
        run_client_interactive(host, port)
if __name__ == '__main__':
    main()
