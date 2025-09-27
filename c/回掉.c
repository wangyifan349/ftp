#include <stdio.h>

/* 二元操作函数类型：接受两个 int，返回 int */
typedef int (*binop_t)(int, int);

/* 几个示例二元操作 */
int op_max(int x, int y) { return x > y ? x : y; }
int op_min(int x, int y) { return x < y ? x : y; }
int op_add(int x, int y) { return x + y; }
int op_mul(int x, int y) { return x * y; }

/* 将二元操作扩展到三个数：等价于 op(op(a,b),c) */
int apply_to_three(binop_t op, int a, int b, int c) {
    return op(op(a, b), c);
}

int main(void) {
    int a, b, c;
    int result;
    binop_t p; /* 函数指针 */

    printf("请输入三个整数（以空格分隔）：");
    if (scanf("%d %d %d", &a, &b, &c) != 3) {
        printf("输入错误\n");
        return 1;
    }

    /* 演示：用不同的函数指针调用同一逻辑 */
    p = op_max;
    result = apply_to_three(p, a, b, c);
    printf("最大值: %d\n", result);

    p = op_min;
    result = apply_to_three(p, a, b, c);
    printf("最小值: %d\n", result);

    p = op_add;
    result = apply_to_three(p, a, b, c);
    printf("按 ((a+b)+c) 相加的结果: %d\n", result);

    p = op_mul;
    result = apply_to_three(p, a, b, c);
    printf("按 ((a*b)*c) 相乘的结果: %d\n", result);

    return 0;
}
