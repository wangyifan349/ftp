/* chatbot_lcs_utf8_c89.c
   C89 可移植实现：支持 UTF-8（按 Unicode 码点）进行 LCS 计算并按相似度降序排序 QA 候选
   编译示例:
     gcc -std=c89 -pedantic -O2 -o chatbot_lcs_utf8_c89 chatbot_lcs_utf8_c89.c
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h> /* for UINT_MAX */

/* 配置 */
#define MAX_STR 1024
#define TOP_K 5

typedef unsigned long uint32; /* 兼容 C89 的 32 位无符号类型近似（至少 32 位） */

typedef struct {
    char question[MAX_STR];
    char answer[MAX_STR];
} QA;

typedef struct {
    int idx;
    double score;
} ScoreItem;

/* 示例 QA 数据库（UTF-8 文本） */
static QA qa_db[] = {
    {"你好", "你好！有什么可以帮你？"},
    {"你叫什么名字", "我是一个示例聊天机器人。"},
    {"今天天气怎么样", "抱歉，我无法实时获取天气信息。"},
    {"怎么做蛋炒饭", "先把米饭、鸡蛋和配菜准备好，热锅冷油，先炒鸡蛋再下饭……"},
    {"最长公共子序列是什么", "最长公共子序列（LCS）是在两个序列中都出现且保持相对顺序的最长序列。"},
    {"안녕하세요", "안녕하세요! 무엇을 도와드릴까요?"},
    {"이름이 뭐예요", "저는 예시 챗봇입니다."}
};
static const int QA_DB_SIZE = (int)(sizeof(qa_db) / sizeof(qa_db[0]));

/* ---------- UTF-8 解码为 Unicode 码点数组（返回长度或 -1 错误） ----------
   语义：
     - buf: 输入 UTF-8 字节串（以 '\0' 结尾）
     - out: 输出缓冲区，用于存放解码后的码点（uint32），由调用者分配
     - out_capacity: out 的容量（以码点数量计）
   返回：
     - >=0 : 写入 out 的码点数量
     - -1  : 解码错误（非法 UTF-8 序列或容量不足）
   说明：
     - 该实现对 UTF-8 做基本验证（避免过长编码、非法续字节、过小的编码等）
     - 只支持到 Unicode 最大码点 U+10FFFF
*/
static int utf8_decode(const char *buf, uint32 *out, int out_capacity) {
    const unsigned char *s = (const unsigned char *)buf;
    int out_len = 0;
    while (*s) {
        uint32 cp = 0;
        int extra = 0;
        if (*s < 0x80) {
            cp = *s;
            extra = 0;
        } else if ((*s & 0xE0) == 0xC0) {
            cp = *s & 0x1F;
            extra = 1;
            if (cp < 0x2) { /* overlong encoding check: leading byte 0xC0..0xC1 invalid */
                return -1;
            }
        } else if ((*s & 0xF0) == 0xE0) {
            cp = *s & 0x0F;
            extra = 2;
        } else if ((*s & 0xF8) == 0xF0) {
            cp = *s & 0x07;
            extra = 3;
            if (cp > 0x10) return -1; /* > U+10FFFF */
        } else {
            return -1; /* invalid leading byte */
        }

        /* check continuation bytes */
        {
            int i;
            for (i = 1; i <= extra; ++i) {
                unsigned char c = s[i];
                if ((c & 0xC0) != 0x80) return -1;
                cp = (cp << 6) | (c & 0x3F);
            }
            /* Reject overlong sequences and surrogate halves */
            if (cp >= 0xD800 && cp <= 0xDFFF) return -1;
            if (cp > 0x10FFFF) return -1;
            /* Overlong checks:
               For extra==1, minimum cp is 0x80
               For extra==2, minimum cp is 0x800
               For extra==3, minimum cp is 0x10000
            */
            if (extra == 1 && cp < 0x80) return -1;
            if (extra == 2 && cp < 0x800) return -1;
            if (extra == 3 && cp < 0x10000) return -1;
        }

        if (out_len >= out_capacity) return -1; /* insufficient capacity */

        out[out_len++] = cp;
        s += (1 + extra);
    }
    return out_len;
}

/* ---------- LCS（基于码点数组） ----------
   使用动态规划，空间优化为两行。工作在码点数组上。
*/
static int lcs_length_codepoints(const uint32 *a, int an, const uint32 *b, int bn) {
    int i, j;
    if (an == 0 || bn == 0) return 0;

    /* 分配两行 (bn+1) 的 int 数组 */
    int *prev = (int *)calloc((size_t)(bn + 1), sizeof(int));
    int *curr = (int *)calloc((size_t)(bn + 1), sizeof(int));
    if (prev == NULL || curr == NULL) {
        if (prev) free(prev);
        if (curr) free(curr);
        return 0;
    }

    for (i = 1; i <= an; ++i) {
        for (j = 1; j <= bn; ++j) {
            if (a[i - 1] == b[j - 1]) curr[j] = prev[j - 1] + 1;
            else curr[j] = (prev[j] > curr[j - 1]) ? prev[j] : curr[j - 1];
        }
        /* swap and zero curr */
        {
            int *tmp = prev;
            prev = curr;
            curr = tmp;
            memset(curr, 0, (size_t)(bn + 1) * sizeof(int));
        }
    }

    i = prev[bn];
    free(prev);
    free(curr);
    return i;
}

