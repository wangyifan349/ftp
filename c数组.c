#include <stdio.h>
#include <stdlib.h>
#include <limits.h> // INT_MIN/INT_MAX
#include <string.h> // memcpy
#include <stdbool.h>

#define MAX_ROWS 100
#define MAX_COLS 100

// 打印二维数组（rows x cols）
void print_matrix(int mat[][MAX_COLS], int rows, int cols) {
    for (int i = 0; i < rows; ++i) {
        for (int j = 0; j < cols; ++j) {
            printf("%6d", mat[i][j]); // 对齐输出
        }
        printf("\n");
    }
}

// 将矩阵全部赋为某个值
void fill_matrix(int mat[][MAX_COLS], int rows, int cols, int val) {
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            mat[i][j] = val;
}

// 从标准输入读取矩阵（按行）
void input_matrix(int mat[][MAX_COLS], int rows, int cols) {
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            scanf("%d", &mat[i][j]);
}

// 计算每一行的和，结果写入 row_sums（长度为 rows）
void row_sums(int mat[][MAX_COLS], int rows, int cols, int row_sums_out[]) {
    for (int i = 0; i < rows; ++i) {
        int s = 0;
        for (int j = 0; j < cols; ++j) s += mat[i][j];
        row_sums_out[i] = s;
    }
}

// 计算每一列的和，结果写入 col_sums（长度为 cols）
void col_sums(int mat[][MAX_COLS], int rows, int cols, int col_sums_out[]) {
    for (int j = 0; j < cols; ++j) {
        int s = 0;
        for (int i = 0; i < rows; ++i) s += mat[i][j];
        col_sums_out[j] = s;
    }
}

// 原地转置方阵（仅当 rows==cols 时有效）
bool transpose_square(int mat[][MAX_COLS], int n) {
    if (n <= 0) return false;
    for (int i = 0; i < n; ++i) {
        for (int j = i + 1; j < n; ++j) {
            int tmp = mat[i][j];
            mat[i][j] = mat[j][i];
            mat[j][i] = tmp;
        }
    }
    return true;
}

// 将矩阵 src 转置到 dest（支持非方阵），要求 dest 已有正确尺寸
void transpose_to(int src[][MAX_COLS], int rows, int cols, int dest[][MAX_COLS]) {
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            dest[j][i] = src[i][j];
}

// 查找最大值及其位置（若多个返回第一个遇到的）
void find_max(int mat[][MAX_COLS], int rows, int cols, int *max_val, int *max_i, int *max_j) {
    int mv = INT_MIN, mi = -1, mj = -1;
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            if (mat[i][j] > mv) {
                mv = mat[i][j];
                mi = i; mj = j;
            }
    *max_val = mv; *max_i = mi; *max_j = mj;
}

// 查找最小值及其位置
void find_min(int mat[][MAX_COLS], int rows, int cols, int *min_val, int *min_i, int *min_j) {
    int mv = INT_MAX, mi = -1, mj = -1;
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            if (mat[i][j] < mv) {
                mv = mat[i][j];
                mi = i; mj = j;
            }
    *min_val = mv; *min_i = mi; *min_j = mj;
}

// 在矩阵中查找某个值，返回出现次数并把第一个位置通过指针返回（若未找到返回0，位置置为 -1）
int find_value(int mat[][MAX_COLS], int rows, int cols, int value, int *first_i, int *first_j) {
    int count = 0;
    *first_i = -1; *first_j = -1;
    for (int i = 0; i < rows; ++i) {
        for (int j = 0; j < cols; ++j) {
            if (mat[i][j] == value) {
                if (count == 0) { *first_i = i; *first_j = j; }
                count++;
            }
        }
    }
    return count;
}

// 矩阵相加：要求尺寸相同，结果写入 res。返回 true 表示成功。
bool add_matrix(int a[][MAX_COLS], int b[][MAX_COLS], int rows, int cols, int res[][MAX_COLS]) {
    if (rows <= 0 || cols <= 0) return false;
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            res[i][j] = a[i][j] + b[i][j];
    return true;
}

// 矩阵乘法：a (r1 x c1) * b (r2 x c2) 要求 c1 == r2，结果写入 res (r1 x c2)
// 返回 true 表示成功
bool multiply_matrix(int a[][MAX_COLS], int r1, int c1, int b[][MAX_COLS], int r2, int c2, int res[][MAX_COLS]) {
    if (c1 != r2) return false;
    for (int i = 0; i < r1; ++i) {
        for (int j = 0; j < c2; ++j) {
            long long sum = 0; // 防止中间溢出
            for (int k = 0; k < c1; ++k) {
                sum += (long long)a[i][k] * b[k][j];
            }
            res[i][j] = (int)sum;
        }
    }
    return true;
}

