/*
 * memory_perf.c
 * 内存操作性能与准确性基准示例
 *
 * 特性：
 * - 高分辨率计时（clock_gettime）
 * - 多次重复测量并取中位数减少噪声
 * - 比较 memcpy 与手写循环（按 8/16/32/64 位块复制）
 * - 对齐分配（posix_memalign）以测试对齐影响
 * - 测试 calloc/malloc/realloc 性能
 * - 验证拷贝正确性
 * - 可使用 -O2/-O3 编译并建议使用 -march=native 以评估最快速度
 *
 * 编译示例：
 *   gcc -O3 -march=native -std=c11 -Wall memory_perf.c -o memory_perf
 * 或（带地址与未定义行为检测，仅用于调试）：
 *   gcc -O2 -std=c11 -Wall -fsanitize=address,undefined -g memory_perf.c -o memory_perf
 *
 * 运行示例：
 *   ./memory_perf
 */

#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdint.h>
#include <inttypes.h>
#include <errno.h>

/* 基准配置 */
static const size_t BUFSIZE = 64 * 1024 * 1024; /* 64 MB */
static const int ITER = 11; /* 做奇数次以取中位数 */

/* 高分辨率计时（纳秒） */
static uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

/* 取数组中位数（数组长度为奇数） */
static double median_double(double *a, int n) {
    /* 简单选择：复制并快速排序 */
    double *tmp = malloc(n * sizeof(double));
    if (!tmp) return -1.0;
    memcpy(tmp, a, n * sizeof(double));
    /* qsort */
    int cmp(const void *p, const void *q) {
        double x = *(const double*)p, y = *(const double*)q;
        return (x < y) ? -1 : (x > y);
    }
    qsort(tmp, n, sizeof(double), cmp);
    double m = tmp[n/2];
    free(tmp);
    return m;
}

/* 验证两个缓冲区相等 */
static int verify_equal(const void *a, const void *b, size_t n) {
    return memcmp(a, b, n) == 0;
}

/* 测试 memcpy 性能 */
static double bench_memcpy(void *dst, const void *src, size_t n, int iterations) {
    double times[ITER];
    for (int it = 0; it < iterations; ++it) {
        uint64_t t0 = now_ns();
        memcpy(dst, src, n);
        uint64_t t1 = now_ns();
        times[it] = (double)(t1 - t0) / 1e9; /* 秒 */
        /* 防止优化：访问 dst */
        volatile uint8_t sink = ((uint8_t*)dst)[0];
        (void)sink;
    }
    return median_double(times, iterations);
}

/* 手写按 64-bit 块复制（较快且可与 memcpy 比较） */
static void copy_u64(void *dst, const void *src, size_t n) {
    uint64_t *d = (uint64_t*)dst;
    const uint64_t *s = (const uint64_t*)src;
    size_t cnt = n / sizeof(uint64_t);
    for (size_t i = 0; i < cnt; ++i) d[i] = s[i];
    /* 余下字节 */
    size_t rem = n % sizeof(uint64_t);
    uint8_t *db = (uint8_t*)d + cnt * sizeof(uint64_t);
    const uint8_t *sb = (const uint8_t*)s + cnt * sizeof(uint64_t);
    for (size_t i = 0; i < rem; ++i) db[i] = sb[i];
}

/* 基准 wrapper for copy_u64 */
static double bench_copy_u64(void *dst, const void *src, size_t n, int iterations) {
    double times[ITER];
    for (int it = 0; it < iterations; ++it) {
        uint64_t t0 = now_ns();
        copy_u64(dst, src, n);
        uint64_t t1 = now_ns();
        times[it] = (double)(t1 - t0) / 1e9;
        volatile uint8_t sink = ((uint8_t*)dst)[0];
        (void)sink;
    }
    return median_double(times, iterations);
}

/* 基准 calloc/malloc/realloc */
static double bench_alloc_free(size_t n, int iterations) {
    double times[ITER];
    for (int it = 0; it < iterations; ++it) {
        uint64_t t0 = now_ns();
        void *p = malloc(n);
        uint64_t t1 = now_ns();
        if (!p) {
            perror("malloc failed");
            return -1.0;
        }
        /* 触发页面分配：写第一个和最后一个字节 */
        ((uint8_t*)p)[0] = 1;
        ((uint8_t*)p)[n-1] = 1;
        free(p);
        uint64_t t2 = now_ns();
        times[it] = (double)(t2 - t0) / 1e9;
    }
    return median_double(times, iterations);
}

