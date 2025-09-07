#!/usr/bin/env python3
"""
dedup_encrypt_menu_pycryptodome.py

依赖:
    pip install pycryptodome

说明:
- 递归去重（按 SHA-256），保留第一个遇到的副本
- 递归加密/解密（AES-256-GCM via pycryptodome），覆盖原文件
- 无类、终端菜单交互
- 加密文件格式: salt(16) || nonce(12) || ciphertext || tag(16)
"""
import os
import sys
import hashlib
from pathlib import Path
from typing import Dict
import secrets
from getpass import getpass
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
# Constants
SALT_SIZE = 16
NONCE_SIZE = 12
TAG_SIZE = 16
KDF_ITERS = 200_000
KEY_LEN = 32
READ_CHUNK = 4 * 1024 * 1024
# ---------- Helpers ----------
def sha256_file(path: Path, chunk_size: int = READ_CHUNK) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            h.update(chunk)
    return h.hexdigest()
def derive_key(password: bytes, salt: bytes, iterations: int = KDF_ITERS, dklen: int = KEY_LEN) -> bytes:
    # PBKDF2 with HMAC-SHA256
    return PBKDF2(password, salt, dklen, count=iterations, hmac_hash_module=SHA256)
# ---------- Dedup ----------
def dedup_directory(root: Path, recursive: bool = True, dry_run: bool = False) -> None:
    hash_map: Dict[str, Path] = {}
    removed = 0
    processed = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for fname in filenames:
            p = Path(dirpath) / fname
            if not p.is_file():
                continue
            processed += 1
            try:
                h = sha256_file(p)
            except Exception as e:
                print(f"[skip] {p}: {e}")
                continue
            if h in hash_map:
                kept = hash_map[h]
                print(f"[dup] {p}  (same as {kept})")
                if not dry_run:
                    try:
                        p.unlink()
                        removed += 1
                    except Exception as e:
                        print(f"[error remove] {p}: {e}")
            else:
                hash_map[h] = p
        if not recursive:
            break
    print(f"Processed {processed} files. Removed {removed} duplicates (dry_run={dry_run}).")
# ---------- Encrypt / Decrypt (pycryptodome AES-GCM) ----------
def encrypt_file(path: Path, password: str) -> None:
    salt = secrets.token_bytes(SALT_SIZE)
    key = derive_key(password.encode('utf-8'), salt)
    nonce = secrets.token_bytes(NONCE_SIZE)
    data = path.read_bytes()
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=TAG_SIZE)
    ct, tag = cipher.encrypt_and_digest(data)
    out = salt + nonce + ct + tag
    path.write_bytes(out)
def decrypt_file(path: Path, password: str) -> bool:
    b = path.read_bytes()
    if len(b) < SALT_SIZE + NONCE_SIZE + TAG_SIZE:
        print(f"[too small] {path} -- not an encrypted file (or corrupted).")
        return False
    salt = b[:SALT_SIZE]
    nonce = b[SALT_SIZE:SALT_SIZE+NONCE_SIZE]
    ct_and_tag = b[SALT_SIZE+NONCE_SIZE:]
    if len(ct_and_tag) < TAG_SIZE:
        print(f"[invalid] {path} -- ciphertext too short.")
        return False
    ct = ct_and_tag[:-TAG_SIZE]
    tag = ct_and_tag[-TAG_SIZE:]
    key = derive_key(password.encode('utf-8'), salt)
    try:
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=TAG_SIZE)
        pt = cipher.decrypt_and_verify(ct, tag)
    except Exception as e:
        print(f"[decrypt fail] {path}: {e}")
        return False
    path.write_bytes(pt)
    return True
def process_directory_encrypt(root: Path, password: str, recursive: bool = True) -> None:
    total = 0
    failed = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for fname in filenames:
            p = Path(dirpath) / fname
            if not p.is_file():
                continue
            total += 1
            try:
                print(f"[enc] {p}")
                encrypt_file(p, password)
            except Exception as e:
                failed += 1
                print(f"[error enc] {p}: {e}")
        if not recursive:
            break
    print(f"Encrypted {total - failed}/{total} files, {failed} failed.")
def process_directory_decrypt(root: Path, password: str, recursive: bool = True) -> None:
    total = 0
    success = 0
    failed = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for fname in filenames:
            p = Path(dirpath) / fname
            if not p.is_file():
                continue
            total += 1
            print(f"[dec] {p}")
            ok = decrypt_file(p, password)
            if ok:
                success += 1
            else:
                failed += 1
        if not recursive:
            break
    print(f"Decrypted {success}/{total} files successfully, {failed} failed.")
# ---------- Menu ----------
def print_menu():
    print()
    print("====== 目录去重 & AES-256-GCM (pycryptodome) ======")
    print("1) 去重（递归） - 删除重复文件，保留第一个")
    print("2) 去重（递归，仅报告） - 不删除，只报告重复项")
    print("3) 加密（递归） - 使用密码对所有文件加密（覆盖）")
    print("4) 解密（递归） - 使用密码对所有文件解密（覆盖）")
    print("5) 退出")
    print("===============================================")

def ask_dir() -> Path:
    path_str = input("输入目标目录路径: ").strip()
    if not path_str:
        print("路径不能为空。")
        return None
    p = Path(path_str)
    if not p.exists() or not p.is_dir():
        print("目录不存在或不是目录。")
        return None
    return p

def main():
    while True:
        print_menu()
        choice = input("选择操作编号: ").strip()
        if choice == '5' or choice.lower() in ('q','quit','exit'):
            print("退出。")
            break
        if choice not in ('1','2','3','4'):
            print("无效选择。")
            continue

        root = ask_dir()
        if root is None:
            continue

        if choice == '1':
            confirm = input("确认递归删除目录中的重复文件？(y/N): ").strip().lower() == 'y'
            if not confirm:
                print("已取消。")
                continue
            dedup_directory(root, recursive=True, dry_run=False)

        elif choice == '2':
            dedup_directory(root, recursive=True, dry_run=True)

        elif choice == '3':
            pwd = getpass("输入加密密码: ")
            if not pwd:
                print("密码不能为空。")
                continue
            confirm = input("加密会覆盖原文件，建议先备份。确认继续？(y/N): ").strip().lower() == 'y'
            if not confirm:
                print("已取消。")
                continue
            process_directory_encrypt(root, pwd, recursive=True)

        elif choice == '4':
            pwd = getpass("输入解密密码: ")
            if not pwd:
                print("密码不能为空。")
                continue
            confirm = input("确认对目录下所有文件尝试解密？(y/N): ").strip().lower() == 'y'
            if not confirm:
                print("已取消。")
                continue
            process_directory_decrypt(root, pwd, recursive=True)
if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n中断，退出。")
