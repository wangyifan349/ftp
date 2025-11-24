#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interactive ChaCha20 batch encrypt/decrypt (PyCryptodome)
- No nested expressions, no list comprehensions
- Clear English variable names
- Atomic replace of files using temp files
"""

import os
import sys
import pathlib
import tempfile
from Crypto.Cipher import ChaCha20
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA256
from Crypto.Random import get_random_bytes

MAGIC = b"CH20FILE"
VERSION = b"\x01"
DEFAULT_PBKDF2_ITERS = 100000
SALT_LENGTH = 16
NONCE_LENGTH = 12
KEY_LENGTH = 32

def derive_key_from_password(password, salt, iterations):
    return PBKDF2(password.encode("utf-8"), salt, dkLen=KEY_LENGTH, count=iterations, hmac_hash_module=SHA256)

def build_file_header(salt, nonce):
    salt_length_byte = bytes([len(salt)])
    nonce_length_byte = bytes([len(nonce)])
    header = MAGIC + VERSION + salt_length_byte + salt + nonce_length_byte + nonce
    return header

def parse_file_header(data_bytes):
    expected_prefix = MAGIC + VERSION
    if not data_bytes.startswith(expected_prefix):
        raise ValueError("Invalid file format or version")
    index = len(expected_prefix)
    salt_length = data_bytes[index]
    index = index + 1
    salt = data_bytes[index:index + salt_length]
    index = index + salt_length
    nonce_length = data_bytes[index]
    index = index + 1
    nonce = data_bytes[index:index + nonce_length]
    index = index + nonce_length
    header_length = index
    return salt, nonce, header_length

def atomic_write_replace_file(file_path, data_bytes):
    directory_path = str(file_path.parent)
    fd, temp_path = tempfile.mkstemp(dir=directory_path)
    try:
        fileobj = os.fdopen(fd, "wb")
        try:
            fileobj.write(data_bytes)
            fileobj.flush()
            os.fsync(fileobj.fileno())
        finally:
            fileobj.close()
        os.replace(temp_path, str(file_path))
    except Exception:
        try:
            os.remove(temp_path)
        except Exception:
            pass
        raise

def encrypt_single_file(file_path, password, iterations):
    fileobj = open(file_path, "rb")
    try:
        plaintext = fileobj.read()
    finally:
        fileobj.close()

    salt = get_random_bytes(SALT_LENGTH)
    key = derive_key_from_password(password, salt, iterations)
    nonce = get_random_bytes(NONCE_LENGTH)
    cipher = ChaCha20.new(key=key, nonce=nonce)
    ciphertext = cipher.encrypt(plaintext)
    header = build_file_header(salt, nonce)
    output_bytes = header + ciphertext
    atomic_write_replace_file(file_path, output_bytes)

def decrypt_single_file(file_path, password, iterations):
    fileobj = open(file_path, "rb")
    try:
        file_bytes = fileobj.read()
    finally:
        fileobj.close()

    salt, nonce, header_length = parse_file_header(file_bytes)
    key = derive_key_from_password(password, salt, iterations)
    ciphertext = file_bytes[header_length:]
    cipher = ChaCha20.new(key=key, nonce=nonce)
    plaintext = cipher.decrypt(ciphertext)
    atomic_write_replace_file(file_path, plaintext)

def list_files_in_directory(directory_path, recursive_flag):
    collected_files = []
    if recursive_flag:
        for path_object in directory_path.rglob("*"):
            if path_object.is_file():
                collected_files.append(path_object)
    else:
        for path_object in directory_path.iterdir():
            if path_object.is_file():
                collected_files.append(path_object)
    return collected_files

def prompt_yes_no(question_text):
    while True:
        answer = input(question_text + " [y/n]: ").strip().lower()
        if answer == "y" or answer == "yes":
            return True
        if answer == "n" or answer == "no":
            return False

def main():
    print("ChaCha20 batch encrypt/decrypt (interactive)")
    directory_input = input("Enter directory path to process: ").strip()
    if directory_input == "":
        print("No directory entered. Exiting.", file=sys.stderr)
        sys.exit(1)

    directory_path = pathlib.Path(directory_input)
    if not directory_path.exists() or not directory_path.is_dir():
        print("Directory does not exist or is not a directory. Exiting.", file=sys.stderr)
        sys.exit(1)

    recursive_flag = prompt_yes_no("Process subdirectories recursively?")

    mode_choice = None
    while mode_choice != "enc" and mode_choice != "dec":
        mode_input = input("Choose operation (enc=encrypt, dec=decrypt): ").strip().lower()
        if mode_input == "enc" or mode_input == "dec":
            mode_choice = mode_input

    password_input = input("Enter password: ")
    if password_input == "":
        print("Password cannot be empty. Exiting.", file=sys.stderr)
        sys.exit(1)

    iterations_input = input("PBKDF2 iterations (press Enter for default 100000): ").strip()
    if iterations_input == "":
        iterations_value = DEFAULT_PBKDF2_ITERS
    else:
        try:
            iterations_value = int(iterations_input)
            if iterations_value <= 0:
                raise ValueError("Iterations must be positive")
        except Exception:
            print("Invalid iteration count, using default.", file=sys.stderr)
            iterations_value = DEFAULT_PBKDF2_ITERS

    files_to_process = list_files_in_directory(directory_path, recursive_flag)
    if len(files_to_process) == 0:
        print("No files to process in directory.")
        return

    print("Starting processing. File count: " + str(len(files_to_process)))
    index_counter = 0
    while index_counter < len(files_to_process):
        current_file = files_to_process[index_counter]
        try:
            if mode_choice == "enc":
                encrypt_single_file(current_file, password_input, iterations_value)
                print("Encrypted: " + str(current_file))
            else:
                decrypt_single_file(current_file, password_input, iterations_value)
                print("Decrypted: " + str(current_file))
        except Exception as exception_object:
            print("Error processing " + str(current_file) + ": " + str(exception_object), file=sys.stderr)
        index_counter = index_counter + 1

if __name__ == "__main__":
    main()
