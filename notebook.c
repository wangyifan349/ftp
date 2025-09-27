/* notebook.c
   简易命令行记事本（尽量兼容 C89/C90）
   功能：new/open/save/show/append/insert/delete/find/replace/exit/help
   编译示例：gcc -std=c89 -O2 -o notebook notebook.c
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

/* 可调整参数 */
#define INITIAL_CAPACITY 128
#define READ_CHUNK 256
#define CMD_BUF 256

/* Document 结构 */
typedef struct {
    char **lines;
    size_t size;
    size_t capacity;
    char *filename;
    int modified;
} Document;

/* 辅助：安全 strdup（C89 中可能没有 strdup） */
static char *xstrdup(const char *s) {
    char *p;
    size_t n;
    if (!s) return NULL;
    n = strlen(s) + 1;
    p = (char*)malloc(n);
    if (!p) return NULL;
    memcpy(p, s, n);
    return p;
}

/* 读取任意长行（不包含尾部换行），返回 malloc 缓冲或 NULL (EOF/错误) */
static char *readline_alloc(FILE *fp) {
    char *buf;
    size_t cap, len;
    int ch;
    cap = READ_CHUNK;
    buf = (char*)malloc(cap);
    if (!buf) return NULL;
    len = 0;
    while (1) {
        ch = fgetc(fp);
        if (ch == EOF) break;
        if (ch == '\r') {
            /* 处理可能的 \r\n：peek 下一个 */
            int nxt = fgetc(fp);
            if (nxt != '\n' && nxt != EOF) ungetc(nxt, fp);
            break;
        }
        if (ch == '\n') break;
        if (len + 1 >= cap) {
            char *nb;
            cap = cap * 2;
            nb = (char*)realloc(buf, cap);
            if (!nb) { free(buf); return NULL; }
            buf = nb;
        }
        buf[len++] = (char)ch;
    }
    if (len == 0 && feof(fp) && ferror(fp) == 0 && ftell(fp) == 0) {
        /* 空文件且没有读到任何字符（首次调用），返回空行 */
    }
    if (len == 0 && feof(fp)) {
        free(buf);
        return NULL;
    }
    buf[len] = '\0';
    return buf;
}

/* Document 管理 */
static Document *doc_new(void) {
    Document *d;
    d = (Document*)malloc(sizeof(Document));
    if (!d) return NULL;
    d->lines = (char**)malloc(sizeof(char*) * INITIAL_CAPACITY);
    if (!d->lines) { free(d); return NULL; }
    d->size = 0;
    d->capacity = INITIAL_CAPACITY;
    d->filename = NULL;
    d->modified = 0;
    return d;
}

static void free_lines(char **lines, size_t cnt) {
    size_t i;
    for (i = 0; i < cnt; ++i) free(lines[i]);
}

static void doc_free(Document *d) {
    if (!d) return;
    free_lines(d->lines, d->size);
    free(d->lines);
    free(d->filename);
    free(d);
}

static int doc_ensure_capacity(Document *d, size_t need) {
    char **n;
    size_t newcap;
    if (need <= d->capacity) return 1;
    newcap = d->capacity;
    while (newcap < need) newcap *= 2;
    n = (char**)realloc(d->lines, sizeof(char*) * newcap);
    if (!n) return 0;
    d->lines = n;
    d->capacity = newcap;
    return 1;
}

static int doc_append(Document *d, char *line) {
    if (!doc_ensure_capacity(d, d->size + 1)) return 0;
    d->lines[d->size++] = line;
    d->modified = 1;
    return 1;
}

static int doc_insert(Document *d, size_t pos, char *line) {
    size_t i;
    if (pos > d->size) pos = d->size;
    if (!doc_ensure_capacity(d, d->size + 1)) return 0;
    for (i = d->size; i > pos; --i) d->lines[i] = d->lines[i-1];
    d->lines[pos] = line;
    d->size++;
    d->modified = 1;
    return 1;
}

static int doc_delete(Document *d, size_t pos) {
    size_t i;
    if (pos >= d->size) return 0;
    free(d->lines[pos]);
    for (i = pos; i + 1 < d->size; ++i) d->lines[i] = d->lines[i+1];
    d->size--;
    d->modified = 1;
    return 1;
}

static void doc_clear(Document *d) {
    free_lines(d->lines, d->size);
    d->size = 0;
    free(d->filename);
    d->filename = NULL;
    d->modified = 0;
}

