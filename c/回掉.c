#include <stdio.h>
#include <stdlib.h>

/* 二元操作函数类型：接受两个 int，返回 int */
typedef int (*binop_t)(int, int);

/* 几个示例二元操作 */
int op_max(int x, int y) { return x > y ? x : y; }
int op_min(int x, int y) { return x < y ? x : y; }
int op_add(int x, int y) { return x + y; }
int op_sub(int x, int y) { return x - y; }
int op_mul(int x, int y) { return x * y; }
int op_div(int x, int y) {
    if (y == 0) {
        printf("错误：除数不能为零！\n");
        exit(1);  // 退出程序
    }
    return x / y;
}
int op_mod(int x, int y) {
    if (y == 0) {
        printf("错误：除数不能为零！\n");
        exit(1);  // 退出程序
    }
    return x % y;
}

/* 将二元操作扩展到三个数：等价于 op(op(a,b),c) */
int apply_to_three(binop_t op, int a, int b, int c) {
    return op(op(a, b), c);
}

void print_menu() {
    printf("请选择一个操作：\n");
    printf("1. 最大值\n");
    printf("2. 最小值\n");
    printf("3. 加法\n");
    printf("4. 减法\n");
    printf("5. 乘法\n");
    printf("6. 除法\n");
    printf("7. 取模\n");
}

int main(void) {
    int a, b, c;
    int result;
    binop_t p;  /* 函数指针 */
    int choice;

    printf("请输入三个整数（以空格分隔）：");
    if (scanf("%d %d %d", &a, &b, &c) != 3) {
        printf("输入错误：请输入三个整数！\n");
        return 1;
    }

    print_menu();
    if (scanf("%d", &choice) != 1 || choice < 1 || choice > 7) {
        printf("输入错误：请选择一个有效的操作选项！\n");
        return 1;
    }

    /* 根据用户选择设置操作符 */
    switch (choice) {
        case 1:  /* 最大值 */
            p = op_max;
            printf("计算结果：最大值 = %d\n", apply_to_three(p, a, b, c));
            break;
        case 2:  /* 最小值 */
            p = op_min;
            printf("计算结果：最小值 = %d\n", apply_to_three(p, a, b, c));
            break;
        case 3:  /* 加法 */
            p = op_add;
            printf("计算结果：加法 = %d\n", apply_to_three(p, a, b, c));
            break;
        case 4:  /* 减法 */
            p = op_sub;
            printf("计算结果：减法 = %d\n", apply_to_three(p, a, b, c));
            break;
        case 5:  /* 乘法 */
            p = op_mul;
            printf("计算结果：乘法 = %d\n", apply_to_three(p, a, b, c));
            break;
        case 6:  /* 除法 */
            p = op_div;
            printf("计算结果：除法 = %d\n", apply_to_three(p, a, b, c));
            break;
        case 7:  /* 取模 */
            p = op_mod;
            printf("计算结果：取模 = %d\n", apply_to_three(p, a, b, c));
            break;
        default:
            printf("无效操作！\n");
            return 1;
    }

    return 0;
}
