/**
 * matrix_tools.c
 * 改进版矩阵工具库与演示程序
 *
 * 改进点：
 *  - 更好的输入/尺寸检查与返回值
 *  - 64-bit 中间运算并检测溢出
 *  - 更多工具：标量乘法、按列排序、行/列最大最小等
 *  - 可交互 demo：选择样例或从 stdin 读取
 *
 * 编译: gcc -std=c11 -O2 -Wall -Wextra -o matrix_tools matrix_tools.c
 * 运行: ./matrix_tools        （运行 demo）
 *       ./matrix_tools -i    （从 stdin 读取矩阵并执行示例）
 */

#include <stdio.h>
#include <stdlib.h>
#include <limits.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>

#define DEFAULT_MAX_ROWS 100
#define DEFAULT_MAX_COLS 100

/* 可调上限 —— 如果需要更大可以在编译或运行时改这些常量 */
static int MAX_ROWS = DEFAULT_MAX_ROWS;
static int MAX_COLS = DEFAULT_MAX_COLS;

/* 返回状态码 */
typedef enum {
    MT_OK = 0,
    MT_ERR_INVALID_DIM = 1,
    MT_ERR_OVERFLOW = 2,
    MT_ERR_MISMATCH = 3,
    MT_ERR_NULL = 4,
    MT_ERR_INPUT = 5
} mt_status_t;

/* 打印矩阵（rows x cols）。label 可为 NULL */
void print_matrix_labelled(int mat[][DEFAULT_MAX_COLS], int rows, int cols, const char *label) {
    if (label) printf("=== %s (%dx%d) ===\n", label, rows, cols);
    for (int i = 0; i < rows; ++i) {
        for (int j = 0; j < cols; ++j) {
            printf("%8d", mat[i][j]);
        }
        printf("\n");
    }
}

/* 安全检查尺寸 */
static bool dims_valid(int rows, int cols) {
    return rows > 0 && cols > 0 && rows <= MAX_ROWS && cols <= MAX_COLS;
}

/* 全矩阵填充 */
mt_status_t fill_matrix(int mat[][DEFAULT_MAX_COLS], int rows, int cols, int val) {
    if (!dims_valid(rows, cols) || mat == NULL) return MT_ERR_INVALID_DIM;
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            mat[i][j] = val;
    return MT_OK;
}

/* 复制矩阵 */
mt_status_t copy_matrix(int src[][DEFAULT_MAX_COLS], int dest[][DEFAULT_MAX_COLS], int rows, int cols) {
    if (!dims_valid(rows, cols) || src == NULL || dest == NULL) return MT_ERR_INVALID_DIM;
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            dest[i][j] = src[i][j];
    return MT_OK;
}

/* 从 stdin 安全读取矩阵（按行）。返回 MT_OK 或错误 */
mt_status_t input_matrix(int mat[][DEFAULT_MAX_COLS], int rows, int cols) {
    if (!dims_valid(rows, cols) || mat == NULL) return MT_ERR_INVALID_DIM;
    for (int i = 0; i < rows; ++i) {
        for (int j = 0; j < cols; ++j) {
            if (scanf("%d", &mat[i][j]) != 1) return MT_ERR_INPUT;
        }
    }
    return MT_OK;
}

/* 计算每一行和（写入 row_sums，数组长度应 >= rows）*/
mt_status_t row_sums(int mat[][DEFAULT_MAX_COLS], int rows, int cols, long long row_sums_out[]) {
    if (!dims_valid(rows, cols) || mat == NULL || row_sums_out == NULL) return MT_ERR_INVALID_DIM;
    for (int i = 0; i < rows; ++i) {
        long long s = 0;
        for (int j = 0; j < cols; ++j) s += mat[i][j];
        row_sums_out[i] = s;
    }
    return MT_OK;
}

/* 计算每一列和（写入 col_sums，数组长度应 >= cols）*/
mt_status_t col_sums(int mat[][DEFAULT_MAX_COLS], int rows, int cols, long long col_sums_out[]) {
    if (!dims_valid(rows, cols) || mat == NULL || col_sums_out == NULL) return MT_ERR_INVALID_DIM;
    for (int j = 0; j < cols; ++j) {
        long long s = 0;
        for (int i = 0; i < rows; ++i) s += mat[i][j];
        col_sums_out[j] = s;
    }
    return MT_OK;
}