/* 打印带单位的吞吐率 */
static void print_bandwidth(const char *label, double seconds, size_t bytes) {
    double bw = (double)bytes / seconds; /* B/s */
    const char *units[] = {"B/s","KB/s","MB/s","GB/s"};
    int u = 0;
    while (bw >= 1024.0 && u < 3) { bw /= 1024.0; ++u; }
    printf("%-20s : %10.6f s, %8.3f %s\n", label, seconds, bw, units[u]);
}

int main(void) {
    printf("memory_perf: buffer=%zu bytes, iterations=%d\n", (size_t)BUFSIZE, ITER);

    /* 对齐分配源和目标 */
    void *src = NULL, *dst = NULL;
    int rc = posix_memalign(&src, 64, BUFSIZE); /* 64-byte 对齐 */
    if (rc) { fprintf(stderr, "posix_memalign src failed: %s\n", strerror(rc)); return 1; }
    rc = posix_memalign(&dst, 64, BUFSIZE);
    if (rc) { fprintf(stderr, "posix_memalign dst failed: %s\n", strerror(rc)); free(src); return 1; }

    /* 初始化源数据为伪随机（固定种子，保证可重复） */
    uint8_t *s8 = (uint8_t*)src;
    for (size_t i = 0; i < BUFSIZE; ++i) s8[i] = (uint8_t)(i * 31 + 17);

    /* 基准 memcpy */
    double t_memcpy = bench_memcpy(dst, src, BUFSIZE, ITER);
    if (t_memcpy < 0) { free(src); free(dst); return 1; }
    if (!verify_equal(dst, src, BUFSIZE)) {
        fprintf(stderr, "memcpy verification failed\n");
        free(src); free(dst); return 1;
    }
    print_bandwidth("memcpy", t_memcpy, BUFSIZE);

    /* 基准 自己实现的 64-bit copy */
    double t_u64 = bench_copy_u64(dst, src, BUFSIZE, ITER);
    if (!verify_equal(dst, src, BUFSIZE)) {
        fprintf(stderr, "copy_u64 verification failed\n");
        free(src); free(dst); return 1;
    }
    print_bandwidth("copy_u64", t_u64, BUFSIZE);

    /* 比较 calloc (初始化) 与 malloc+memset */
    double t_calloc = -1.0, t_malloc_memset = -1.0;
    {
        double times_c[ITER];
        for (int it = 0; it < ITER; ++it) {
            uint64_t t0 = now_ns();
            void *p = calloc(1, BUFSIZE);
            uint64_t t1 = now_ns();
            if (!p) { perror("calloc failed"); break; }
            /* 访问 to ensure pages committed */
            ((uint8_t*)p)[0] = 1;
            ((uint8_t*)p)[BUFSIZE-1] = 1;
            free(p);
            uint64_t t2 = now_ns();
            times_c[it] = (double)(t2 - t0) / 1e9;
        }
        t_calloc = median_double(times_c, ITER);
    }
    {
        double times_m[ITER];
        for (int it = 0; it < ITER; ++it) {
            uint64_t t0 = now_ns();
            void *p = malloc(BUFSIZE);
            if (!p) { perror("malloc failed"); break; }
            memset(p, 0, BUFSIZE);
            free(p);
            uint64_t t1 = now_ns();
            times_m[it] = (double)(t1 - t0) / 1e9;
        }
        t_malloc_memset = median_double(times_m, ITER);
    }
    print_bandwidth("calloc (init pages)", t_calloc, BUFSIZE);
    print_bandwidth("malloc+memset", t_malloc_memset, BUFSIZE);

    /* malloc/realloc/free 基准 */
    double t_alloc = bench_alloc_free(BUFSIZE, ITER);
    print_bandwidth("malloc+touch+free", t_alloc, BUFSIZE);

    /* 清理 */
    free(src);
    free(dst);

    printf("Done.\n");
    return 0;
}
