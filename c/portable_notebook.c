/*
 portable_notebook.c
 Portable command-line text editor (single-file, standard C)
 Target: Dev-C++ (MinGW/GCC), Linux, macOS (GCC/Clang)
 Compile: gcc -o notebook portable_notebook.c
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#ifndef LINE_MAX_LEN
#define LINE_MAX_LEN 4096
#endif

#define INITIAL_CAP 1024

#if defined(_WIN32) || defined(_WIN64)
#define DEFAULT_EOL "\r\n"
#else
#define DEFAULT_EOL "\n"
#endif

typedef struct {
    char **lines;
    size_t count;
    size_t capacity;
    char *last_snapshot; /* simple undo snapshot */
} TextBuffer;

/* helper: fatal */
static void fatal(const char *msg) {
    fprintf(stderr, "Fatal: %s\n", msg);
    exit(EXIT_FAILURE);
}

/* create buffer */
static TextBuffer* tb_create(void) {
    TextBuffer *tb = (TextBuffer*)calloc(1, sizeof(TextBuffer));
    if (!tb) fatal("out of memory");
    tb->capacity = INITIAL_CAP;
    tb->lines = (char**)calloc(tb->capacity, sizeof(char*));
    if (!tb->lines) fatal("out of memory");
    tb->count = 0;
    tb->last_snapshot = NULL;
    return tb;
}

/* free buffer */
static void tb_free(TextBuffer *tb) {
    if (!tb) return;
    for (size_t i = 0; i < tb->count; ++i) free(tb->lines[i]);
    free(tb->lines);
    free(tb->last_snapshot);
    free(tb);
}

/* ensure capacity */
static void tb_ensure(TextBuffer *tb, size_t mincap) {
    if (tb->capacity >= mincap) return;
    size_t nc = tb->capacity;
    while (nc < mincap) nc *= 2;
    char **nl = (char**)realloc(tb->lines, nc * sizeof(char*));
    if (!nl) fatal("out of memory");
    tb->lines = nl;
    tb->capacity = nc;
}

/* safe strdup */
static char* safe_strdup(const char *s) {
    if (!s) return NULL;
    size_t n = strlen(s);
    char *p = (char*)malloc(n + 1);
    if (!p) fatal("out of memory");
    memcpy(p, s, n + 1);
    return p;
}

/* read a full line from stdin (dynamically) */
static char* input_line(void) {
    char buf[512];
    if (!fgets(buf, (int)sizeof(buf), stdin)) return NULL;
    size_t n = strcspn(buf, "\r\n");
    buf[n] = '\0';
    /* if line fits, duplicate */
    if (n < sizeof(buf)-1 || buf[sizeof(buf)-2] == '\n') return safe_strdup(buf);
    /* else read rest */
    char *res = safe_strdup(buf);
    int c;
    while ((c = getchar()) != EOF && c != '\n' && c != '\r') {
        size_t len = strlen(res);
        res = (char*)realloc(res, len + 2);
        if (!res) fatal("out of memory");
        res[len] = (char)c;
        res[len+1] = '\0';
    }
    return res;
}

/* snapshot for undo */
static void tb_snapshot(TextBuffer *tb) {
    free(tb->last_snapshot);
    size_t total = 0;
    for (size_t i=0;i<tb->count;i++) total += strlen(tb->lines[i]) + 1;
    char *all = (char*)malloc(total + 1);
    if (!all) fatal("out of memory");
    char *p = all;
    for (size_t i=0;i<tb->count;i++) {
        size_t L = strlen(tb->lines[i]);
        memcpy(p, tb->lines[i], L);
        p += L;
        *p++ = '\n';
    }
    *p = '\0';
    tb->last_snapshot = all;
}

/* restore snapshot */
static void tb_restore(TextBuffer *tb) {
    if (!tb->last_snapshot) { printf("No undo available.\n"); return; }
    for (size_t i=0;i<tb->count;i++) free(tb->lines[i]);
    tb->count = 0;
    char *copy = safe_strdup(tb->last_snapshot);
    char *tok = strtok(copy, "\n");
    while (tok) {
        tb_ensure(tb, tb->count + 1);
        tb->lines[tb->count++] = safe_strdup(tok);
        tok = strtok(NULL, "\n");
    }
    free(copy);
    printf("Undo done.\n");
}