/* 查找最大/最小值与位置（若多个返回第一个）*/
mt_status_t find_max(int mat[][DEFAULT_MAX_COLS], int rows, int cols, int *max_val, int *max_i, int *max_j) {
    if (!dims_valid(rows, cols) || mat == NULL || max_val == NULL || max_i == NULL || max_j == NULL)
        return MT_ERR_INVALID_DIM;
    int mv = INT_MIN, mi = -1, mj = -1;
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            if (mat[i][j] > mv) {
                mv = mat[i][j]; mi = i; mj = j;
            }
    *max_val = mv; *max_i = mi; *max_j = mj;
    return MT_OK;
}

mt_status_t find_min(int mat[][DEFAULT_MAX_COLS], int rows, int cols, int *min_val, int *min_i, int *min_j) {
    if (!dims_valid(rows, cols) || mat == NULL || min_val == NULL || min_i == NULL || min_j == NULL)
        return MT_ERR_INVALID_DIM;
    int mv = INT_MAX, mi = -1, mj = -1;
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            if (mat[i][j] < mv) {
                mv = mat[i][j]; mi = i; mj = j;
            }
    *min_val = mv; *min_i = mi; *min_j = mj;
    return MT_OK;
}

/* 查找值，返回出现次数并把第一次位置写回 */
int find_value(int mat[][DEFAULT_MAX_COLS], int rows, int cols, int value, int *first_i, int *first_j) {
    if (!dims_valid(rows, cols) || mat == NULL) {
        if (first_i) *first_i = -1;
        if (first_j) *first_j = -1;
        return 0;
    }
    int count = 0;
    if (first_i) *first_i = -1;
    if (first_j) *first_j = -1;
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            if (mat[i][j] == value) {
                if (count == 0 && first_i) { *first_i = i; *first_j = j; }
                ++count;
            }
    return count;
}

/* 就地转置方阵（rows==cols），失败返回非 0 */
mt_status_t transpose_square_inplace(int mat[][DEFAULT_MAX_COLS], int n) {
    if (n <= 0 || n > MAX_ROWS || mat == NULL) return MT_ERR_INVALID_DIM;
    for (int i = 0; i < n; ++i)
        for (int j = i + 1; j < n; ++j) {
            int t = mat[i][j]; mat[i][j] = mat[j][i]; mat[j][i] = t;
        }
    return MT_OK;
}

/* 转置到 dest（支持非方阵），要求 dest 有足够尺寸 */
mt_status_t transpose_to(int src[][DEFAULT_MAX_COLS], int rows, int cols, int dest[][DEFAULT_MAX_COLS]) {
    if (!dims_valid(rows, cols) || src == NULL || dest == NULL) return MT_ERR_INVALID_DIM;
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            dest[j][i] = src[i][j];
    return MT_OK;
}

/* 安全添加两个 int 检测溢出（返回 false 表示溢出）*/
static bool safe_add_int(int a, int b, int *out) {
    long long r = (long long)a + (long long)b;
    if (r > INT_MAX || r < INT_MIN) return false;
    *out = (int)r;
    return true;
}

/* 标量乘法（mat *= scalar）*/
mt_status_t scalar_multiply(int mat[][DEFAULT_MAX_COLS], int rows, int cols, int scalar) {
    if (!dims_valid(rows, cols) || mat == NULL) return MT_ERR_INVALID_DIM;
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j) {
            long long prod = (long long)mat[i][j] * (long long)scalar;
            if (prod > INT_MAX || prod < INT_MIN) return MT_ERR_OVERFLOW;
            mat[i][j] = (int)prod;
        }
    return MT_OK;
}

