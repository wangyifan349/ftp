/* finance_stats.c
 * 简易理财统计工具
 * 编译示例: gcc -std=c99 -Wall -Wextra -o finance_stats finance_stats.c
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define MAX_ITEMS 1000   // 最多支持的记录数
/* ---------- 工具函数 ---------- */
/* 交换两个 double */
static void swap(double *a, double *b) {
    double t = *a;
    *a = *b;
    *b = t;
}
/* 简单的快速排序（升序） */
static void quicksort(double arr[], int left, int count) {
    if (count > 1) {
        double pivot = arr[left + count / 2];
        int i = left;
        int j = left + count - 1;
        while (i <= j) {
            while (arr[i] < pivot) i++;
            while (arr[j] > pivot) j--;
            if (i <= j) {
                swap(&arr[i], &arr[j]);
                i++; j--;
            }
        }
        if (j - left + 1 > 0) quicksort(arr, left, j - left + 1);
        if (left + count - i > 0) quicksort(arr, i, left + count - i);
    }
}
/* 计算中位数（已排序数组） */
static double median(double data[], int n) {
    if (n % 2 == 1) {
        return data[n / 2];
    } else {
        return (data[n / 2 - 1] + data[n / 2]) / 2.0;
    }
}
/* 计算众数（返回众数数量，存入 modes[]） */
static int mode(double data[], int n, double modes[], int max_modes) {
    int i, cur_cnt = 1, max_cnt = 1, mode_cnt = 0;
    for (i = 1; i < n; ++i) {
        if (fabs(data[i] - data[i-1]) < 1e-9) {
            cur_cnt++;
        } else {
            if (cur_cnt > max_cnt) {
                max_cnt = cur_cnt;
                mode_cnt = 0;
                modes[mode_cnt++] = data[i-1];
            } else if (cur_cnt == max_cnt) {
                if (mode_cnt < max_modes) modes[mode_cnt++] = data[i-1];
            }
            cur_cnt = 1;
        }
    }
    /* 处理最后一段 */
    if (cur_cnt > max_cnt) {
        max_cnt = cur_cnt;
        mode_cnt = 0;
        modes[mode_cnt++] = data[n-1];
    } else if (cur_cnt == max_cnt) {
        if (mode_cnt < max_modes) modes[mode_cnt++] = data[n-1];
    }
    /* 若所有数出现次数相同，则视为“无众数” */
    if (max_cnt == 1) return 0;
    return mode_cnt;
}
/* ---------- 主功能 ---------- */
int main(void) {
    double amounts[MAX_ITEMS];
    int count = 0;
    int running = 1;
    while (running) {
        printf("\n=== 理财统计工具 ===\n");
        printf("1. 添加金额记录\n");
        printf("2. 查看统计信息\n");
        printf("3. 显示所有记录（升序）\n");
        printf("4. 显示所有记录（降序）\n");
        printf("5. 清空所有记录\n");
        printf("0. 退出\n");
        printf("请选择: ");
        int choice;
        if (scanf("%d", &choice) != 1) {
            while (getchar()!='\n'); // 清除错误输入
            continue;
        }
        switch (choice) {
            case 1: {
                if (count >= MAX_ITEMS) {
                    printf("已达最大记录数 (%d)。\n", MAX_ITEMS);
                    break;
                }
                double val;
                printf("请输入金额（正数或负数，支持小数）: ");
                if (scanf("%lf", &val) == 0) {
                    while (getchar()!='\n');
                    printf("输入无效。\n");
                } else {
                    amounts[count++] = val;
                    printf("已记录第 %d 条金额。\n", count);
                }
                break;
            }
            case 2: {
                if (count == 0) {
                    printf("暂无数据。\n");
                    break;
                }
                double sum = 0, min = amounts[0], max = amounts[0];
                for (int i = 0; i < count; ++i) {
                    sum += amounts[i];
                    if (amounts[i] < min) min = amounts[i];
                    if (amounts[i] > max) max = amounts[i];
                }
                double avg = sum / count;
                /* 为统计中位数、众数复制并排序 */
                double sorted[MAX_ITEMS];
                memcpy(sorted, amounts, count * sizeof(double));
                quicksort(sorted, 0, count);
                double med = median(sorted, count);
                double modes[10];
                int mode_num = mode(sorted, count, modes, 10);
                printf("\n--- 统计结果 ---\n");
                printf("记录数: %d\n", count);
                printf("总和: %.2f\n", sum);
                printf("平均: %.2f\n", avg);
                printf("最小: %.2f\n", min);
                printf("最大: %.2f\n", max);
                printf("中位数: %.2f\n", med);
                if (mode_num == 0) {
                    printf("众数: 无（所有数出现次数相同）\n");
                } else {
                    printf("众数 (%d 个): ", mode_num);
                    for (int i = 0; i < mode_num; ++i) {
                        printf("%.2f ", modes[i]);
                    }
                    printf("\n");
                }
                break;
            }
            case 3: {
                if (count == 0) { printf("暂无数据。\n"); break; }
                double sorted[MAX_ITEMS];
                memcpy(sorted, amounts, count * sizeof(double));
                quicksort(sorted, 0, count);
                printf("\n--- 所有记录（升序） ---\n");
                for (int i = 0; i < count; ++i) {
                    printf("%.2f ", sorted[i]);
                }
                printf("\n");
                break;
            }
            case 4: {
                if (count == 0) { printf("暂无数据。\n"); break; }
                double sorted[MAX_ITEMS];
                memcpy(sorted, amounts, count * sizeof(double));
                quicksort(sorted, 0, count);
                printf("\n--- 所有记录（降序） ---\n");
                for (int i = count-1; i >= 0; --i) {
                    printf("%.2f ", sorted[i]);
                }
                printf("\n");
                break;
            }
            case 5: {
                count = 0;
                printf("已清空所有记录。\n");
                break;
            }
            case 0:
                running = 0;
                break;
            default:
                printf("无效选项，请重新输入。\n");
        }
    }
    printf("感谢使用，再见！\n");
    return 0;
}