/* load file */
static int tb_load(TextBuffer *tb, const char *path) {
    if (!path || path[0] == '\0') return 0;
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    for (size_t i=0;i<tb->count;i++) free(tb->lines[i]);
    tb->count = 0;
    char *line = NULL;
    size_t cap = 0;
#if defined(_MSC_VER) || defined(__MINGW32__)
    /* no getline guaranteed: use fgets loop */
    char tbuf[LINE_MAX_LEN];
    while (fgets(tbuf, sizeof(tbuf), f)) {
        size_t L = strlen(tbuf);
        while (L>0 && (tbuf[L-1]=='\n' || tbuf[L-1]=='\r')) tbuf[--L] = '\0';
        tb_ensure(tb, tb->count + 1);
        tb->lines[tb->count++] = safe_strdup(tbuf);
    }
#else
    ssize_t r;
    while ((r = getline(&line, &cap, f)) != -1) {
        while (r>0 && (line[r-1]=='\n' || line[r-1]=='\r')) line[--r] = '\0';
        tb_ensure(tb, tb->count + 1);
        tb->lines[tb->count++] = safe_strdup(line);
    }
    free(line);
#endif
    fclose(f);
    return 1;
}

/* save file (create .bak if exists) */
static int tb_save(TextBuffer *tb, const char *path) {
    if (!path || path[0]=='\0') return 0;
    /* backup */
    FILE *chk = fopen(path, "rb");
    if (chk) {
        fclose(chk);
        char bak[512];
        if ((int)snprintf(bak, sizeof(bak), "%s.bak", path) > 0) {
            FILE *src = fopen(path, "rb");
            FILE *dst = fopen(bak, "wb");
            if (src && dst) {
                char buf[8192];
                size_t n;
                while ((n = fread(buf,1,sizeof(buf),src))>0) fwrite(buf,1,n,dst);
            }
            if (src) fclose(src);
            if (dst) fclose(dst);
        }
    }
    FILE *f = fopen(path, "wb");
    if (!f) return 0;
    for (size_t i=0;i<tb->count;i++) {
#if defined(_WIN32) || defined(_WIN64)
        if (fprintf(f, "%s\r\n", tb->lines[i]) < 0) { fclose(f); return 0; }
#else
        if (fprintf(f, "%s\n", tb->lines[i]) < 0) { fclose(f); return 0; }
#endif
    }
    fclose(f);
    return 1;
}

/* view */
static void tb_view(TextBuffer *tb, size_t start1, size_t maxlines) {
    if (tb->count == 0) { printf("(empty)\n"); return; }
    if (start1 < 1) start1 = 1;
    size_t start = start1 - 1;
    size_t end = start + maxlines;
    if (end > tb->count) end = tb->count;
    for (size_t i=start;i<end;i++) printf("%6zu: %s\n", i+1, tb->lines[i]);
}

/* replace line */
static int tb_replace_line(TextBuffer *tb, size_t lineno, const char *text) {
    if (lineno < 1 || lineno > tb->count) return 0;
    size_t idx = lineno - 1;
    free(tb->lines[idx]);
    tb->lines[idx] = safe_strdup(text ? text : "");
    return 1;
}

/* insert line before lineno (1-based). if lineno > count+1, append */
static void tb_insert_line(TextBuffer *tb, size_t lineno, const char *text) {
    if (lineno < 1) lineno = 1;
    size_t idx = lineno - 1;
    if (idx > tb->count) idx = tb->count;
    tb_ensure(tb, tb->count + 1);
    for (size_t i=tb->count;i>idx;i--) tb->lines[i] = tb->lines[i-1];
    tb->lines[idx] = safe_strdup(text ? text : "");
    tb->count++;
}

/* delete line */
static int tb_delete_line(TextBuffer *tb, size_t lineno) {
    if (lineno < 1 || lineno > tb->count) return 0;
    size_t idx = lineno - 1;
    free(tb->lines[idx]);
    for (size_t i=idx;i+1<tb->count;i++) tb->lines[i] = tb->lines[i+1];
    tb->count--;
    return 1;
}

/* find pattern, start_index is 0-based line index */
static int tb_find(TextBuffer *tb, const char *pat, size_t start_index, int case_insensitive, size_t *out_line, size_t *out_pos) {
    if (!pat || pat[0]=='\0') return 0;
    size_t patlen = strlen(pat);
    for (size_t i=start_index;i<tb->count;i++) {
        const char *ln = tb->lines[i];
        size_t llen = strlen(ln);
        if (!case_insensitive) {
            char *p = strstr(ln, pat);
            if (p) { *out_line = i; *out_pos = (size_t)(p - ln); return 1; }
        } else {
            if (patlen > llen) continue;
            for (size_t pos=0; pos+patlen<=llen; pos++) {
                size_t k;
                for (k=0;k<patlen;k++) if (tolower((unsigned char)ln[pos+k]) != tolower((unsigned char)pat[k])) break;
                if (k==patlen) { *out_line = i; *out_pos = pos; return 1; }
            }
        }
    }
    return 0;
}

