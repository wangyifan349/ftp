/* single_file.c  -- 兼容 C89 的示例程序，含完整注释
 *
 * 功能：
 *  - 安全内存分配（xmalloc/xcalloc/xrealloc）
 *  - 阶乘（迭代，溢出检测）
 *  - 斐波那契（迭代 + 记忆化/自底向上，溢出检测）
 *  - 二分查找（迭代）
 *  - 归并排序（递归，使用一次性辅助数组）
 *  - 快速排序（原地，递归/循环混合以限制栈深度）
 *  - 二叉树：创建、递归释放、递归与迭代中序遍历（动态栈）
 *
 * 备注：
 *  - 代码尽量避免 C99/C11 特性，变量在块开始处声明，使用 /* ... */ 注释。
 *  - xmalloc/xcalloc/xrealloc 在分配失败时会打印错误并 exit(EXIT_FAILURE)。
 *  - 溢出检测为简单策略，适合教学与常规用途；若需严谨大整数请使用专门库。
 */

#include <stdio.h>
#include <stdlib.h>
#include <limits.h>

/* ----------------------------
   安全内存分配封装（C89 风格）
   ---------------------------- */

/* xmalloc: 分配 n 字节，失败时打印错误并退出。
   返回指针（非 NULL）或 NULL（当 n==0 时）。 */
void *xmalloc(size_t n) {
    void *p;
    if (n == 0) return NULL; /* 请求 0 字节，返回 NULL（调用者需注意） */
    p = malloc(n);
    if (!p) {
        fprintf(stderr, "内存分配失败 (%lu bytes)\n", (unsigned long)n);
        exit(EXIT_FAILURE);
    }
    return p;
}

/* xcalloc: 分配 nmemb * size 字节并置零，失败时打印并退出。
   返回指针或 NULL（当 nmemb==0 或 size==0 时）。 */
void *xcalloc(size_t nmemb, size_t size) {
    void *p;
    if (nmemb == 0 || size == 0) return NULL;
    p = calloc(nmemb, size);
    if (!p) {
        fprintf(stderr, "内存分配失败 (calloc)\n");
        exit(EXIT_FAILURE);
    }
    return p;
}

/* xrealloc: 重新分配内存块，失败时打印并退出。
   若 size==0 返回 NULL（与 realloc 行为稍不同：简化处理）。 */
void *xrealloc(void *ptr, size_t size) {
    void *p;
    if (size == 0) return NULL;
    p = realloc(ptr, size);
    if (!p) {
        fprintf(stderr, "内存重新分配失败 (%lu bytes)\n", (unsigned long)size);
        exit(EXIT_FAILURE);
    }
    return p;
}

/* ----------------------------
   1) 阶乘（迭代实现）
   ---------------------------- */

/* factorial_iter:
   - 输入 n（int），返回 n!（long long）。
   - 若 n < 0 或计算过程中检测到溢出，返回 -1 表示错误/不可表示。
   - 使用 LLONG_MAX 做简单溢出检测：在乘之前检查 res > LLONG_MAX / i。 */
long long factorial_iter(int n) {
    long long res;
    int i;
    if (n < 0) return -1; /* 负数阶乘未定义（整数版本） */
    res = 1LL;
    for (i = 2; i <= n; ++i) {
        /* 溢出检测：若 res * i > LLONG_MAX 则溢出 */
        if (res > LLONG_MAX / i) {
            return -1;
        }
        res *= i;
    }
    return res;
}

/* ----------------------------
   2) 斐波那契（迭代与记忆化）
   ---------------------------- */

/* fib_iter:
   - 迭代计算第 n 个斐波那契数（0-based: fib(0)=0, fib(1)=1）。
   - 若 n < 0 返回 -1。若检测到溢出返回 -1（简单溢出检测：next < previous）。
*/
long long fib_iter(int n) {
    long long a, b, next;
    int i;
    if (n < 0) return -1;
    if (n <= 1) return (long long)n;
    a = 0LL;
    b = 1LL;
    for (i = 2; i <= n; ++i) {
        next = a + b;
        /* 简单溢出检测：若 next < b 则发生了环绕（溢出） */
        if (next < b) return -1;
        a = b;
        b = next;
    }
    return b;
}

