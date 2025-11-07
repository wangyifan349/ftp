/* factorial_menu_gmp_c89.c
 *
 * GMP 支持的阶乘交互式菜单，兼容 C89（ISO C90）。
 *
 * 编译：
 *   gcc -O2 -std=c89 -pedantic -Wall -Wextra -o factorial_menu_gmp_c89 factorial_menu_gmp_c89.c -lgmp
 *
 * 运行：
 *   ./factorial_menu_gmp_c89
 *
 * 注意：与先前版本相同的安全与资源提示适用。
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <limits.h>
#include <gmp.h>

typedef unsigned int uint;

/* 读取一行并解析成 unsigned int，返回是否成功 */
int read_uint_from_stdin(uint *out)
{
    char buf[256];
    char *p;
    char *end;
    unsigned long v;

    if (!fgets(buf, sizeof(buf), stdin)) return 0;
    p = buf;
    while (isspace((unsigned char)*p)) ++p;
    if (*p == '\0' || *p == '\n') return 0;
    v = strtoul(p, &end, 10);
    if (end == p) return 0;
    while (isspace((unsigned char)*end)) ++end;
    if (*end != '\0' && *end != '\n') return 0;
    *out = (uint)v;
    return 1;
}

/* 使用 unsigned long long 迭代计算 n!（带溢出检测），若成功返回 1 并写入 *res_u64 */
int factorial_iter_u64(unsigned long long *res_u64, uint n)
{
    unsigned long long r = 1ULL;
    uint i;
    for (i = 2; i <= n; ++i) {
        if (i != 0 && r > ULLONG_MAX / i) return 0;
        r *= (unsigned long long)i;
    }
    *res_u64 = r;
    return 1;
}

/* 使用 GMP 迭代计算 n!，结果放入 res (mpz_t)。res 必须已初始化。 */
void factorial_gmp(mpz_t res, uint n)
{
    uint i;
    mpz_set_ui(res, 1U);
    for (i = 2; i <= n; ++i) {
        mpz_mul_ui(res, res, i);
    }
}

/* 计算并打印 n! 的素因子幂次（Legendre 公式），不依赖 n! 的大小 */
void prime_factor_exponents_of_factorial(uint n)
{
    unsigned int limit;
    unsigned int i, p, q;
    char *is_prime;

    if (n <= 1) {
        printf("%u! = 1 (没有素因子)\n", (unsigned int)n);
        return;
    }
    limit = n;
    is_prime = (char *)malloc((limit + 1) * sizeof(char));
    if (!is_prime) {
        fprintf(stderr, "内存分配失败\n");
        return;
    }
    for (i = 0; i <= limit; ++i) is_prime[i] = 1;
    is_prime[0] = is_prime[1] = 0;
    for (p = 2; (unsigned long)p * (unsigned long)p <= limit; ++p) {
        if (is_prime[p]) {
            for (q = p * p; q <= limit; q += p) is_prime[q] = 0;
        }
    }
    printf("%u! 的素因子幂次（p^e）：\n", (unsigned int)n);
    for (p = 2; p <= limit; ++p) {
        if (!is_prime[p]) continue;
        {
            unsigned int power = 0;
            unsigned int pp = p;
            while (pp <= n) {
                power += n / pp;
                if (pp > n / p) break;
                pp *= p;
            }
            if (power > 0) {
                printf("%u^%u  ", p, power);
            }
        }
    }
    printf("\n");
    free(is_prime);
}

/* 打印 mpz_t 的素因数分解（仅用于较小值）：试除法直到 sqrt(n)。对大数可能非常慢。 */
void print_prime_factorization_mpz(const mpz_t val)
{
    mpz_t n;
    mpz_t p;
    mpz_t sqrt_n;
    int first = 1;

    mpz_init(n);
    mpz_init(p);
    mpz_init(sqrt_n);

    mpz_set(n, val);

    if (mpz_cmp_ui(n, 0) == 0) { printf("0\n"); goto cleanup; }
    if (mpz_cmp_ui(n, 1) == 0) { printf("1\n"); goto cleanup; }

    /* 处理因子 2 */
    if (mpz_even_p(n)) {
        unsigned int cnt = 0;
        while (mpz_even_p(n)) {
            mpz_fdiv_q_2exp(n, n, 1); /* n /= 2 */
            ++cnt;
        }
        if (!first) printf(" * ");
        printf("2^%u", cnt);
        first = 0;
    }

    mpz_sqrt(sqrt_n, n);

    /* 试除奇数因子 */
    mpz_set_ui(p, 3);
    while (mpz_cmp(p, sqrt_n) <= 0) {
        if (mpz_divisible_p(n, p)) {
            unsigned int cnt = 0;
            while (mpz_divisible_p(n, p)) {
                mpz_divexact(n, n, p);
                ++cnt;
            }
            if (!first) printf(" * ");
            mpz_out_str(stdout, 10, p);
            printf("^%u", cnt);
            first = 0;
            mpz_sqrt(sqrt_n, n);
        }
        mpz_add_ui(p, p, 2);
    }

    if (mpz_cmp_ui(n, 1) > 0) {
        if (!first) printf(" * ");
        mpz_out_str(stdout, 10, n);
        printf("^1");
    }
    printf("\n");

cleanup:
    mpz_clear(n);
    mpz_clear(p);
    mpz_clear(sqrt_n);
}

/* 计算并打印 1/1! + ... + 1/n! 的 double 近似 */
void compute_reciprocal_factorial_sum_double(uint n)
{
    double sum = 0.0;
    double term = 1.0;
    unsigned int i;
    for (i = 1; i <= n; ++i) {
        term /= (double)i;
        sum += term;
    }
    printf("近似: 1/1! + ... + 1/%u! = %.17g\n", (unsigned int)n, sum);
}

