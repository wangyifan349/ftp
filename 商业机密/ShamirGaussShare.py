#!/usr/bin/env python3
"""ShamirGaussShare 是一个纯 Python 实现的 Shamir 秘密分享工具。它在有限域 GF(p) 上生成 n 个份额（shares），任意 k 个份额可通过高斯消元重建出原始秘密（多项式常数项）。"""
from typing import List, Tuple
import secrets
# ---- number theory ----
def is_probable_prime(n: int) -> bool:
    if n < 2:
        return False
    small_primes = [2,3,5,7,11,13,17,19,23,29]
    for p in small_primes:
        if n % p == 0:
            return n == p
    d = n - 1
    s = 0
    while d % 2 == 0:
        d //= 2
        s += 1
    def check(a: int) -> bool:
        x = pow(a, d, n)
        if x == 1 or x == n-1:
            return True
        for _ in range(s-1):
            x = (x * x) % n
            if x == n-1:
                return True
        return False
    bases = [2,325,9375,28178,450775,9780504,1795265022]
    for a in bases:
        if a % n == 0:
            continue
        if not check(a):
            return False
    return True
def find_next_prime(start_at: int) -> int:
    if start_at <= 2:
        return 2
    candidate = start_at if start_at % 2 == 1 else start_at + 1
    while not is_probable_prime(candidate):
        candidate += 2
    return candidate
def extended_gcd(a: int, b: int) -> Tuple[int,int,int]:
    if b == 0:
        return (a, 1, 0)
    g, x1, y1 = extended_gcd(b, a % b)
    return (g, y1, x1 - (a // b) * y1)
def modular_inverse(value: int, modulus: int) -> int:
    value = value % modulus
    g, inv, _ = extended_gcd(value, modulus)
    if g != 1:
        raise ValueError("No modular inverse")
    return inv % modulus
# ---- polynomial ----
def evaluate_polynomial(coefficients: List[int], x_value: int, prime_modulus: int) -> int:
    result = 0
    for coeff in reversed(coefficients):
        result = (result * x_value + coeff) % prime_modulus
    return result
def generate_random_coefficients(k: int, secret_integer: int, prime_modulus: int) -> List[int]:
    coeffs = [secret_integer % prime_modulus]
    for _ in range(k-1):
        coeffs.append(secrets.randbelow(prime_modulus))
    return coeffs
# ---- gaussian elimination mod p ----
def gaussian_elimination_modular(matrix_A: List[List[int]], vector_b: List[int], prime_modulus: int) -> List[int]:
    n = len(matrix_A)
    if any(len(row) != n for row in matrix_A):
        raise ValueError("Matrix must be square")
    if len(vector_b) != n:
        raise ValueError("Dimension mismatch")
    mat = [row[:] for row in matrix_A]
    rhs = vector_b[:]
    pivot_row = 0
    for pivot_col in range(n):
        sel = None
        for r in range(pivot_row, n):
            if mat[r][pivot_col] % prime_modulus != 0:
                sel = r
                break
        if sel is None:
            continue
        if sel != pivot_row:
            mat[pivot_row], mat[sel] = mat[sel], mat[pivot_row]
            rhs[pivot_row], rhs[sel] = rhs[sel], rhs[pivot_row]
        pivot_val = mat[pivot_row][pivot_col] % prime_modulus
        inv_pivot = modular_inverse(pivot_val, prime_modulus)
        for c in range(pivot_col, n):
            mat[pivot_row][c] = (mat[pivot_row][c] * inv_pivot) % prime_modulus
        rhs[pivot_row] = (rhs[pivot_row] * inv_pivot) % prime_modulus
        for r in range(n):
            if r == pivot_row:
                continue
            factor = mat[r][pivot_col] % prime_modulus
            if factor == 0:
                continue
            for c in range(pivot_col, n):
                mat[r][c] = (mat[r][c] - factor * mat[pivot_row][c]) % prime_modulus
            rhs[r] = (rhs[r] - factor * rhs[pivot_row]) % prime_modulus
        pivot_row += 1
        if pivot_row == n:
            break
    for i in range(n):
        if mat[i][i] % prime_modulus == 0:
            raise ValueError("Singular matrix modulo p")
    return [rhs[i] % prime_modulus for i in range(n)]

# ---- SSS API ----
def create_shares(secret_integer: int, total_shares: int, threshold: int, prime_modulus: int = None) -> Tuple[int, List[Tuple[int,int]]]:
    if not (1 <= threshold <= total_shares):
        raise ValueError("Require 1 <= threshold <= total_shares")
    if secret_integer < 0:
        raise ValueError("Secret must be non-negative")
    if prime_modulus is None:
        bit_length = max(secret_integer.bit_length() + 1, (total_shares.bit_length() + 1))
        start_candidate = 1 << bit_length
        start_candidate = max(start_candidate, secret_integer + 1)
        prime_modulus = find_next_prime(start_candidate)
    else:
        if not is_probable_prime(prime_modulus):
            raise ValueError("Provided prime_modulus not prime")
        if secret_integer >= prime_modulus:
            raise ValueError("Secret must be less than prime_modulus")
    coeffs = generate_random_coefficients(threshold, secret_integer, prime_modulus)
    shares: List[Tuple[int,int]] = []
    for i in range(1, total_shares + 1):
        x = i
        y = evaluate_polynomial(coeffs, x, prime_modulus)
        shares.append((x, y))
    return prime_modulus, shares
def recover_secret_with_gaussian_elimination(provided_shares: List[Tuple[int,int]], prime_modulus: int) -> int:
    if len(provided_shares) == 0:
        raise ValueError("At least one share required")
    r = len(provided_shares)
    A: List[List[int]] = []
    b: List[int] = []
    for (x, y) in provided_shares:
        row = []
        power = 1
        x_mod = x % prime_modulus
        for _ in range(r):
            row.append(power)
            power = (power * x_mod) % prime_modulus
        A.append(row)
        b.append(y % prime_modulus)
    coeffs = gaussian_elimination_modular(A, b, prime_modulus)
    return coeffs[0] % prime_modulus
# ---- helpers ----
def bytes_to_integer(byte_data: bytes) -> int:
    return int.from_bytes(byte_data, "big")
def integer_to_bytes(integer_value: int, length: int = None) -> bytes:
    if integer_value < 0:
        raise ValueError("Negative integer")
    minimal = (integer_value.bit_length() + 7) // 8
    if minimal == 0:
        minimal = 1
    if length is None:
        length = minimal
    return integer_value.to_bytes(length, "big")
# ---- demo ----
def demo() -> None:
    secret = 123456789012345678901234567890
    total_shares = 6
    threshold = 3
    p, shares = create_shares(secret, total_shares, threshold)
    print("Selected prime modulus p:", p, "  已选择素数模 p:", p)
    print("Generated shares (x, y):  生成的份额 (x, y):")
    for s in shares:
        print("  ", s)
    subset = shares[:threshold]
    recovered = recover_secret_with_gaussian_elimination(subset, p)
    print("Recovered from first {} shares: {}".format(threshold, recovered), "  从前 {} 个份额恢复: {}".format(threshold, recovered))
    assert recovered == secret
    subset2 = shares[-threshold:]
    recovered2 = recover_secret_with_gaussian_elimination(subset2, p)
    print("Recovered from last {} shares: {}".format(threshold, recovered2), "  从后 {} 个份额恢复: {}".format(threshold, recovered2))
    assert recovered2 == secret
    print("Recovery successful. 恢复成功。")
if __name__ == "__main__":
    demo()