/* fib_memo:
   - 使用自底向上的记忆化数组计算 fib(n)。
   - 分配 (n+1) 个 long long 存放结果；若分配失败，xcalloc 已经 exit。
   - 使用 LLONG_MIN 作为"未初始化"标记（不会作为合法斐波那契值）。
   - 溢出检测为：如果新值 < 前一项，则视为溢出。
*/
long long fib_memo(int n) {
    long long *memo;
    int i;
    long long res;
    if (n < 0) return -1;
    /* 分配 n+1 个元素（注意转换为 size_t） */
    memo = (long long *) xcalloc((size_t)(n + 1), sizeof(long long));
    if (!memo) return -1; /* 理论上 xcalloc 失败会 exit，这里是冗余检查 */
    /* 初始化为不可用标记 */
    for (i = 0; i <= n; ++i) memo[i] = LLONG_MIN;
    /* 基础值 */
    memo[0] = 0LL;
    if (n >= 1) memo[1] = 1LL;
    /* 自底向上填表 */
    for (i = 2; i <= n; ++i) {
        if (memo[i-1] == LLONG_MIN || memo[i-2] == LLONG_MIN) {
            free(memo);
            return -1;
        }
        memo[i] = memo[i-1] + memo[i-2];
        /* 溢出检测 */
        if (memo[i] < memo[i-1]) {
            free(memo);
            return -1;
        }
    }
    res = memo[n];
    free(memo);
    return res;
}

/* ----------------------------
   3) 二分查找（迭代）
   ---------------------------- */

/* binary_search_iter:
   - 在升序数组 arr（长度 n）中查找 target。
   - 返回找到的索引（int），找不到返回 -1。
   - 使用区间 [lo, hi) 的风格，避免 hi 溢出问题。 */
int binary_search_iter(const int arr[], unsigned int n, int target) {
    unsigned int lo, hi, mid;
    lo = 0;
    hi = n; /* 半开区间 [lo, hi) */
    while (lo < hi) {
        mid = lo + (hi - lo) / 2;
        if (arr[mid] == target) return (int)mid;
        if (arr[mid] < target) lo = mid + 1;
        else hi = mid;
    }
    return -1;
}

/* ----------------------------
   4) 归并排序（递归 + 一次性辅助数组）
   ---------------------------- */

/* merge_range:
   - 将 arr[l..m-1] 与 arr[m..r-1] 合并到 aux[l..r-1]，然后复制回 arr[l..r-1]。
   - 使用半开区间 [l, m) 和 [m, r)。这种区间表示减少 off-by-one 错误。 */
void merge_range(int arr[], int aux[], unsigned int l, unsigned int m, unsigned int r) {
    unsigned int i, j, k;
    i = l; j = m; k = l;
    while (i < m && j < r) {
        if (arr[i] <= arr[j]) aux[k++] = arr[i++];
        else aux[k++] = arr[j++];
    }
    while (i < m) aux[k++] = arr[i++];
    while (j < r) aux[k++] = arr[j++];
    /* 复制回原数组 */
    for (k = l; k < r; ++k) arr[k] = aux[k];
}

/* merge_sort_recursive:
   - 递归地排序区间 [l, r)（半开），当区间大小 <=1 时返回。
   - 使用外部传入的 aux 数组，避免每次递归重复分配内存。 */
void merge_sort_recursive(int arr[], int aux[], unsigned int l, unsigned int r) {
    unsigned int m;
    if (r - l <= 1) return; /* 已有序或只有一个元素 */
    m = l + (r - l) / 2;
    merge_sort_recursive(arr, aux, l, m);
    merge_sort_recursive(arr, aux, m, r);
    merge_range(arr, aux, l, m, r);
}

/* merge_sort:
   - 对长度为 n 的数组 arr 进行归并排序。
   - 分配一次性辅助数组 aux（大小 n），调用递归函数，结束后释放 aux。 */
