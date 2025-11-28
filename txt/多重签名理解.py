# demo_single_vs_multisig.py
# pip install ecdsa
import hashlib
from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError
def hash_message(text: str) -> bytes:
    return hashlib.sha256(text.encode('utf-8')).digest()
# ---------- single signature ----------
def generate_single_key():
    sk = SigningKey.generate(curve=SECP256k1)
    vk = sk.get_verifying_key()
    return sk, vk
def sign_single(sk: SigningKey, text: str) -> bytes:
    h = hash_message(text)
    return sk.sign_digest(h, sigencode=SigningKey.sigencode_der)
def verify_single(vk: VerifyingKey, text: str, sig: bytes) -> bool:
    h = hash_message(text)
    try:
        return vk.verify_digest(sig, h, sigdecode=VerifyingKey.sigdecode_der)
    except BadSignatureError:
        return False
# ---------- multi‑signature (M of N) ----------
def generate_multi_keys(n: int):
    keys = []
    for _ in range(n):
        sk = SigningKey.generate(curve=SECP256k1)
        vk = sk.get_verifying_key()
        keys.append((sk, vk))
    return keys
def sign_multi(sk_list, text: str, m: int):
    h = hash_message(text)
    sigs = []
    for i in range(m):
        sig = sk_list[i].sign_digest(h, sigencode=SigningKey.sigencode_der)
        sigs.append(sig)
    return sigs
def verify_multi(vk_list, text: str, sigs, m: int) -> bool:
    h = hash_message(text)
    valid = 0
    used = set()
    for sig in sigs:
        for idx, vk in enumerate(vk_list):
            if idx in used:
                continue
            try:
                if vk.verify_digest(sig, h, sigdecode=VerifyingKey.sigdecode_der):
                    valid += 1
                    used.add(idx)
                    break
            except BadSignatureError:
                continue
    return valid >= m
# ---------- demo ----------
if __name__ == "__main__":
    msg = "Demo text for signing."
    # single
    sk_s, vk_s = generate_single_key()
    sig_s = sign_single(sk_s, msg)
    print("single ok:", verify_single(vk_s, msg, sig_s))
    # multi 2-of-3
    keys = generate_multi_keys(3)
    sks = [k[0] for k in keys]
    vks = [k[1] for k in keys]
    sigs = sign_multi(sks, msg, 2)
    print("multi 2-of-3 ok:", verify_multi(vks, msg, sigs, 2))
    # insufficient signatures
    sigs_one = sign_multi(sks, msg, 1)
    print("multi insufficient ok:", verify_multi(vks, msg, sigs_one, 2))