/* 菜单选项实现（使用 GMP） */
void option_compute_single_factorial_gmp(void)
{
    uint n;
    unsigned long long u64val;
    int ok64;
    mpz_t fact;
    size_t bit_count;

    printf("输入 n (>=0): ");
    if (!read_uint_from_stdin(&n)) { printf("输入无效。\n"); return; }

    ok64 = factorial_iter_u64(&u64val, n);

    mpz_init(fact);
    factorial_gmp(fact, n);

    printf("%u! = ", (unsigned int)n);
    mpz_out_str(stdout, 10, fact);
    printf("\n");

    if (ok64) {
        printf("(u64 计算: %llu)\n", u64val);
    } else {
        printf("(u64 溢出；已使用 GMP 计算完整值)\n");
    }

    bit_count = mpz_sizeinbase(fact, 2);
    if (bit_count <= 1024) {
        printf("尝试对 %u! 做素因子分解（可能耗时）...\n", (unsigned int)n);
        print_prime_factorization_mpz(fact);
    } else {
        printf("数值太大（%zu 位），不尝试直接试除分解。改为输出素因子幂次：\n", bit_count);
        prime_factor_exponents_of_factorial(n);
    }

    mpz_clear(fact);
}

void option_compute_sum_factorials_gmp(void)
{
    uint n;
    mpz_t sum;
    mpz_t fact;
    mpz_t tmp;
    unsigned int i;

    printf("输入 n (>=1): ");
    if (!read_uint_from_stdin(&n) || n == 0) { printf("输入无效。\n"); return; }

    mpz_init(sum);
    mpz_init_set_ui(fact, 1);
    mpz_init(tmp);

    printf("i   i!                         S = 1! + ... + i!\n");
    printf("---------------------------------------------------------------\n");
    for (i = 1; i <= n; ++i) {
        mpz_mul_ui(fact, fact, i);
        printf("%2u  ", i);
        mpz_out_str(stdout, 10, fact);
        printf("  ");
        mpz_add(tmp, sum, fact);
        mpz_out_str(stdout, 10, tmp);
        printf("\n");
        mpz_add(sum, sum, fact);
    }
    printf("---------------------------------------------------------------\n");
    printf("最终 S = 1! + ... + %u! = ", (unsigned int)n);
    mpz_out_str(stdout, 10, sum);
    printf("\n");

    mpz_clear(sum);
    mpz_clear(fact);
    mpz_clear(tmp);
}

void option_reciprocal_sum(void)
{
    uint n;
    printf("输入 n (>=1，用于计算 1/1! + ... + 1/n!): ");
    if (!read_uint_from_stdin(&n) || n == 0) { printf("输入无效。\n"); return; }
    compute_reciprocal_factorial_sum_double(n);
}

void option_compare_recursive_iterative(void)
{
    uint n;
    unsigned long long r_iter;
    int ok_iter;
    mpz_t g;
    mpz_t from_u64;

    printf("输入 n (>=0，用于比较 u64（迭代）与 GMP): ");
    if (!read_uint_from_stdin(&n)) { printf("输入无效。\n"); return; }

    ok_iter = factorial_iter_u64(&r_iter, n);

    mpz_init(g);
    factorial_gmp(g, n);

    if (ok_iter) printf("（u64）迭代结果: %llu\n", r_iter);
    else printf("（u64）迭代结果: 溢出或不可用\n");

    printf("（GMP）结果（高精度）：");
    mpz_out_str(stdout, 10, g);
    printf("\n");

    if (ok_iter) {
        mpz_init(from_u64);
        mpz_set_ui(from_u64, r_iter);
        if (mpz_cmp(from_u64, g) == 0) printf("GMP 与 u64 迭代结果一致（当 u64 未溢出时）。\n");
        else printf("GMP 与 u64 结果不一致（不应发生）。\n");
        mpz_clear(from_u64);
    } else {
        printf("u64 溢出，无法与 GMP 比较完整值。\n");
    }

    mpz_clear(g);
}

void option_factorial_prime_exponents(void)
{
    uint n;
    printf("输入 n (>=0): ");
    if (!read_uint_from_stdin(&n)) { printf("输入无效。\n"); return; }
    prime_factor_exponents_of_factorial(n);
}

/* 主菜单循环 */
int main(void)
{
    uint opt;

    for (;;) {
        printf("\n=== 阶乘（GMP 支持，C89）相关计算菜单 ===\n");
        printf("1) 使用 GMP 计算 n! 并显示（任意精度），尝试素因子分解（对较小结果）\n");
        printf("2) 使用 GMP 计算并打印 1! + 2! + ... + n!\n");
        printf("3) 计算 1/1! + 1/2! + ... + 1/n! 的 double 近似\n");
        printf("4) 打印 n! 的素因子幂次（Legendre 公式）\n");
        printf("5) 比较 u64（迭代）与 GMP 的阶乘实现并报告（若 u64 未溢出）\n");
        printf("6) 退出\n");
        printf("请选择一个选项（1-6）： ");

        if (!read_uint_from_stdin(&opt)) {
            printf("读取选项失败，退出。\n");
            return 1;
        }

        if (opt == 1) option_compute_single_factorial_gmp();
        else if (opt == 2) option_compute_sum_factorials_gmp();
        else if (opt == 3) option_reciprocal_sum();
        else if (opt == 4) option_factorial_prime_exponents();
        else if (opt == 5) option_compare_recursive_iterative();
        else if (opt == 6) { printf("退出。\n"); return 0; }
        else printf("无效选项。\n");
    }
    /* not reached */
    return 0;
}