int merge_sort(int arr[], unsigned int n) {
    int *aux;
    if (!arr || n <= 1) return 0;
    aux = (int *) xmalloc((size_t)n * sizeof(int));
    merge_sort_recursive(arr, aux, 0, n);
    free(aux);
    return 0;
}

/* ----------------------------
   5) 快速排序（原地，递归/循环混合）
   ---------------------------- */

/* quick_sort_recursive:
   - 原地排序 arr[lo..hi]（闭区间）。
   - 选取中间元素为 pivot（简单、降低最坏情况概率）。
   - 内部使用 while 循环 + 递归处理较小一侧，循环处理另一侧，目的是限制递归深度（尾递归优化思路）。 */
static void quick_sort_recursive(int arr[], int lo, int hi) {
    int pivot, i, j, t;
    while (lo < hi) {
        pivot = arr[lo + (hi - lo) / 2]; /* 选取中间元素作为 pivot */
        i = lo; j = hi;
        /* 双指针划分 */
        while (i <= j) {
            while (arr[i] < pivot) ++i;
            while (arr[j] > pivot) --j;
            if (i <= j) {
                t = arr[i]; arr[i] = arr[j]; arr[j] = t;
                ++i; --j;
            }
        }
        /* 递归处理较小的一侧，以限制栈深度 */
        if (j - lo < hi - i) {
            if (lo < j) quick_sort_recursive(arr, lo, j);
            lo = i; /* 循环继续处理右侧 */
        } else {
            if (i < hi) quick_sort_recursive(arr, i, hi);
            hi = j; /* 循环继续处理左侧 */
        }
    }
}

/* quick_sort:
   - 对长度为 n 的数组 arr 进行快速排序（封装函数）。
   - 将 unsigned int n 转为闭区间 hi = (int)n - 1 传入递归。 */
void quick_sort(int arr[], unsigned int n) {
    if (!arr || n <= 1) return;
    quick_sort_recursive(arr, 0, (int)n - 1);
}

/* ----------------------------
   6) 二叉树：节点、创建、释放、遍历（递归与迭代）
   ---------------------------- */

/* 二叉树节点定义 */
typedef struct Node {
    int val;
    struct Node *left;
    struct Node *right;
} Node;

/* node_new:
   - 分配并初始化一个新节点，值为 v，左右子节点置 NULL。
   - xmalloc 在失败时会 exit，因此这里无需额外错误检查。 */
Node *node_new(int v) {
    Node *n;
    n = (Node *) xmalloc(sizeof(Node));
    n->val = v;
    n->left = n->right = NULL;
    return n;
}

/* node_free:
   - 递归释放整棵树（后序遍历释放左右再释放根）。
   - 采用保存左右指针后 free(root) 的方式，以避免在 free 后引用已经释放的内存。 */
void node_free(Node *root) {
    Node *left, *right;
    if (!root) return;
    left = root->left;
    right = root->right;
    free(root);
    node_free(left);
    node_free(right);
}

/* inorder_recursive:
   - 递归中序遍历并打印节点值（左-根-右）。 */
void inorder_recursive(const Node *root) {
    if (!root) return;
    inorder_recursive(root->left);
    printf("%d ", root->val);
    inorder_recursive(root->right);
}

/* 动态栈结构：用于迭代中序遍历，避免固定大小栈 */
typedef struct {
    Node **data;            /* 指向 Node* 的动态数组 */
    unsigned int size;      /* 当前元素个数 */
    unsigned int cap;       /* 容量 */
} NodeStack;

/* stack_init: 初始化栈，初始容量 16 */
void stack_init(NodeStack *s) {
    s->cap = 16;
    s->size = 0;
    s->data = (Node **) xmalloc((size_t)s->cap * sizeof(Node *));
}

/* stack_push: 推入元素，若超容量则扩容（xrealloc 会在失败时 exit） */
void stack_push(NodeStack *s, Node *n) {
    if (s->size == s->cap) {
        s->cap *= 2;
        s->data = (Node **) xrealloc(s->data, (size_t)s->cap * sizeof(Node *));
    }
    s->data[s->size++] = n;
}

/* stack_pop: 弹出并返回栈顶元素，空栈返回 NULL（调用者需检查） */
Node *stack_pop(NodeStack *s) {
    if (s->size == 0) return NULL;
    s->size--;
    return s->data[s->size];
}