/* 文件操作 */
static int doc_load(Document *d, const char *fname) {
    FILE *f;
    char *line;
    d->modified = 0;
    f = fopen(fname, "rb");
    if (!f) return 0;
    doc_clear(d);
    while (1) {
        line = readline_alloc(f);
        if (!line) break;
        if (!doc_append(d, line)) { free(line); fclose(f); return 0; }
    }
    fclose(f);
    d->filename = xstrdup(fname);
    if (!d->filename) return 0;
    d->modified = 0;
    return 1;
}

static int doc_save(Document *d, const char *fname) {
    FILE *f;
    size_t i;
    if (!fname) return 0;
    f = fopen(fname, "wb");
    if (!f) return 0;
    for (i = 0; i < d->size; ++i) {
        if (fputs(d->lines[i], f) == EOF || fputc('\n', f) == EOF) { fclose(f); return 0; }
    }
    fclose(f);
    free(d->filename);
    d->filename = xstrdup(fname);
    d->modified = 0;
    return 1;
}

/* 多行输入直到单独一行 '.' 结束 */
static char **read_multiline(size_t *out_count) {
    char **arr;
    size_t cap, cnt;
    char *line;
    cap = 16;
    cnt = 0;
    arr = (char**)malloc(sizeof(char*) * cap);
    if (!arr) return NULL;
    while (1) {
        line = readline_alloc(stdin);
        if (!line) {
            break;
        }
        if (strcmp(line, ".") == 0) { free(line); break; }
        if (cnt >= cap) {
            char **na;
            cap *= 2;
            na = (char**)realloc(arr, sizeof(char*) * cap);
            if (!na) { free_lines(arr, cnt); free(arr); return NULL; }
            arr = na;
        }
        arr[cnt++] = line;
    }
    *out_count = cnt;
    return arr;
}

/* 查找（不区分大小写可选） */
static int str_contains_ci(const char *hay, const char *pat) {
    size_t hn, pn, i, j;
    hn = strlen(hay);
    pn = strlen(pat);
    if (pn == 0) return 1;
    if (pn > hn) return 0;
    for (i = 0; i + pn <= hn; ++i) {
        for (j = 0; j < pn; ++j) {
            if (tolower((unsigned char)hay[i+j]) != tolower((unsigned char)pat[j])) break;
        }
        if (j == pn) return 1;
    }
    return 0;
}

static void cmd_find(Document *d, const char *pat, int ci) {
    size_t i;
    if (!pat || pat[0] == '\0') { printf("空模式。\n"); return; }
    for (i = 0; i < d->size; ++i) {
        if (ci) {
            if (str_contains_ci(d->lines[i], pat)) printf("%u: %s\n", (unsigned int)(i+1), d->lines[i]);
        } else {
            if (strstr(d->lines[i], pat)) printf("%u: %s\n", (unsigned int)(i+1), d->lines[i]);
        }
    }
}

