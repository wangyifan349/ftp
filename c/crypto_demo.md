```toml
[package]
name = "crypto_demo"
version = "0.1.0"
edition = "2021"

[dependencies]
aes-gcm = "0.10"
chacha20poly1305 = "0.10"
rand = "0.8"
base64 = "0.21"
argon2 = "0.4"
hkdf = "0.13"
x25519-dalek = "1.2"
sha2 = "0.10"
zeroize = "1.5"
anyhow = "1.0"
hex = "0.4"
```

src/main.rs:
```rust
//! crypto_demo: 演示 AES-256-GCM 对称加密（含 Argon2 密钥派生、AAD）
//! 以及基于 X25519 的非对称密钥封装 + ChaCha20-Poly1305 对称加密。
//!
//! 输出所有密文均为单个 Base64 字符串，格式在注释中有说明。
//!
//! 仅为演示用途：生产请使用 KMS、硬件模块或受信任的密钥管理方案。

use aes_gcm::{Aes256Gcm, Key, Nonce};
use aes_gcm::aead::{Aead, NewAead, Payload};
use chacha20poly1305::ChaCha20Poly1305;
use chacha20poly1305::aead::AeadCore;
use chacha20poly1305::aead::OsRng as ChaChaOsRng;
use chacha20poly1305::aead::rand_core::RngCore;
use chacha20poly1305::aead::rand_core::SeedableRng;
use chacha20poly1305::aead::rand_core::CryptoRng;
use chacha20poly1305::aead::rand_core::block::BlockRng;
use chacha20poly1305::XChaCha20Poly1305;
use chacha20poly1305::aead::KeyInit;
use rand::RngCore as RandRngCore;
use rand::rngs::OsRng;
use base64::{engine::general_purpose, Engine as _};
use argon2::{Argon2, password_hash::{SaltString, PasswordHasher}};
use hkdf::Hkdf;
use sha2::Sha256;
use x25519_dalek::{EphemeralSecret, PublicKey as X25519Public, StaticSecret};
use zeroize::Zeroize;
use anyhow::{Context, Result};
use std::convert::TryInto;

/// 常量
const VERSION: u8 = 1; // 输出格式版本
const NONCE_LEN: usize = 12; // GCM 推荐 12 字节 nonce
const SALT_MAX_LEN: usize = 255; // 我们用 1 字节表示 salt 长度

// ---------------------------
// 辅助：Argon2 派生 key（32 字节）
// ---------------------------
fn derive_key_argon2(passphrase: &str, salt: &[u8]) -> Result<[u8; 32]> {
    // Argon2id 默认参数（示例）。生产环境按目标硬件调整：
    // m_cost 64MB, t_cost 3, parallelism 1 的典型值
    let argon2 = Argon2::default();
    let mut key = [0u8; 32];
    argon2
        .hash_password_into(passphrase.as_bytes(), salt, &mut key)
        .context("argon2 derive failed")?;
    Ok(key)
}

// ---------------------------
// 对称加密：AES-256-GCM
// 输出格式（Base64编码）说明（字节顺序）:
// [version:1][salt_len:1][salt: salt_len][nonce:12][ciphertext:rest]
// - version: u8，便于后续兼容升级
// - salt_len: 0 表示未使用 passphrase（密钥由调用方提供）
// - salt: 如果使用 passphrase，则必须存储 salt 以便解密时派生相同 key
// - nonce: GCM nonce（12 字节）
// - ciphertext: AES-GCM 输出（包含 tag）
// All data encoded as single Base64 string for easy transport/store.
// ---------------------------
fn encrypt_aes256_gcm(
    plaintext: &str,
    key_opt: Option<&[u8; 32]>,   // 如果为 None，可传入 passphrase
    passphrase_opt: Option<&str>, // 如果 Some，使用 Argon2 + 随机 salt 派生 key，并将 salt 写入输出
    aad_opt: Option<&[u8]>,
) -> Result<String> {
    // 获取 key 和 salt（可选）
    let (key_bytes, salt_opt) = if let Some(pw) = passphrase_opt {
        // 生成随机 salt
        let salt = SaltString::generate(&mut OsRng).as_bytes().to_vec();
        let key = derive_key_argon2(pw, &salt)?;
        (key, Some(salt))
    } else if let Some(k) = key_opt {
        (*k, None)
    } else {
        // 既没有 passphrase 也没有 key 提供：生成随机 key（调用者负责保存）
        let mut rand_key = [0u8; 32];
        OsRng.fill_bytes(&mut rand_key);
        (rand_key, None)
    };

    let cipher = Aes256Gcm::new(Key::from_slice(&key_bytes));

    // 随机 nonce (12 bytes)
    let mut nonce_bytes = [0u8; NONCE_LEN];
    OsRng.fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);

    // 加密（支持 AAD）
    let ciphertext = if let Some(aad) = aad_opt {
        cipher.encrypt(nonce, Payload { msg: plaintext.as_bytes(), aad })
    } else {
        cipher.encrypt(nonce, plaintext.as_bytes())
    }
    .context("AES-GCM encrypt failed")?;

    // 组合输出
    let mut out = Vec::with_capacity(1 + 1 + salt_opt.as_ref().map(|s| s.len()).unwrap_or(0) + NONCE_LEN + ciphertext.len());
    out.push(VERSION);
    if let Some(salt) = &salt_opt {
        let salt_len = salt.len();
        if salt_len > SALT_MAX_LEN { return Err(anyhow::anyhow!("salt too long")); }
        out.push(salt_len as u8);
        out.extend_from_slice(salt);
    } else {
        out.push(0u8);
    }
    out.extend_from_slice(&nonce_bytes);
    out.extend_from_slice(&ciphertext);

    // 清理 key
    let mut zk = key_bytes;
    zk.zeroize();

    Ok(general_purpose::STANDARD.encode(out))
}

fn decrypt_aes256_gcm(
    encoded: &str,
    key_opt: Option<&[u8; 32]>,     // 如果使用 passphrase，此处为 None
    passphrase_opt: Option<&str>,   // 如果 Some，则在输出中期望 salt 并派生 key
    aad_opt: Option<&[u8]>,
) -> Result<String> {
    let data = general_purpose::STANDARD.decode(encoded).context("base64 decode failed")?;
    if data.len() < 1 + 1 + NONCE_LEN {
        return Err(anyhow::anyhow!("data too short"));
    }
    let mut idx = 0usize;
    let version = data[idx]; idx +=1;
    if version != VERSION {
        return Err(anyhow::anyhow!("unsupported version"));
    }
    let salt_len = data[idx] as usize; idx +=1;
    if salt_len > 0 {
        if data.len() < idx + salt_len + NONCE_LEN {
            return Err(anyhow::anyhow!("data too short for salt/nonce"));
        }
    } else {
        if data.len() < idx + NONCE_LEN {
            return Err(anyhow::anyhow!("data too short for nonce"));
        }
    }
    let salt = if salt_len > 0 {
        let s = data[idx..idx+salt_len].to_vec();
        idx += salt_len;
        Some(s)
    } else {
        None
    };
    let nonce_bytes = &data[idx..idx+NONCE_LEN]; idx += NONCE_LEN;
    let ciphertext = &data[idx..];

    // 获取 key
    let key_bytes = if let Some(pw) = passphrase_opt {
        let salt = salt.ok_or_else(|| anyhow::anyhow!("missing salt for passphrase"))?;
        derive_key_argon2(pw, &salt)?
    } else if let Some(k) = key_opt {
        *k
    } else {
        return Err(anyhow::anyhow!("no key or passphrase provided"));
    };

    let cipher = Aes256Gcm::new(Key::from_slice(&key_bytes));
    let nonce = Nonce::from_slice(nonce_bytes);

    let plaintext_bytes = if let Some(aad) = aad_opt {
        cipher.decrypt(nonce, Payload { msg: ciphertext, aad })
    } else {
        cipher.decrypt(nonce, ciphertext)
    }
    .context("AES-GCM decrypt failed (auth failure?)")?;

    // 清理 key
    let mut zk = key_bytes;
    zk.zeroize();

    let plaintext = String::from_utf8(plaintext_bytes).context("invalid utf8")?;
    Ok(plaintext)
}

// ---------------------------
// 非对称：X25519 ephemeral -> 接收方静态 (HKDF -> ChaCha20-Poly1305)
// 输出格式（Base64）: [version:1][ephemeral_pub(32)][nonce(12)][ciphertext]
// 注意：接收方需要其静态私钥来解密。此处仅演示单个消息封装。
// ---------------------------

fn encrypt_x25519_chacha20poly1305(
    plaintext: &str,
    receiver_pub: &[u8; 32], // 接收方 X25519 公钥（静态）
    aad_opt: Option<&[u8]>,
) -> Result<String> {
    // 1. 生成 ephemeral secret & pub
    let eph_secret = EphemeralSecret::new(OsRng);
    let eph_pub = X25519Public::from(&eph_secret);

    // 2. 计算共享 secret = eph_secret.diffie_hellman(receiver_pub)
    let receiver_pub_key = X25519Public::from(*receiver_pub);
    let shared = eph_secret.diffie_hellman(&receiver_pub_key);

    // 3. 从 shared 派生对称 key（HKDF-SHA256）
    let hk = Hkdf::<Sha256>::new(None, shared.as_bytes());
    let mut okm = [0u8; 32];
    hk.expand(&[], &mut okm).context("hkdf expand failed")?;

    // 4. 使用 XChaCha20-Poly1305 或 ChaCha20-Poly1305 (这里用 XChaCha20Poly1305 提供更长 nonce)
    let cipher = XChaCha20Poly1305::new(&okm.into());
    let mut nonce = [0u8; 24];
    OsRng.fill_bytes(&mut nonce);
    let ct = if let Some(aad) = aad_opt {
        cipher.encrypt(&nonce.into(), Payload { msg: plaintext.as_bytes(), aad })
    } else {
        cipher.encrypt(&nonce.into(), plaintext.as_bytes())
    }.context("xchacha encrypt failed")?;

    // 组合：version || eph_pub(32) || nonce(24) || ct
    let mut out = Vec::with_capacity(1 + 32 + 24 + ct.len());
    out.push(VERSION);
    out.extend_from_slice(eph_pub.as_bytes());
    out.extend_from_slice(&nonce);
    out.extend_from_slice(&ct);

    // 清理 okm
    okm.zeroize();

    Ok(general_purpose::STANDARD.encode(out))
}

fn decrypt_x25519_chacha20poly1305(
    encoded: &str,
    receiver_priv: &[u8; 32], // 接收方静态私钥
    aad_opt: Option<&[u8]>,
) -> Result<String> {
    let data = general_purpose::STANDARD.decode(encoded).context("base64 decode failed")?;
    // minimal length check
    if data.len() < 1 + 32 + 24 + 16 { // 16 = poly1305 tag 最小长度
        return Err(anyhow::anyhow!("data too short"));
    }
    let mut idx = 0usize;
    let version = data[idx]; idx +=1;
    if version != VERSION { return Err(anyhow::anyhow!("unsupported version")); }
    let eph_pub_bytes: [u8; 32] = data[idx..idx+32].try_into().unwrap(); idx += 32;
    let nonce_bytes: [u8; 24] = data[idx..idx+24].try_into().unwrap(); idx += 24;
    let ciphertext = &data[idx..];

    let eph_pub = X25519Public::from(eph_pub_bytes);
    let receiver_secret = StaticSecret::from(*receiver_priv);
    let shared = receiver_secret.diffie_hellman(&eph_pub);

    // HKDF -> key
    let hk = Hkdf::<Sha256>::new(None, shared.as_bytes());
    let mut okm = [0u8; 32];
    hk.expand(&[], &mut okm).context("hkdf expand failed")?;

    let cipher = XChaCha20Poly1305::new(&okm.into());
    let plaintext_bytes = if let Some(aad) = aad_opt {
        cipher.decrypt(&nonce_bytes.into(), Payload { msg: ciphertext, aad })
    } else {
        cipher.decrypt(&nonce_bytes.into(), ciphertext)
    }
    .context("xchacha decrypt failed")?;

    // 清理
    okm.zeroize();

    let s = String::from_utf8(plaintext_bytes).context("invalid utf8")?;
    Ok(s)
}

// ---------------------------
// Demo main 和 单元测试
// ---------------------------
fn main() -> Result<()> {
    // 简单 demo: 对称随机 key
    let key = {
        let mut k = [0u8; 32];
        OsRng.fill_bytes(&mut k);
        k
    };
    let pt = "Rust 加密示例 - 明文字符串";
    let ct = encrypt_aes256_gcm(pt, Some(&key), None, Some(b"demo-aad"))?;
    println!("AES-GCM (random key) ciphertext: {}", ct);
    let pt2 = decrypt_aes256_gcm(&ct, Some(&key), None, Some(b"demo-aad"))?;
    println!("decrypted: {}", pt2);

    // 对称：passphrase 派生 key
    let pass = "correct horse battery staple";
    let ct_pw = encrypt_aes256_gcm("使用 passphrase 的消息", None, Some(pass), None)?;
    println!("AES-GCM (passphrase) ciphertext: {}", ct_pw);
    let pt_pw = decrypt_aes256_gcm(&ct_pw, None, Some(pass), None)?;
    println!("decrypted(passphrase): {}", pt_pw);

    // 非对称：生成接收方静态密钥对（示例）
    let receiver_secret = StaticSecret::new(OsRng);
    let receiver_pub = X25519Public::from(&receiver_secret);
    let recv_pub_bytes = receiver_pub.as_bytes().clone();
    let recv_priv_bytes = receiver_secret.to_bytes();

    let ct_asym = encrypt_x25519_chacha20poly1305("这是非对称加密消息", &recv_pub_bytes, None)?;
    println!("X25519+XChaCha20 ciphertext: {}", ct_asym);
    let pt_asym = decrypt_x25519_chacha20poly1305(&ct_asym, &recv_priv_bytes, None)?;
    println!("decrypted(asym): {}", pt_asym);

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_aes_roundtrip_random_key() {
        let mut key = [0u8; 32];
        OsRng.fill_bytes(&mut key);
        let pt = "hello aes-gcm";
        let ct = encrypt_aes256_gcm(pt, Some(&key), None, Some(b"aad")).unwrap();
        let out = decrypt_aes256_gcm(&ct, Some(&key), None, Some(b"aad")).unwrap();
        assert_eq!(pt, out);
    }

    #[test]
    fn test_aes_roundtrip_passphrase() {
        let pass = "pw123";
        let pt = "secret text";
        let ct = encrypt_aes256_gcm(pt, None, Some(pass), None).unwrap();
        let out = decrypt_aes256_gcm(&ct, None, Some(pass), None).unwrap();
        assert_eq!(pt, out);
    }

    #[test]
    fn test_aes_auth_failure() {
        let mut key = [0u8; 32];
        OsRng.fill_bytes(&mut key);
        let pt = "auth test";
        let mut ct = encrypt_aes256_gcm(pt, Some(&key), None, None).unwrap();
        // tamper: flip a byte in base64 decoded payload
        let mut raw = general_purpose::STANDARD.decode(&ct).unwrap();
        raw[raw.len()-1] ^= 0x01;
        let tampered = general_purpose::STANDARD.encode(&raw);
        assert!(decrypt_aes256_gcm(&tampered, Some(&key), None, None).is_err());
    }

    #[test]
    fn test_x25519_roundtrip() {
        let receiver_secret = StaticSecret::new(OsRng);
        let receiver_pub = X25519Public::from(&receiver_secret);
        let recv_pub_bytes = receiver_pub.as_bytes().clone();
        let recv_priv_bytes = receiver_secret.to_bytes();

        let pt = "asymmetric msg";
        let ct = encrypt_x25519_chacha20poly1305(pt, &recv_pub_bytes, None).unwrap();
        let out = decrypt_x25519_chacha20poly1305(&ct, &recv_priv_bytes, None).unwrap();
        assert_eq!(pt, out);
    }
}
```