/* replace all occurrences (non-regex) */
static void tb_replace_all(TextBuffer *tb, const char *pat, const char *rep, int case_insensitive) {
    if (!pat || pat[0]=='\0') return;
    size_t patlen = strlen(pat);
    size_t replen = rep ? strlen(rep) : 0;
    for (size_t i=0;i<tb->count;i++) {
        const char *src = tb->lines[i];
        size_t srclen = strlen(src);
        /* allocate initial out */
        size_t outcap = srclen + 64;
        char *out = (char*)malloc(outcap);
        if (!out) fatal("out of memory");
        size_t outpos = 0, inpos = 0;
        while (inpos < srclen) {
            int match = 0;
            if (!case_insensitive) {
                if (inpos + patlen <= srclen && memcmp(src+inpos, pat, patlen) == 0) match = 1;
            } else {
                if (inpos + patlen <= srclen) {
                    size_t k; for (k=0;k<patlen;k++) if (tolower((unsigned char)src[inpos+k]) != tolower((unsigned char)pat[k])) break;
                    if (k==patlen) match = 1;
                }
            }
            if (match) {
                if (outpos + replen + 1 > outcap) { outcap = (outpos + replen + 1) * 2; out = (char*)realloc(out, outcap); if (!out) fatal("out of memory"); }
                if (replen) memcpy(out+outpos, rep, replen);
                outpos += replen;
                inpos += patlen;
            } else {
                if (outpos + 2 > outcap) { outcap = outpos + 64; out = (char*)realloc(out, outcap); if (!out) fatal("out of memory"); }
                out[outpos++] = src[inpos++];
            }
        }
        out[outpos] = '\0';
        free(tb->lines[i]);
        tb->lines[i] = out;
    }
}

/* trim in-place */
static void trim_inplace(char *s) {
    if (!s) return;
    char *start = s;
    while (*start && isspace((unsigned char)*start)) ++start;
    if (start != s) memmove(s, start, strlen(start) + 1);
    size_t L = strlen(s);
    while (L > 0 && isspace((unsigned char)s[L-1])) s[--L] = '\0';
}

/* confirm */
static int confirm(const char *msg) {
    printf("%s (y/n): ", msg);
    char *ln = input_line();
    if (!ln) return 0;
    int yes = (ln[0]=='y' || ln[0]=='Y');
    free(ln);
    return yes;
}

/* show menu */
static void show_menu(void) {
    printf("=== Portable Notebook ===\n");
    printf("[O]Open [S]Save [A]Append [I]Insert [E]Edit [D]Delete [F]Find [R]Replace [V]View [U]Undo [H]Help [Q]Quit\n");
}