/* 矩阵相加：要求尺寸相同，结果写入 res。失败返回非 0 */
mt_status_t add_matrix(int a[][DEFAULT_MAX_COLS], int b[][DEFAULT_MAX_COLS], int rows, int cols, int res[][DEFAULT_MAX_COLS]) {
    if (!dims_valid(rows, cols) || a == NULL || b == NULL || res == NULL) return MT_ERR_INVALID_DIM;
    for (int i = 0; i < rows; ++i) {
        for (int j = 0; j < cols; ++j) {
            if (!safe_add_int(a[i][j], b[i][j], &res[i][j])) return MT_ERR_OVERFLOW;
        }
    }
    return MT_OK;
}

/* 矩阵乘法：a (r1 x c1) * b (r2 x c2) 要求 c1 == r2，结果写入 res (r1 x c2)
   使用 64-bit 中间并检测是否超出 int 范围（返回 MT_ERR_OVERFLOW）。
*/
mt_status_t multiply_matrix(int a[][DEFAULT_MAX_COLS], int r1, int c1, int b[][DEFAULT_MAX_COLS], int r2, int c2, int res[][DEFAULT_MAX_COLS]) {
    if (a == NULL || b == NULL || res == NULL) return MT_ERR_NULL;
    if (c1 != r2) return MT_ERR_MISMATCH;
    if (!dims_valid(r1, c2)) return MT_ERR_INVALID_DIM;
    for (int i = 0; i < r1; ++i) {
        for (int j = 0; j < c2; ++j) {
            long long sum = 0;
            for (int k = 0; k < c1; ++k) {
                sum += (long long)a[i][k] * (long long)b[k][j];
                /* 可选：早期溢出检测 */
                if (sum > (long long)INT_MAX || sum < (long long)INT_MIN) return MT_ERR_OVERFLOW;
            }
            res[i][j] = (int)sum;
        }
    }
    return MT_OK;
}

/* 对每一行进行升序排序（插入排序）*/
mt_status_t sort_rows_asc(int mat[][DEFAULT_MAX_COLS], int rows, int cols) {
    if (!dims_valid(rows, cols) || mat == NULL) return MT_ERR_INVALID_DIM;
    for (int i = 0; i < rows; ++i) {
        for (int j = 1; j < cols; ++j) {
            int key = mat[i][j];
            int k = j - 1;
            while (k >= 0 && mat[i][k] > key) {
                mat[i][k + 1] = mat[i][k];
                k--;
            }
            mat[i][k + 1] = key;
        }
    }
    return MT_OK;
}

/* 对每一列进行升序排序（插入排序）*/
mt_status_t sort_cols_asc(int mat[][DEFAULT_MAX_COLS], int rows, int cols) {
    if (!dims_valid(rows, cols) || mat == NULL) return MT_ERR_INVALID_DIM;
    for (int j = 0; j < cols; ++j) {
        for (int i = 1; i < rows; ++i) {
            int key = mat[i][j];
            int k = i - 1;
            while (k >= 0 && mat[k][j] > key) {
                mat[k + 1][j] = mat[k][j];
                k--;
            }
            mat[k + 1][j] = key;
        }
    }
    return MT_OK;
}

