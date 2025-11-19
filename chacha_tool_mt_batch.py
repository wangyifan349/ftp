#!/usr/bin/env python3
"""
chacha_tool_mt_batch.py

ChaCha20-Poly1305 并行批量加密工具（递归目录）。
- 递归遍历输入目录（os.walk），对每个文件并行加密/解密。
- 每个文件内部按块并行处理（ThreadPoolExecutor）。
- 文件级并行也使用线程池，限制并发文件数以控制资源。
- JSON 中二进制字段使用 Base58 编码。
- 不使用 AAD。
"""
import os
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional
from functools import partial
from Crypto.Cipher import ChaCha20_Poly1305
from Crypto.Protocol.KDF import PBKDF2, HKDF
from Crypto.Hash import SHA256
from Crypto.Random import get_random_bytes
import base58
# ---------------- 配置 ----------------
KEY_LEN = 32
NONCE_LEN = 12
SALT_LEN = 16
PBKDF2_ITERS = 200_000
VERSION = 2
DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MiB
CPU_COUNT = os.cpu_count() or 4
MAX_WORKERS_FILE = max(2, CPU_COUNT)          # 并发处理文件数
MAX_WORKERS_CHUNK = max(2, CPU_COUNT * 2)     # 每文件内部并行线程数
# ---------------- 辅助 ----------------
def derive_key_pbkdf2(password: str, salt: bytes, iterations: int = PBKDF2_ITERS, dklen: int = KEY_LEN) -> bytes:
    return PBKDF2(password.encode('utf-8'), salt, dklen, count=iterations, hmac_hash_module=SHA256)
def derive_key_hkdf(ikm: bytes, salt: Optional[bytes] = None, info: bytes = b'ChaCha20-Poly1305-key', dklen: int = KEY_LEN) -> bytes:
    return HKDF(master=ikm, key_len=dklen, salt=salt, hashmod=SHA256, context=info)
def b58_encode(b: bytes) -> str:
    return base58.b58encode(b).decode('ascii')
def b58_decode(s: str) -> bytes:
    return base58.b58decode(s.encode('ascii'))
# ---------------- 单文件：按块分割 ----------------
def split_file(path: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[Tuple[int, bytes]]:
    parts = []
    with open(path, 'rb') as f:
        idx = 0
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            parts.append((idx, data))
            idx += 1
    return parts
# ---------------- 加密/解密单块 ----------------
def encrypt_chunk(idx: int, data: bytes, key: bytes) -> dict:
    nonce = get_random_bytes(NONCE_LEN)
    cipher = ChaCha20_Poly1305.new(key=key, nonce=nonce)
    ct, tag = cipher.encrypt_and_digest(data)
    return {"i": idx, "nonce": b58_encode(nonce), "ct": b58_encode(ct), "tag": b58_encode(tag), "len": len(data)}
def decrypt_chunk(entry: dict, key: bytes) -> Tuple[int, bytes]:
    nonce = b58_decode(entry["nonce"])
    ct = b58_decode(entry["ct"])
    tag = b58_decode(entry["tag"])
    cipher = ChaCha20_Poly1305.new(key=key, nonce=nonce)
    pt = cipher.decrypt_and_verify(ct, tag)
    return entry["i"], pt
# ---------------- 单文件处理（并行块） ----------------
def encrypt_file_internal(in_path: str, out_path: str, password: str, use_hkdf: bool, chunk_size: int, max_workers_chunk: int) -> None:
    salt = get_random_bytes(SALT_LEN)
    key = derive_key_hkdf(password.encode('utf-8'), salt=salt) if use_hkdf else derive_key_pbkdf2(password, salt)
    parts = split_file(in_path, chunk_size=chunk_size)
    results = [None] * len(parts)
    with ThreadPoolExecutor(max_workers=max_workers_chunk) as ex:
        futures = {ex.submit(encrypt_chunk, idx, data, key): idx for idx, data in parts}
        for fut in as_completed(futures):
            res = fut.result()
            results[res["i"]] = res
    blob = {"v": VERSION, "kdf": "hkdf" if use_hkdf else "pbkdf2", "salt": b58_encode(salt), "chunk_size": chunk_size, "chunks": results, "orig_name": os.path.basename(in_path), "total_chunks": len(results)}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(blob, f, separators=(',', ':'))
def decrypt_file_internal(in_path: str, out_path: str, password: str, max_workers_chunk: int) -> None:
    with open(in_path, 'r', encoding='utf-8') as f:
        blob = json.load(f)
    salt = b58_decode(blob["salt"])
    key = derive_key_hkdf(password.encode('utf-8'), salt=salt) if blob.get("kdf") == "hkdf" else derive_key_pbkdf2(password, salt)
    chunks_meta = blob["chunks"]
    results = [None] * len(chunks_meta)
    with ThreadPoolExecutor(max_workers=max_workers_chunk) as ex:
        futures = {ex.submit(decrypt_chunk, entry, key): entry["i"] for entry in chunks_meta}
        for fut in as_completed(futures):
            idx, pt = fut.result()
            results[idx] = pt
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'wb') as out_f:
        for piece in results:
            out_f.write(piece)