int main(void) {
    TextBuffer *tb = tb_create();
    char current_path[512] = "";
    show_menu();
    for (;;) {
        printf("\ncmd> ");
        char *cmd = input_line();
        if (!cmd) break;
        trim_inplace(cmd);
        if (cmd[0] == '\0') { free(cmd); continue; }
        char c = (char)tolower((unsigned char)cmd[0]);
        free(cmd);
        if (c == 'q') {
            if (tb->count > 0) {
                if (!confirm("Exit without saving?")) continue;
            }
            break;
        } else if (c == 'h') {
            show_menu();
        } else if (c == 'o') {
            printf("Open path: ");
            char *p = input_line();
            if (!p) continue;
            trim_inplace(p);
            if (p[0] != '\0') {
                if (tb_load(tb, p)) {
                    strncpy(current_path, p, sizeof(current_path)-1);
                    current_path[sizeof(current_path)-1] = '\0';
                    printf("Loaded %s (%zu lines)\n", current_path, tb->count);
                } else printf("Failed to open %s\n", p);
            }
            free(p);
        } else if (c == 's') {
            if (current_path[0] == '\0') {
                printf("Save path: ");
                char *p = input_line();
                if (!p) continue;
                trim_inplace(p);
                if (p[0] != '\0') strncpy(current_path, p, sizeof(current_path)-1);
                current_path[sizeof(current_path)-1] = '\0';
                free(p);
            }
            tb_snapshot(tb);
            if (tb_save(tb, current_path)) printf("Saved to %s (backup created if existed)\n", current_path);
            else printf("Save failed\n");
        } else if (c == 'a') {
            printf("Append lines. Single '.' stops.\n");
            while (1) {
                char *ln = input_line();
                if (!ln) break;
                if (strcmp(ln, ".") == 0) { free(ln); break; }
                tb_ensure(tb, tb->count + 1);
                tb->lines[tb->count++] = ln;
            }
        } else if (c == 'v') {
            printf("Start line (1): ");
            char *ln = input_line();
            size_t start = 1;
            if (ln) { if (sscanf(ln, "%zu", &start) != 1) start = 1; free(ln); }
            tb_view(tb, start, 40);
        } else if (c == 'e') {
            printf("Edit line number: ");
            char *ln = input_line();
            size_t lineno = 0;
            if (ln && sscanf(ln, "%zu", &lineno) == 1) {
                free(ln);
                printf("New content: ");
                char *newtext = input_line();
                if (!newtext) continue;
                tb_snapshot(tb);
                if (!tb_replace_line(tb, lineno, newtext)) printf("Invalid line number\n");
                free(newtext);
            } else { printf("Invalid input\n"); if (ln) free(ln); }
        } else if (c == 'i') {
            printf("Insert at line number (1 to append): ");
            char *ln = input_line();
            size_t lineno = 0;
            if (ln && sscanf(ln, "%zu", &lineno) == 1) {
                free(ln);
                printf("Content: ");
                char *text = input_line();
                if (!text) continue;
                tb_snapshot(tb);
                tb_insert_line(tb, lineno, text);
                free(text);
            } else { printf("Invalid input\n"); if (ln) free(ln); }
        } else if (c == 'd') {
            printf("Delete which line? ");
            char *ln = input_line();
            size_t lineno = 0;
            if (ln && sscanf(ln, "%zu", &lineno) == 1) {
                free(ln);
                if (!confirm("Confirm delete?")) continue;
                tb_snapshot(tb);
                if (!tb_delete_line(tb, lineno)) printf("Invalid line number\n");
            } else { printf("Invalid input\n"); if (ln) free(ln); }
        } else if (c == 'f') {
            printf("Find pattern: ");
            char *pat = input_line();
            if (!pat) continue;
            printf("Case sensitive? (y/n): ");
            char *cs = input_line();
            int csflag = (cs && (cs[0]=='y' || cs[0]=='Y'));
            free(cs);
            size_t out_line=0, out_pos=0;
            if (tb_find(tb, pat, 0, !csflag, &out_line, &out_pos)) {
                printf("Found at line %zu, pos %zu:\n  %s\n", out_line+1, out_pos+1, tb->lines[out_line]);
            } else printf("Not found\n");
            free(pat);
        } else if (c == 'r') {
            printf("Pattern: ");
            char *pat = input_line();
            if (!pat) continue;
            printf("Replacement: ");
            char *rep = input_line();
            if (!rep) { free(pat); continue; }
            printf("Case sensitive? (y/n): ");
            char *cs = input_line();
            int csflag = (cs && (cs[0]=='y' || cs[0]=='Y'));
            free(cs);
            printf("Replace all? (y/n): ");
            char *allp = input_line();
            int allflag = (allp && (allp[0]=='y' || allp[0]=='Y'));
            free(allp);
            tb_snapshot(tb);
            if (allflag) {
                tb_replace_all(tb, pat, rep, !csflag);
                printf("Replace all done\n");
            } else {
                size_t found_line=0, found_pos=0;
                if (tb_find(tb, pat, 0, !csflag, &found_line, &found_pos)) {
                    const char *old = tb->lines[found_line];
                    size_t oldlen = strlen(old);
                    size_t patlen = strlen(pat);
                    size_t replen = strlen(rep);
                    size_t newlen = oldlen - patlen + replen;
                    char *newline = (char*)malloc(newlen + 1);
                    if (!newline) fatal("out of memory");
                    if (found_pos > 0) memcpy(newline, old, found_pos);
                    memcpy(newline + found_pos, rep, replen);
                    memcpy(newline + found_pos + replen, old + found_pos + patlen, oldlen - (found_pos + patlen));
                    newline[newlen] = '\0';
                    free(tb->lines[found_line]);
                    tb->lines[found_line] = newline;
                    printf("Replaced at line %zu\n", found_line+1);
                } else printf("Pattern not found\n");
            }
            free(pat);
            free(rep);
        } else if (c == 'u') {
            tb_restore(tb);
        } else {
            printf("Unknown command. Press H for help.\n");
        }
    }

    tb_free(tb);
    printf("Exit\n");
    return 0;
}
