// chacha20_poly1305_demo.c
// Requires libsodium: https://libsodium.org
// Compile: gcc -O2 chacha20_poly1305_demo.c -o demo -lsodium

#include <sodium.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

int main(void) {
    if (sodium_init() < 0) {
        fprintf(stderr, "libsodium init failed\n");
        return 1;
    }

    // 明文
    const unsigned char *msg = (const unsigned char *)
        "Example plaintext for ChaCha20-Poly1305 demo.";
    unsigned long long msg_len = (unsigned long long)strlen((const char *)msg);

    // 1) 生成密钥（32 字节）
    unsigned char key[crypto_aead_chacha20poly1305_IETF_KEYBYTES];
    randombytes_buf(key, sizeof key);

    // 2) 生成 12 字节 nonce （IETF variant 使用 12 字节）
    unsigned char nonce[crypto_aead_chacha20poly1305_IETF_NPUBBYTES];
    randombytes_buf(nonce, sizeof nonce);

    // 3) 加密（不使用 AAD）
    unsigned long long ciphertext_len = msg_len + crypto_aead_chacha20poly1305_IETF_ABYTES;
    unsigned char *ciphertext = malloc(ciphertext_len);
    if (!ciphertext) { perror("malloc"); return 1; }

    if (crypto_aead_chacha20poly1305_ietf_encrypt(
            ciphertext, &ciphertext_len,
            msg, msg_len,
            NULL, 0,          // no AAD
            NULL,              // nsec (not used)
            nonce, key) != 0) {
        fprintf(stderr, "encryption failed\n");
        free(ciphertext);
        return 1;
    }

    printf("Plaintext: %s\n", (const char *)msg);
    printf("Key (hex): ");
    for (size_t i = 0; i < sizeof key; ++i) printf("%02x", key[i]);
    printf("\nNonce (hex): ");
    for (size_t i = 0; i < sizeof nonce; ++i) printf("%02x", nonce[i]);
    printf("\nCiphertext+Tag (hex): ");
    for (unsigned long long i = 0; i < ciphertext_len; ++i) printf("%02x", ciphertext[i]);
    printf("\n");

    // 4) 解密（不使用 AAD）
    unsigned char *decrypted = malloc(ciphertext_len); // >= ciphertext_len
    if (!decrypted) { perror("malloc"); free(ciphertext); return 1; }
    unsigned long long decrypted_len = 0;

    if (crypto_aead_chacha20poly1305_ietf_decrypt(
            decrypted, &decrypted_len,
            NULL,               // nsec
            ciphertext, ciphertext_len,
            NULL, 0,            // no AAD
            nonce, key) != 0) {
        fprintf(stderr, "decryption failed: authentication failed\n");
        free(ciphertext); free(decrypted);
        return 1;
    }

    printf("Decrypted (%llu bytes): %.*s\n", decrypted_len, (int)decrypted_len, decrypted);

    free(ciphertext);
    free(decrypted);
    // 清除敏感数据
    sodium_memzero(key, sizeof key);
    sodium_memzero(nonce, sizeof nonce);

    return 0;
}