/* demo：显示若干操作并支持交互（选择样例或读入） */
static void demo_operations_interactive(bool read_from_stdin) {
    int a[DEFAULT_MAX_ROWS][DEFAULT_MAX_COLS];
    int b[DEFAULT_MAX_ROWS][DEFAULT_MAX_COLS];
    int t[DEFAULT_MAX_ROWS][DEFAULT_MAX_COLS];
    int res[DEFAULT_MAX_ROWS][DEFAULT_MAX_COLS];

    int rows = 3, cols = 4;

    if (read_from_stdin) {
        printf("请输入行数和列数（空格分隔，最大 %d x %d）：", MAX_ROWS, MAX_COLS);
        if (scanf("%d %d", &rows, &cols) != 2 || !dims_valid(rows, cols)) {
            fprintf(stderr, "无效尺寸输入，使用默认 3x4\n");
            rows = 3; cols = 4;
            /* 清理 stdin 错误状态 */
            int ch; while ((ch = getchar()) != EOF && ch != '\n') {}
        } else {
            printf("请按行输入 %dx%d 个整数：\n", rows, cols);
            if (input_matrix(a, rows, cols) != MT_OK) {
                fprintf(stderr, "读取矩阵失败，使用示例矩阵\n");
                rows = 3; cols = 4;
            }
        }
    }

    if (rows == 3 && cols == 4) {
        int sample[3][4] = {
            {3, 1, 4, 2},
            {5, 6, 1, 0},
            {9, 7, 8, -1}
        };
        for (int i = 0; i < rows; ++i)
            for (int j = 0; j < cols; ++j)
                a[i][j] = sample[i][j];
    }

    print_matrix_labelled(a, rows, cols, "初始矩阵 A");

    long long rs[DEFAULT_MAX_ROWS];
    if (row_sums(a, rows, cols, rs) == MT_OK) {
        printf("\n每行和:\n");
        for (int i = 0; i < rows; ++i) printf("row %d sum = %lld\n", i, rs[i]);
    }

    long long cs[DEFAULT_MAX_COLS];
    if (col_sums(a, rows, cols, cs) == MT_OK) {
        printf("\n每列和:\n");
        for (int j = 0; j < cols; ++j) printf("col %d sum = %lld\n", j, cs[j]);
    }

    int maxv, max_i, max_j;
    int minv, min_i, min_j;
    if (find_max(a, rows, cols, &maxv, &max_i, &max_j) == MT_OK)
        printf("\n最大值: %d at (%d,%d)\n", maxv, max_i, max_j);
    if (find_min(a, rows, cols, &minv, &min_i, &min_j) == MT_OK)
        printf("最小值: %d at (%d,%d)\n", minv, min_i, min_j);

    int target = 1, first_i = -1, first_j = -1;
    int cnt = find_value(a, rows, cols, target, &first_i, &first_j);
    if (cnt > 0)
        printf("\n值 %d 出现 %d 次，第一次出现在 (%d,%d)\n", target, cnt, first_i, first_j);
    else
        printf("\n值 %d 未找到\n", target);

    if (transpose_to(a, rows, cols, t) == MT_OK) {
        print_matrix_labelled(t, cols, rows, "A 的转置 T");
    }

    /* 复制 A -> B 并修改 B */
    copy_matrix(a, b, rows, cols);
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            b[i][j] += 10;
    print_matrix_labelled(b, rows, cols, "矩阵 B (由 A 复制并 +10)");

    if (add_matrix(a, b, rows, cols, res) == MT_OK) {
        print_matrix_labelled(res, rows, cols, "C = A + B");
    } else {
        fprintf(stderr, "矩阵相加溢出或尺寸错误\n");
    }

    /* A (r x c) * T (c x r) -> res (r x r) */
    if (multiply_matrix(a, rows, cols, t, cols, rows, res) == MT_OK) {
        print_matrix_labelled(res, rows, rows, "res = A * T (A * A^T)");
    } else {
        fprintf(stderr, "矩阵乘法失败（尺寸不匹配或溢出）\n");
    }

    print_matrix_labelled(a, rows, cols, "A 原始（用于排序前）");
    sort_rows_asc(a, rows, cols);
    print_matrix_labelled(a, rows, cols, "A 每行升序排序后");

    transpose_to(a, rows, cols, t);
    print_matrix_labelled(t, cols, rows, "排序后 A 的转置 T");

    fill_matrix(res, rows, rows, 7);
    print_matrix_labelled(res, rows, rows, "res（全部填充为 7）");
}

/* 简单命令行解析：-i 表示从 stdin 读矩阵，否则运行内置 demo */
int main(int argc, char **argv) {
    bool read_stdin = false;
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--input") == 0) read_stdin = true;
        else if (strcmp(argv[i], "--max-r") == 0 && i + 1 < argc) {
            int r = atoi(argv[++i]); if (r > 0) MAX_ROWS = r;
        } else if (strcmp(argv[i], "--max-c") == 0 && i + 1 < argc) {
            int c = atoi(argv[++i]); if (c > 0) MAX_COLS = c;
        } else {
            /* ignore unknown */
        }
    }

    demo_operations_interactive(read_stdin);
    return 0;
}
