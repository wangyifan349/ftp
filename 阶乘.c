#include <stdio.h>
#include <stdlib.h>
#include <limits.h>
#include <stdbool.h>

/* 检查 a * b 是否会在 unsigned long long 上溢出 */
bool mul_will_overflow_u64(unsigned long long a, unsigned long long b) {
    if (a == 0 || b == 0) return false;
    return a > ULLONG_MAX / b;
}

/* 递归计算 n!，通过指针返回结果；若溢出返回 false */
bool factorial_rec_u64(unsigned long long *res, unsigned int n) {
    if (n == 0 || n == 1) {
        *res = 1ULL;
        return true;
    }
    unsigned long long sub;
    if (!factorial_rec_u64(&sub, n - 1)) return false;
    if (mul_will_overflow_u64(sub, (unsigned long long)n)) return false;
    *res = sub * (unsigned long long)n;
    return true;
}

int main(int argc, char *argv[]) {
    unsigned int n = 20; // 默认
    if (argc >= 2) {
        char *end;
        unsigned long tmp = strtoul(argv[1], &end, 10);
        if (*end != '\0' || tmp == 0) {
            fprintf(stderr, "Usage: %s [n>0]\n", argv[0]);
            return 1;
        }
        n = (unsigned int)tmp;
    }

    unsigned long long sum = 0;
    printf("n  n! (unsigned long long)        Sk = 1 + 2! + ... + n!\n");
    printf("---------------------------------------------------------\n");
    for (unsigned int i = 1; i <= n; ++i) {
        unsigned long long fact;
        if (!factorial_rec_u64(&fact, i)) {
            printf("Overflow detected computing %u!. Stop. Use GMP for big integers or reduce n.\n", i);
            return 1;
        }
        if (ULLONG_MAX - sum < fact) {
            printf("Overflow detected adding %u! to sum. Stop. Use GMP for big integers or reduce n.\n", i);
            return 1;
        }
        sum += fact;
        printf("%2u  %20llu  %20llu\n", i, fact, sum);
    }
    printf("---------------------------------------------------------\n");
    printf("Final: %u! = %llu\n", n, (unsigned long long)0); // avoid printing outdated var
    printf("Final: S = 1 + 2! + ... + %u! = %llu\n", n, sum);
    return 0;
}