# ---------------- 目录递归处理（文件级并行） ----------------
def process_directory_encrypt(src_dir: str, dst_dir: str, password: str, use_hkdf: bool = False, chunk_size: int = DEFAULT_CHUNK_SIZE, max_workers_file: int = MAX_WORKERS_FILE, max_workers_chunk: int = MAX_WORKERS_CHUNK):
    tasks = []
    for root, dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(root, src_dir)
        for name in files:
            src_path = os.path.join(root, name)
            rel_path = os.path.normpath(os.path.join(rel_root, name)) if rel_root != '.' else name
            dst_path = os.path.join(dst_dir, rel_path + '.enc')
            tasks.append((src_path, dst_path))
    total = len(tasks)
    if total == 0:
        print("没有找到要加密的文件。")
        return
    print(f"找到 {total} 个文件，开始并行加密（并行文件数 {max_workers_file}）...")
    with ThreadPoolExecutor(max_workers=max_workers_file) as ex:
        futures = {ex.submit(encrypt_file_internal, src, dst, password, use_hkdf, chunk_size, max_workers_chunk): (src, dst) for src, dst in tasks}
        completed = 0
        for fut in as_completed(futures):
            src, dst = futures[fut]
            try:
                fut.result()
                completed += 1
                print(f"[{completed}/{total}] 加密完成: {src} -> {dst}")
            except Exception as e:
                print(f"[ERROR] 处理文件 {src} 失败: {e}")
def process_directory_decrypt(src_dir: str, dst_dir: str, password: str, max_workers_file: int = MAX_WORKERS_FILE, max_workers_chunk: int = MAX_WORKERS_CHUNK):
    tasks = []
    for root, dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(root, src_dir)
        for name in files:
            if not name.endswith('.enc'):
                continue
            src_path = os.path.join(root, name)
            rel_name = name[:-4]  # remove .enc
            rel_path = os.path.normpath(os.path.join(rel_root, rel_name)) if rel_root != '.' else rel_name
            dst_path = os.path.join(dst_dir, rel_path)
            tasks.append((src_path, dst_path))
    total = len(tasks)
    if total == 0:
        print("没有找到要解密的 .enc 文件。")
        return
    print(f"找到 {total} 个 .enc 文件，开始并行解密（并行文件数 {max_workers_file}）...")
    with ThreadPoolExecutor(max_workers=max_workers_file) as ex:
        futures = {ex.submit(decrypt_file_internal, src, dst, password, max_workers_chunk): (src, dst) for src, dst in tasks}
        completed = 0
        for fut in as_completed(futures):
            src, dst = futures[fut]
            try:
                fut.result()
                completed += 1
                print(f"[{completed}/{total}] 解密完成: {src} -> {dst}")
            except Exception as e:
                print(f"[ERROR] 处理文件 {src} 失败: {e}")
# ---------------- 交互式菜单 / CLI ----------------
def interactive_menu():
    print("批量 ChaCha20-Poly1305 工具（递归目录）")
    print("1) 加密目录")
    print("2) 解密目录")
    print("3) 退出")
    choice = input("选择 (1-3): ").strip()
    if choice == '1':
        src = input("输入要加密的源目录: ").strip()
        dst = input("输入输出目标目录: ").strip()
        password = input("输入密码: ").strip()
        use_hkdf = input("使用 HKDF? (y/N): ").strip().lower() == 'y'
        chunk_size = input(f"分块大小（字节，回车使用默认 {DEFAULT_CHUNK_SIZE}）: ").strip()
        chunk_size = int(chunk_size) if chunk_size else DEFAULT_CHUNK_SIZE
        files_threads = input(f"并发处理文件数（回车使用 {MAX_WORKERS_FILE}）: ").strip()
        files_threads = int(files_threads) if files_threads else MAX_WORKERS_FILE
        chunk_threads = input(f"每文件内部并行线程数（回车使用 {MAX_WORKERS_CHUNK}）: ").strip()
        chunk_threads = int(chunk_threads) if chunk_threads else MAX_WORKERS_CHUNK
        process_directory_encrypt(src, dst, password, use_hkdf, chunk_size, files_threads, chunk_threads)
    elif choice == '2':
        src = input("输入包含 .enc 文件的源目录: ").strip()
        dst = input("输入解密输出目标目录: ").strip()
        password = input("输入密码: ").strip()
        files_threads = input(f"并发处理文件数（回车使用 {MAX_WORKERS_FILE}）: ").strip()
        files_threads = int(files_threads) if files_threads else MAX_WORKERS_FILE
        chunk_threads = input(f"每文件内部并行线程数（回车使用 {MAX_WORKERS_CHUNK}）: ").strip()
        chunk_threads = int(chunk_threads) if chunk_threads else MAX_WORKERS_CHUNK
        process_directory_decrypt(src, dst, password, files_threads, chunk_threads)
    elif choice == '3':
        print("退出")
        sys.exit(0)
    else:
        print("无效选择")
def main():
    if len(sys.argv) == 1:
        while True:
            interactive_menu()
            input("按回车返回主菜单...")
    else:
        cmd = sys.argv[1].lower()
        if cmd == 'encdir' and len(sys.argv) >= 5:
            _, _, src, dst, password = sys.argv[:5]
            process_directory_encrypt(src, dst, password)
        elif cmd == 'decdir' and len(sys.argv) >= 5:
            _, _, src, dst, password = sys.argv[:5]
            process_directory_decrypt(src, dst, password)
        else:
            print("用法:")
            print("  不带参数运行进入交互式菜单")
            print("  encdir <src_dir> <dst_dir> <password>")
            print("  decdir <src_dir> <dst_dir> <password>")
if __name__ == '__main__':
    main()