// 对每一行进行升序排序（使用简单的插入排序）
void sort_rows_asc(int mat[][MAX_COLS], int rows, int cols) {
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
}

// 复制矩阵（rows x cols）
void copy_matrix(int src[][MAX_COLS], int dest[][MAX_COLS], int rows, int cols) {
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            dest[i][j] = src[i][j];
}

// 演示/测试函数：对操作逐步打印并解释
void demo_operations() {
    int a[MAX_ROWS][MAX_COLS];
    int b[MAX_ROWS][MAX_COLS];
    int c[MAX_ROWS][MAX_COLS];
    int t[MAX_ROWS][MAX_COLS];
    int res[MAX_ROWS][MAX_COLS];
    int rows = 3, cols = 4;

    // 初始样例矩阵 A
    int sample[3][4] = {
        {3, 1, 4, 2},
        {5, 6, 1, 0},
        {9, 7, 8, -1}
    };
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            a[i][j] = sample[i][j];

    printf("=== 初始矩阵 A ===\n");
    print_matrix(a, rows, cols);
    printf("\n");

    // 按行求和并打印每一步
    int rs[MAX_ROWS];
    row_sums(a, rows, cols, rs);
    printf("每行和 (row_sums):\n");
    for (int i = 0; i < rows; ++i)
        printf("row %d sum = %d\n", i, rs[i]);
    printf("\n");

    // 按列求和
    int cs[MAX_COLS];
    col_sums(a, rows, cols, cs);
    printf("每列和 (col_sums):\n");
    for (int j = 0; j < cols; ++j)
        printf("col %d sum = %d\n", j, cs[j]);
    printf("\n");

    // 查找最大/最小并打印位置
    int maxv, max_i, max_j, minv, min_i, min_j;
    find_max(a, rows, cols, &maxv, &max_i, &max_j);
    find_min(a, rows, cols, &minv, &min_i, &min_j);
    printf("最大值: %d at (%d,%d)\n", maxv, max_i, max_j);
    printf("最小值: %d at (%d,%d)\n\n", minv, min_i, min_j);

    // 查找某个值（示例：1）
    int target = 1;
    int first_i, first_j;
    int cnt = find_value(a, rows, cols, target, &first_i, &first_j);
    if (cnt > 0)
        printf("值 %d 出现 %d 次，第一次出现在 (%d,%d)\n\n", target, cnt, first_i, first_j);
    else
        printf("值 %d 未找到\n\n", target);

    // 转置到 T 并打印
    transpose_to(a, rows, cols, t);
    printf("A 的转置 T (尺寸 %dx%d):\n", cols, rows);
    print_matrix(t, cols, rows);
    printf("\n");

    // 复制 A 到 B，然后对 B 做修改以演示 add 的结果差异
    copy_matrix(a, b, rows, cols);
    // 修改 b：在每个元素上加 10（演示用）
    for (int i = 0; i < rows; ++i)
        for (int j = 0; j < cols; ++j)
            b[i][j] += 10;
    printf("矩阵 B (由 A 复制并每项 +10):\n");
    print_matrix(b, rows, cols);
    printf("\n");

    // A + B -> C
    add_matrix(a, b, rows, cols, c);
    printf("C = A + B:\n");
    print_matrix(c, rows, cols);
    printf("\n");

    // 矩阵乘法示例：A (3x4) * T (4x3) = res (3x3)
    if (multiply_matrix(a, rows, cols, t, cols, rows, res)) {
        printf("res = A * T (A * A^T) (尺寸 %dx%d):\n", rows, rows);
        print_matrix(res, rows, rows);
    } else {
        printf("矩阵乘法尺寸不匹配，无法计算。\n");
    }
    printf("\n");

    // 对 A 每行排序前后对比
    printf("A 原始（用于排序前）:\n");
    print_matrix(a, rows, cols);
    printf("\n");

    sort_rows_asc(a, rows, cols);
    printf("A 每行升序排序后:\n");
    print_matrix(a, rows, cols);
    printf("\n");

    // 将排序后的 A 再转置并打印，展示连续操作
    transpose_to(a, rows, cols, t);
    printf("排序后 A 的转置 T:\n");
    print_matrix(t, cols, rows);
    printf("\n");

    // 填充一个矩阵（示例：全部填 7）并打印
    fill_matrix(res, rows, rows, 7); // 重用 res 存放方阵
    printf("res（全部填充为 7 的 %dx%d 方阵示例）:\n", rows, rows);
    print_matrix(res, rows, rows);
    printf("\n");
}

int main(void) {
    demo_operations();
    return 0;
}