/* stack_empty: 是否为空 */
int stack_empty(const NodeStack *s) {
    return s->size == 0;
}

/* stack_free: 释放栈内部数组 */
void stack_free(NodeStack *s) {
    free(s->data);
    s->data = NULL;
    s->size = s->cap = 0;
}

/* inorder_iterative:
   - 迭代中序遍历实现，使用动态栈模拟递归。
   - 算法：从根开始，不断向左走并将节点压栈；当不能再左走时弹出栈顶并访问，然后转向右子树。 */
void inorder_iterative(const Node *root) {
    NodeStack st;
    const Node *cur;
    stack_init(&st);
    cur = root;
    while (cur || !stack_empty(&st)) {
        while (cur) {
            /* 强制类型转换是因为栈元素类型为 Node*，而 cur 是 const Node* */
            stack_push(&st, (Node *)cur);
            cur = cur->left;
        }
        cur = stack_pop(&st);
        if (!cur) break;
        printf("%d ", cur->val);
        cur = cur->right;
    }
    stack_free(&st);
}

/* ----------------------------
   7) 辅助输入与主程序示例（C89 风格）
   ---------------------------- */

/* safe_scan_int:
   - 读取一个整数到 out，失败时清理输入缓冲并返回 0，否则返回 1。 */
int safe_scan_int(int *out) {
    int c;
    if (!out) return 0;
    if (scanf("%d", out) != 1) {
        /* 清空当前行输入，避免残留影响后续输入 */
        while ((c = getchar()) != EOF && c != '\n') ;
        return 0;
    }
    return 1;
}

/* main: 演示各功能的基本测试/示例 */
int main(void) {
    int arr[] = {5,2,9,1,5,6};
    unsigned int n = sizeof(arr)/sizeof(arr[0]);
    int *copy1;
    int *copy2;
    long long f;
    long long fm;
    int idx;
    Node *root;
    {
        unsigned int i;
        /* 为排序分配工作数组并复制初始数据 */
        copy1 = (int *) xmalloc((size_t)n * sizeof(int));
        copy2 = (int *) xmalloc((size_t)n * sizeof(int));
        for (i = 0; i < n; ++i) {
            copy1[i] = arr[i];
            copy2[i] = arr[i];
        }
    }

    /* 归并排序 */
    merge_sort(copy1, n);
    /* 快速排序 */
    quick_sort(copy2, n);

    /* 输出排序结果 */
    printf("merge_sort result: ");
    {
        unsigned int i;
        for (i = 0; i < n; ++i) printf("%d ", copy1[i]);
    }
    printf("\nquick_sort result: ");
    {
        unsigned int i;
        for (i = 0; i < n; ++i) printf("%d ", copy2[i]);
    }
    printf("\n");

    free(copy1);
    free(copy2);

    /* 阶乘示例（20! 在 long long 中可能溢出，函数会检测溢出） */
    f = factorial_iter(20);
    if (f < 0) printf("factorial(20) 溢出或无效\n");
    else printf("factorial(20) = %lld\n", f);

    /* 斐波那契示例（带记忆化） */
    fm = fib_memo(50);
    if (fm < 0) printf("fib(50) 溢出或无效\n");
    else printf("fib(50) = %lld\n", fm);

    /* 构造一棵简单二叉树用于遍历示例 */
    root = node_new(4);
    root->left = node_new(2);
    root->right = node_new(6);
    root->left->left = node_new(1);
    root->left->right = node_new(3);

    printf("inorder_recursive: ");
    inorder_recursive(root);
    printf("\ninorder_iterative: ");
    inorder_iterative(root);
    printf("\n");

    /* 释放二叉树内存 */
    node_free(root);

    /* 二分查找示例 */
    {
        int sorted[] = {1,3,5,7,9,11};
        unsigned int sorted_n = sizeof(sorted)/sizeof(sorted[0]);
        idx = binary_search_iter(sorted, sorted_n, 7);
        printf("index of 7 = %d\n", idx);
    }

    return 0;
}