/* 在单行上替换（返回是否发生替换） - 简化实现，分大小写两套 */
static int replace_in_line_simple(char **pline, const char *pat, const char *rep, int all, int ci) {
    char *line = *pline;
    size_t linelen = strlen(line);
    size_t patlen = strlen(pat);
    size_t replen = strlen(rep);
    size_t count = 0;
    size_t i, newlen;
    char *nline;
    char *dst;
    char *p;
    if (patlen == 0) return 0;
    if (!ci) {
        /* 先统计出现次数（若 all）或找到首次 */
        if (!all) {
            p = strstr(line, pat);
            if (!p) return 0;
            /* 构造新字符串 */
            newlen = linelen - patlen + replen;
            nline = (char*)malloc(newlen + 1);
            if (!nline) return 0;
            i = p - line;
            memcpy(nline, line, i);
            memcpy(nline + i, rep, replen);
            strcpy(nline + i + replen, p + patlen);
            free(line);
            *pline = nline;
            return 1;
        }
        /* all */
        p = strstr(line, pat);
        while (p) {
            count++;
            p = strstr(p + patlen, pat);
        }
        if (count == 0) return 0;
        newlen = linelen + count * (replen - patlen);
        nline = (char*)malloc(newlen + 1);
        if (!nline) return 0;
        dst = nline;
        p = line;
        while ((p = strstr(p, pat)) != NULL) {
            size_t prefix = p - line;
            memcpy(dst, line, prefix);
            dst += prefix;
            memcpy(dst, rep, replen);
            dst += replen;
            line = p + patlen;
            p = line;
        }
        strcpy(dst, line);
        free(*pline);
        *pline = nline;
        return 1;
    } else {
        /* 忽略大小写：构造小写副本用于查找 */
        char *low = (char*)malloc(linelen + 1);
        char *lpat = (char*)malloc(patlen + 1);
        int changed = 0;
        if (!low || !lpat) { free(low); free(lpat); return 0; }
        for (i = 0; i < linelen; ++i) low[i] = tolower((unsigned char)line[i]);
        low[linelen] = '\0';
        for (i = 0; i < patlen; ++i) lpat[i] = tolower((unsigned char)pat[i]);
        lpat[patlen] = '\0';
        if (!all) {
            char *q = strstr(low, lpat);
            if (!q) { free(low); free(lpat); return 0; }
            i = q - low;
            newlen = linelen - patlen + replen;
            nline = (char*)malloc(newlen + 1);
            if (!nline) { free(low); free(lpat); return 0; }
            memcpy(nline, *pline, i);
            memcpy(nline + i, rep, replen);
            strcpy(nline + i + replen, *pline + i + patlen);
            free(*pline);
            *pline = nline;
            free(low); free(lpat);
            return 1;
        }
        /* all, 先数 */
        {
            char *t = low;
            while ((t = strstr(t, lpat)) != NULL) { count++; t += patlen; }
        }
        if (count == 0) { free(low); free(lpat); return 0; }
        newlen = linelen + count * (replen - patlen);
        nline = (char*)malloc(newlen + 1);
        if (!nline) { free(low); free(lpat); return 0; }
        dst = nline;
        {
            size_t srcpos = 0;
            char *found;
            while ((found = strstr(low + srcpos, lpat)) != NULL) {
                size_t pos = found - low;
                memcpy(dst, *pline + srcpos, pos - srcpos);
                dst += pos - srcpos;
                memcpy(dst, rep, replen);
                dst += replen;
                srcpos = pos + patlen;
            }
            strcpy(dst, *pline + srcpos);
        }
        free(*pline);
        *pline = nline;
        free(low); free(lpat);
        return 1;
    }
}

/* 替换命令在整个文档上运行 */
static size_t cmd_replace(Document *d, const char *pat, const char *rep, int all, int ci) {
    size_t i, changed = 0;
    if (!pat) return 0;
    for (i = 0; i < d->size; ++i) {
        if (replace_in_line_simple(&d->lines[i], pat, rep, all, ci)) changed++;
    }
    if (changed) d->modified = 1;
    return changed;
}

/* 命令帮助 */
static void cmd_help(void) {
    printf("命令列表：\n");
    printf(" open [file]\n");
    printf(" new\n");
    printf(" save [file]\n");
    printf(" show [start] [end]\n");
    printf(" append\n");
    printf(" insert [n]\n");
    printf(" delete [n]\n");
    printf(" find [pattern] [i]\n");
    printf(" replace [pat] [rep] [all] [i]\n");
    printf(" exit\n");
    printf(" help\n");
}

/* 小工具：安全读取一行命令（在主循环中使用 fgets） */
static void trim_newline(char *s) {
    size_t n = strlen(s);
    if (n > 0 && s[n-1] == '\n') s[n-1] = '\0';
}

