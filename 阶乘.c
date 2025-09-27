#include <stdio.h>

int main(void) {
    unsigned long long fact = 1;
    unsigned long long sum = 0;

    printf("n  n! (unsigned long long)        Sk = 1 + 2! + ... + n!\n");
    printf("---------------------------------------------------------\n");

    // 对于 n=1 单独处理：题目首项为单独的 1（既视作1或1!均为1）
    for (int n = 1; n <= 20; ++n) {
        if (n == 1) {
            fact = 1;           // 1! = 1
        } else {
            fact *= (unsigned long long)n; // 逐步计算 n!
        }
        sum += fact;            // 累加到 Sk

        // 输出 n, n!, Sk
        printf("%2d  %20llu  %20llu\n", n, fact, sum);
    }

    // 最终汇总
    printf("---------------------------------------------------------\n");
    printf("Final: 20! = %llu\n", fact);
    printf("Final: S = 1 + 2! + ... + 20! = %llu\n", sum);

    // 另外用 double 计算以便观察精度差异
    double dfact = 1.0;
    double dsum = 0.0;
    for (int n = 1; n <= 20; ++n) {
        if (n == 1) dfact = 1.0;
        else dfact *= (double)n;
        dsum += dfact;
    }
    printf("Double approximation: S_double = %.0f\n", dsum);
    printf("Double 20! approx = %.0f\n", dfact);

    return 0;
}