/* 计算两个 UTF-8 字符串的相似度：先解码为码点数组，再计算 LCS_len / max(len1, len2)
   若解码失败（非法 UTF-8 或缓冲不足），按字节回退到简单比较（避免崩溃），
   但通常不会发生因为我们为解码分配了足够缓冲。
*/
static double lcs_similarity_utf8(const char *a, const char *b) {
    /* 估计最大码点数：不超过字节长度 */
    int la = (int)strlen(a);
    int lb = (int)strlen(b);
    if (la == 0 && lb == 0) return 1.0;
    if (la == 0 || lb == 0) return 0.0;

    /* 分配码点缓冲：字节数上限 */
    /* 注意：为安全起见，限制单字符串最大字节数为 MAX_STR-1 */
    if (la >= MAX_STR) la = MAX_STR - 1;
    if (lb >= MAX_STR) lb = MAX_STR - 1;

    /* 最多 MAX_STR-1 个码点（每个码点至少 1 字节） */
    {
        int cap_a = MAX_STR;
        int cap_b = MAX_STR;
        uint32 *cp_a = (uint32 *)malloc((size_t)cap_a * sizeof(uint32));
        uint32 *cp_b = (uint32 *)malloc((size_t)cap_b * sizeof(uint32));
        int an = 0, bn = 0;
        double result = 0.0;
        if (cp_a == NULL || cp_b == NULL) {
            if (cp_a) free(cp_a);
            if (cp_b) free(cp_b);
            return 0.0;
        }

        an = utf8_decode(a, cp_a, cap_a);
        bn = utf8_decode(b, cp_b, cap_b);
        if (an < 0 || bn < 0) {
            /* 解码错误：回退到字节级别的简单相似度（安全退化） */
            int l = 0;
            int i;
            /* 简单 LCS 字节级别（保守实现），但避免再次复杂解码 */
            for (i = 0; a[i] && b[i]; ++i) {
                if (a[i] == b[i]) l++;
            }
            l = l; /* keep l */
            {
                int mx = (int)((strlen(a) > strlen(b)) ? strlen(a) : strlen(b));
                if (mx == 0) result = 1.0;
                else result = (double)l / (double)mx;
            }
            free(cp_a);
            free(cp_b);
            return result;
        }

        /* 计算 LCS */
        {
            int lcs = lcs_length_codepoints(cp_a, an, cp_b, bn);
            int mx = (an > bn) ? an : bn;
            if (mx == 0) result = 1.0;
            else result = (double)lcs / (double)mx;
        }

        free(cp_a);
        free(cp_b);
        return result;
    }
}

/* qsort 比较函数，按 score 降序 */
static int score_cmp_desc(const void *p1, const void *p2) {
    const ScoreItem *a = (const ScoreItem *)p1;
    const ScoreItem *b = (const ScoreItem *)p2;
    if (a->score < b->score) return 1;
    if (a->score > b->score) return -1;
    return 0;
}

/* 排序并返回 top K */
static int rank_answers_by_lcs_utf8(const char *query, ScoreItem out[], int out_size) {
    int n = QA_DB_SIZE;
    int i;
    ScoreItem *scores;

    if (n <= 0) return 0;

    scores = (ScoreItem *)malloc((size_t)n * sizeof(ScoreItem));
    if (scores == NULL) {
        fprintf(stderr, "内存分配失败\n");
        return 0;
    }

    for (i = 0; i < n; ++i) {
        scores[i].idx = i;
        scores[i].score = lcs_similarity_utf8(query, qa_db[i].question);
    }

    qsort(scores, (size_t)n, sizeof(ScoreItem), score_cmp_desc);

    if (out_size > n) out_size = n;
    for (i = 0; i < out_size; ++i) out[i] = scores[i];

    free(scores);
    return out_size;
}

/* 输出响应 */
static void chatbot_response(const char *query, double threshold) {
    ScoreItem top[TOP_K];
    int got = rank_answers_by_lcs_utf8(query, top, TOP_K);
    int i;

    if (got == 0) {
        printf("知识库为空或内部错误。\n");
        return;
    }

    if (top[0].score >= threshold) {
        printf("%s\n", qa_db[top[0].idx].answer);
    } else {
        printf("没有找到高置信度的直接匹配。以下是候选回复（按相似度降序）：\n");
        for (i = 0; i < got; ++i) {
            int qi = top[i].idx;
            printf("问题: %s  (相似度: %.3f) -> 回答: %s\n", qa_db[qi].question, top[i].score, qa_db[qi].answer);
        }
    }
}

/* 安全读取一行并去除换行 */
static char *readline_strip(char *buf, int size) {
    char *p;
    if (fgets(buf, size, stdin) == NULL) return NULL;
    p = buf + strlen(buf);
    if (p != buf) {
        if (*(p - 1) == '\n') *(p - 1) = '\0';
        if ((p - 1) > buf && *(p - 2) == '\r') *(p - 2) = '\0';
    }
    return buf;
}

int main(void) {
    char input[MAX_STR];
    const double threshold = 0.25;

    printf("示例聊天机器人（支持 UTF-8，多语言，中/英/韩，C89 版本）。输入 '退出' 结束。\n");
    while (1) {
        printf("你: ");
        if (readline_strip(input, sizeof(input)) == NULL) break;
        if (strcmp(input, "退出") == 0 || strcmp(input, "quit") == 0 || strcmp(input, "exit") == 0) {
            printf("再见！\n");
            break;
        }
        chatbot_response(input, threshold);
    }
    return 0;
}