/* 主程序 */
int main(void) {
    Document *doc;
    char cmdline[CMD_BUF];
    char *tok;
    char *saveptr; /* not standard C89, avoid strtok_r; we will use strtok */
    doc = doc_new();
    if (!doc) { fprintf(stderr, "内存分配失败\n"); return 1; }
    printf("简易记事本。输入 help 查看命令。\n");
    while (1) {
        size_t start, end, i;
        int ci = 0, all = 0;
        char *arg1, *arg2, *arg3, *arg4;
        printf("> ");
        fflush(stdout);
        if (!fgets(cmdline, sizeof(cmdline), stdin)) {
            printf("\n");
            break;
        }
        trim_newline(cmdline);
        tok = strtok(cmdline, " ");
        if (!tok) continue;
        if (strcmp(tok, "help") == 0) {
            cmd_help();
            continue;
        }
        if (strcmp(tok, "new") == 0) {
            if (doc->modified) {
                int c;
                printf("有未保存更改，继续将丢失。输入 y 确认：");
                c = getchar();
                while (getchar() != '\n');
                if (c != 'y' && c != 'Y') { printf("已取消。\n"); continue; }
            }
            doc_clear(doc);
            printf("新建空文档。\n");
            continue;
        }
        if (strcmp(tok, "open") == 0) {
            arg1 = strtok(NULL, " ");
            if (!arg1) { printf("用法: open [file]\n"); continue; }
            if (doc->modified) {
                int c;
                printf("有未保存更改，继续将丢失。输入 y 确认：");
                c = getchar();
                while (getchar() != '\n');
                if (c != 'y' && c != 'Y') { printf("已取消。\n"); continue; }
            }
            if (!doc_load(doc, arg1)) printf("打开失败: %s\n", arg1);
            else printf("已打开: %s (%u 行)\n", arg1, (unsigned int)doc->size);
            continue;
        }
        if (strcmp(tok, "save") == 0) {
            arg1 = strtok(NULL, " ");
            if (!arg1) {
                if (!doc->filename) { printf("没有文件名，请使用 save [file]\n"); continue; }
                arg1 = doc->filename;
            }
            if (!doc_save(doc, arg1)) printf("保存失败: %s\n", arg1);
            else printf("已保存到: %s\n", arg1);
            continue;
        }
        if (strcmp(tok, "show") == 0) {
            arg1 = strtok(NULL, " ");
            arg2 = strtok(NULL, " ");
            if (arg1) start = (size_t)atoi(arg1);
            else start = 1;
            if (arg2) end = (size_t)atoi(arg2);
            else end = doc->size;
            if (start < 1) start = 1;
            if (end > doc->size) end = doc->size;
            if (start > end) { printf("范围错误。\n"); continue; }
            for (i = start; i <= end; ++i) printf("%u: %s\n", (unsigned int)i, doc->lines[i-1]);
            continue;
        }
        if (strcmp(tok, "append") == 0) {
            size_t cnt, j;
            char **arr = read_multiline(&cnt);
            if (!arr) { printf("读取失败。\n"); continue; }
            for (j = 0; j < cnt; ++j) doc_append(doc, arr[j]);
            free(arr);
            printf("已追加 %u 行。\n", (unsigned int)cnt);
            continue;
        }
        if (strcmp(tok, "insert") == 0) {
            arg1 = strtok(NULL, " ");
            start = 1;
            if (arg1) start = (size_t)atoi(arg1);
            if (start < 1) start = 1;
            if (start > doc->size + 1) start = doc->size + 1;
            printf("在第 %u 行之前插入。输入多行，以 '.' 结束：\n", (unsigned int)start);
            {
                size_t cnt, j;
                char **arr = read_multiline(&cnt);
                if (!arr) { printf("读取失败。\n"); continue; }
                for (j = 0; j < cnt; ++j) doc_insert(doc, start - 1 + j, arr[j]);
                free(arr);
                printf("已插入 %u 行。\n", (unsigned int)cnt);
            }
            continue;
        }
        if (strcmp(tok, "delete") == 0) {
            arg1 = strtok(NULL, " ");
            if (!arg1) { printf("用法: delete [n]\n"); continue; }
            start = (size_t)atoi(arg1);
            if (start < 1 || start > doc->size) { printf("行号超出范围。\n"); continue; }
            doc_delete(doc, start - 1);
            printf("已删除第 %u 行。\n", (unsigned int)start);
            continue;
        }
        if (strcmp(tok, "find") == 0) {
            arg1 = strtok(NULL, " ");
            arg2 = strtok(NULL, " ");
            ci = 0;
            if (!arg1) { printf("用法: find [pattern] [i]\n"); continue; }
            if (arg2 && strcmp(arg2, "i") == 0) ci = 1;
            cmd_find(doc, arg1, ci);
            continue;
        }
        if (strcmp(tok, "replace") == 0) {
            arg1 = strtok(NULL, " ");
            arg2 = strtok(NULL, " ");
            arg3 = strtok(NULL, " ");
            arg4 = strtok(NULL, " ");
            if (!arg1 || !arg2) { printf("用法: replace [pat] [rep] [all] [i]\n"); continue; }
            all = 0; ci = 0;
            if (arg3 && strcmp(arg3, "all") == 0) all = 1;
            if (arg4 && strcmp(arg4, "i") == 0) ci = 1;
            {
                size_t changed = cmd_replace(doc, arg1, arg2, all, ci);
                if (changed) printf("已修改 %u 行。\n", (unsigned int)changed);
                else printf("未找到匹配项。\n");
            }
            continue;
        }
        if (strcmp(tok, "exit") == 0) {
            if (doc->modified) {
                int c;
                printf("有未保存更改，确认退出请输入 y：");
                c = getchar();
                while (getchar() != '\n');
                if (c != 'y' && c != 'Y') { printf("已取消退出。\n"); continue; }
            }
            break;
        }
        printf("未知命令: %s\n", tok);
    }

    doc_free(doc);
    return 0;
}
