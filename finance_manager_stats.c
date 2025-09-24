/*
 * finance_manager_stats.c
 *
 * 财务管理工具（增强版）
 *
 * 新增功能：
 * - 按 ID 修改 / 删除（保留）
 * - 按日期范围与/或类别筛选记录
 * - 统计与分析函数：总和、均值、中位数、众数、方差、标准差、最小、最大、计数
 * - 在统计视图中可输出明细并导出筛选结果到 CSV
 *
 * 编译：
 *   gcc -std=c11 -O2 -lm -o finance_manager_stats finance_manager_stats.c
 *
 * 注意：
 * - 程序为示例，输入有基本校验，但非抗恶意输入场景。
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <math.h>

#define INITIAL_CAPACITY 128
#define DATE_LEN 11   /* YYYY-MM-DD + '\\0' */
#define CATEGORY_LEN 64
#define NOTE_LEN 256
#define LINE_BUF 1024
#define DATA_FILE "finance_data.csv"

/* 记录结构 */
typedef struct {
    int id;
    char date[DATE_LEN];
    char category[CATEGORY_LEN];
    double amount;
    char note[NOTE_LEN];
} Record;

/* 动态数组容器 */
typedef struct {
    Record *items;
    size_t size;
    size_t capacity;
    int next_id;
} RecordList;

/* 统计结果容器 */
typedef struct {
    size_t count;
    double sum;
    double mean;
    double median;
    double mode;      /* 若无明确众数，返回 NAN */
    double variance;  /* 样本方差（n-1）如果 count>1，否则 NAN */
    double stddev;    /* 标准差 */
    double min;
    double max;
} Stats;

/* ---------- 函数声明 ---------- */
void init_list(RecordList *list);
void free_list(RecordList *list);
void ensure_capacity(RecordList *list);
void add_record(RecordList *list, const char *date, const char *category, double amount, const char *note);
int find_index_by_id(RecordList *list, int id);
int delete_record(RecordList *list, int id);
int update_record(RecordList *list, int id, const char *date, const char *category, double amount, const char *note);
void list_records(RecordList *list);
int save_to_file(RecordList *list, const char *filename);
int load_from_file(RecordList *list, const char *filename);

/* 筛选辅助 */
size_t filter_records(RecordList *list, Record **out, const char *date_from, const char *date_to, const char *category);
/* 统计函数 */
Stats compute_stats_from_amounts(double *arr, size_t n);
double *collect_amounts(Record **records, size_t n);
/* I/O / 工具 */
void trim_newline(char *s);
int date_compare(const char *a, const char *b); /* lexicographic compare for YYYY-MM-DD */
void to_lower_str(char *s);

/* 交互 */
void print_menu(void);
void print_stats(Stats *s);

/* ---------- 实现 ---------- */

void init_list(RecordList *list) {
    list->items = malloc(sizeof(Record) * INITIAL_CAPACITY);
    if (!list->items) { perror("malloc"); exit(EXIT_FAILURE); }
    list->size = 0;
    list->capacity = INITIAL_CAPACITY;
    list->next_id = 1;
}

void free_list(RecordList *list) {
    free(list->items);
    list->items = NULL;
    list->size = 0;
    list->capacity = 0;
}

/* 扩容 */
void ensure_capacity(RecordList *list) {
    if (list->size >= list->capacity) {
        size_t newcap = list->capacity * 2;
        Record *p = realloc(list->items, sizeof(Record) * newcap);
        if (!p) { perror("realloc"); exit(EXIT_FAILURE); }
        list->items = p;
        list->capacity = newcap;
    }
}

void add_record(RecordList *list, const char *date, const char *category, double amount, const char *note) {
    ensure_capacity(list);
    Record *r = &list->items[list->size++];
    r->id = list->next_id++;
    strncpy(r->date, date, DATE_LEN-1); r->date[DATE_LEN-1] = '\0';
    strncpy(r->category, category, CATEGORY_LEN-1); r->category[CATEGORY_LEN-1] = '\0';
    r->amount = amount;
    strncpy(r->note, note, NOTE_LEN-1); r->note[NOTE_LEN-1] = '\0';
}

int find_index_by_id(RecordList *list, int id) {
    for (size_t i = 0; i < list->size; ++i) if (list->items[i].id == id) return (int)i;
    return -1;
}

int delete_record(RecordList *list, int id) {
    int idx = find_index_by_id(list, id);
    if (idx < 0) return 0;
    /* 保持顺序：移动后面的元素前移 */
    for (size_t i = idx+1; i < list->size; ++i) list->items[i-1] = list->items[i];
    list->size--;
    return 1;
}

int update_record(RecordList *list, int id, const char *date, const char *category, double amount, const char *note) {
    int idx = find_index_by_id(list, id);
    if (idx < 0) return 0;
    Record *r = &list->items[idx];
    strncpy(r->date, date, DATE_LEN-1); r->date[DATE_LEN-1] = '\0';
    strncpy(r->category, category, CATEGORY_LEN-1); r->category[CATEGORY_LEN-1] = '\0';
    r->amount = amount;
    strncpy(r->note, note, NOTE_LEN-1); r->note[NOTE_LEN-1] = '\0';
    return 1;
}

void list_records(RecordList *list) {
    if (list->size == 0) { printf("无记录。\n"); return; }
    printf("ID\t日期\t\t类别\t\t金额\t备注\n");
    printf("----------------------------------------------------------------\n");
    for (size_t i = 0; i < list->size; ++i) {
        Record *r = &list->items[i];
        printf("%d\t%-10s\t%-12s\t%10.2f\t%s\n", r->id, r->date, r->category, r->amount, r->note);
    }
}

/* 保存到 CSV（覆盖写）*/
int save_to_file(RecordList *list, const char *filename) {
    FILE *f = fopen(filename, "w");
    if (!f) { perror("fopen"); return 0; }
    fprintf(f, "id,date,category,amount,note\n");
    for (size_t i = 0; i < list->size; ++i) {
        Record *r = &list->items[i];
        /* 简单处理双引号 */
        char note_safe[NOTE_LEN*2]; size_t p=0;
        for (size_t j=0; r->note[j] && p+1 < sizeof(note_safe); ++j) {
            note_safe[p++] = (r->note[j] == '"') ? '\'' : r->note[j];
        }
        note_safe[p] = '\0';
        fprintf(f, "%d,%s,%s,%.2f,\"%s\"\n", r->id, r->date, r->category, r->amount, note_safe);
    }
    fclose(f);
    return 1;
}

/* 从 CSV 加载（追加） */
int load_from_file(RecordList *list, const char *filename) {
    FILE *f = fopen(filename, "r");
    if (!f) return 0;
    char line[LINE_BUF];
    int line_no = 0;
    while (fgets(line, sizeof(line), f)) {
        line_no++;
        trim_newline(line);
        if (line_no == 1 && strstr(line, "id") && strstr(line, "date")) continue;
        if (line[0] == '\0') continue;
        /* 基本 CSV 解析，类似之前实现 */
        char *p = line;
        char *tok = strtok(p, ",");
        if (!tok) continue;
        int id = atoi(tok);
        tok = strtok(NULL, ","); if (!tok) continue;
        char date[DATE_LEN]; strncpy(date, tok, DATE_LEN-1); date[DATE_LEN-1]='\0';
        tok = strtok(NULL, ","); if (!tok) continue;
        char category[CATEGORY_LEN]; strncpy(category, tok, CATEGORY_LEN-1); category[CATEGORY_LEN-1]='\0';
        tok = strtok(NULL, ","); if (!tok) continue;
        double amount = atof(tok);
        char note_rest[NOTE_LEN*2] = "";
        char *note_start = strtok(NULL, "");
        if (note_start) {
            size_t l = strlen(note_start);
            if (l >= 2 && note_start[0]=='"' && note_start[l-1]=='"') {
                note_start[l-1] = '\0';
                strncpy(note_rest, note_start+1, NOTE_LEN-1);
            } else {
                strncpy(note_rest, note_start, NOTE_LEN-1);
            }
            note_rest[NOTE_LEN-1] = '\0';
        }
        ensure_capacity(list);
        Record *r = &list->items[list->size++];
        r->id = id;
        strncpy(r->date, date, DATE_LEN-1); r->date[DATE_LEN-1] = '\0';
        strncpy(r->category, category, CATEGORY_LEN-1); r->category[CATEGORY_LEN-1] = '\0';
        r->amount = amount;
        strncpy(r->note, note_rest, NOTE_LEN-1); r->note[NOTE_LEN-1] = '\0';
        if (id >= list->next_id) list->next_id = id + 1;
    }
    fclose(f);
    return 1;
}

/* 将符合条件的记录指针输出到 out（out 由调用者分配为 Record* 数组或 malloc），返回数量
 * 条件：date_from/date_to 可以为 NULL（无下/上界），category 为 NULL 表示不按类别筛选（类别不区分大小写）
 * 注意：out 必须有足够空间（>= list->size），这里为了简化直接要求外部准备。
 */
size_t filter_records(RecordList *list, Record **out, const char *date_from, const char *date_to, const char *category) {
    size_t cnt = 0;
    char catlower[CATEGORY_LEN];
    if (category) {
        strncpy(catlower, category, CATEGORY_LEN-1); catlower[CATEGORY_LEN-1]='\0'; to_lower_str(catlower);
    }
    for (size_t i=0;i<list->size;++i) {
        Record *r = &list->items[i];
        if (date_from && date_compare(r->date, date_from) < 0) continue;
        if (date_to && date_compare(r->date, date_to) > 0) continue;
        if (category) {
            char rcat[CATEGORY_LEN]; strncpy(rcat, r->category, CATEGORY_LEN-1); rcat[CATEGORY_LEN-1]='\0'; to_lower_str(rcat);
            if (strcmp(rcat, catlower) != 0) continue;
        }
        out[cnt++] = r;
    }
    return cnt;
}

/* 从记录指针数组收集金额到新分配数组，调用者需 free */
double *collect_amounts(Record **records, size_t n) {
    if (n == 0) return NULL;
    double *arr = malloc(sizeof(double) * n);
    if (!arr) { perror("malloc"); exit(EXIT_FAILURE); }
    for (size_t i=0;i<n;++i) arr[i] = records[i]->amount;
    return arr;
}

/* 比较日期字符串 YYYY-MM-DD（字典序可用）*/
int date_compare(const char *a, const char *b) {
    return strcmp(a, b);
}

/* 将字符串转小写 */
void to_lower_str(char *s) { for (; *s; ++s) *s = (char)tolower((unsigned char)*s); }

int cmp_double_asc(const void *pa, const void *pb) {
    double a = *(const double*)pa, b = *(const double*)pb;
    if (a < b) return -1; if (a > b) return 1; return 0;
}

/* 计算统计量（中位数、众数、方差等）：
 * - median: 排序后取中位（若 n 偶数，取平均）
 * - mode: 返回唯一众数值；若存在多众数或无重复，返回 NAN（此处策略：要求唯一出现次数严格大于其他）
 * - variance/stddev: 使用样本方差（除以 n-1），若 n<=1 返回 NAN
 */
Stats compute_stats_from_amounts(double *arr, size_t n) {
    Stats s;
    s.count = n;
    s.sum = 0.0;
    s.mean = NAN; s.median = NAN; s.mode = NAN; s.variance = NAN; s.stddev = NAN;
    s.min = NAN; s.max = NAN;
    if (n == 0) return s;
    /* 复制一份进行排序以不破坏原始 */
    double *tmp = malloc(sizeof(double)*n);
    if (!tmp) { perror("malloc"); exit(EXIT_FAILURE); }
    for (size_t i=0;i<n;++i) { tmp[i] = arr[i]; s.sum += arr[i]; }
    s.mean = s.sum / (double)n;
    qsort(tmp, n, sizeof(double), cmp_double_asc);
    s.min = tmp[0]; s.max = tmp[n-1];
    /* 中位数 */
    if (n % 2 == 1) s.median = tmp[n/2];
    else s.median = (tmp[n/2 - 1] + tmp[n/2]) / 2.0;
    /* 众数：遍历已排序数组，统计最长连续段，判断是否唯一 */
    size_t best_count = 1, cur_count = 1;
    double best_value = tmp[0];
    int ties = 0;
    for (size_t i=1;i<n;++i) {
        if (tmp[i] == tmp[i-1]) {
            cur_count++;
        } else {
            if (cur_count > best_count) { best_count = cur_count; best_value = tmp[i-1]; ties = 0; }
            else if (cur_count == best_count) { ties = 1; }
            cur_count = 1;
        }
    }
    /* 结束段处理 */
    if (cur_count > best_count) { best_count = cur_count; best_value = tmp[n-1]; ties = 0; }
    else if (cur_count == best_count) { ties = 1; }
    if (best_count > 1 && ties == 0) s.mode = best_value;
    else s.mode = NAN; /* 没有唯一众数 */
    /* 方差（样本方差） */
    if (n > 1) {
        double sumsq = 0.0;
        for (size_t i=0;i<n;++i) {
            double d = arr[i] - s.mean;
            sumsq += d*d;
        }
        s.variance = sumsq / (double)(n - 1);
        s.stddev = sqrt(s.variance);
    } else {
        s.variance = NAN;
        s.stddev = NAN;
    }
    free(tmp);
    return s;
}

/* 辅助：打印统计结果 */
void print_stats(Stats *s) {
    printf("记录数: %zu\n", s->count);
    printf("总和: %.2f\n", s->sum);
    if (!isnan(s->mean)) printf("均值: %.4f\n", s->mean);
    if (!isnan(s->median)) printf("中位数: %.4f\n", s->median);
    if (!isnan(s->mode)) printf("众数: %.4f\n", s->mode); else printf("众数: 无唯一众数或无重复\n");
    if (!isnan(s->variance)) printf("样本方差: %.6f\n", s->variance);
    if (!isnan(s->stddev)) printf("样本标准差: %.6f\n", s->stddev);
    if (!isnan(s->min)) printf("最小值: %.2f\n", s->min);
    if (!isnan(s->max)) printf("最大值: %.2f\n", s->max);
}

/* 移除换行 */
void trim_newline(char *s) {
    size_t n = strlen(s);
    while (n>0 && (s[n-1]=='\n' || s[n-1]=='\r')) { s[n-1] = '\0'; n--; }
}

/* 打印菜单 */
void print_menu(void) {
    printf("\n--- 财务管理（增强版） %s ---\n", "2025-09-24");
    printf("1. 列出所有记录\n");
    printf("2. 添加记录\n");
    printf("3. 删除记录（按 ID）\n");
    printf("4. 修改记录（按 ID）\n");
    printf("5. 按条件筛选并统计（日期范围/类别）\n");
    printf("6. 导出筛选结果到 CSV\n");
    printf("7. 保存到文件\n");
    printf("8. 从文件加载（追加）\n");
    printf("9. 退出\n");
    printf("选择操作（1-9）：");
}

/* ---------- 主交互 ---------- */
int main(void) {
    RecordList list;
    init_list(&list);

    /* 试图加载默认文件 */
    if (load_from_file(&list, DATA_FILE)) {
        printf("已从 %s 加载 %zu 条记录（若文件存在）。\n", DATA_FILE, list.size);
    }

    char buf[LINE_BUF];
    while (1) {
        print_menu();
        if (!fgets(buf, sizeof(buf), stdin)) break;
        int choice = atoi(buf);
        if (choice == 1) {
            list_records(&list);
        } else if (choice == 2) {
            char date[DATE_LEN], category[CATEGORY_LEN], note[NOTE_LEN];
            double amount;
            printf("输入日期 (YYYY-MM-DD): ");
            if (!fgets(date, sizeof(date), stdin)) continue; trim_newline(date);
            printf("输入类别: ");
            if (!fgets(category, sizeof(category), stdin)) continue; trim_newline(category);
            printf("输入金额（收入正，支出负）: ");
            if (!fgets(buf, sizeof(buf), stdin)) continue; amount = atof(buf);
            printf("输入备注: ");
            if (!fgets(note, sizeof(note), stdin)) continue; trim_newline(note);
            add_record(&list, date, category, amount, note);
            printf("已添加，ID=%d\n", list.next_id - 1);
        } else if (choice == 3) {
            printf("输入要删除的 ID: ");
            if (!fgets(buf, sizeof(buf), stdin)) continue;
            int id = atoi(buf);
            if (delete_record(&list, id)) printf("已删除 ID=%d\n", id);
            else printf("未找到 ID=%d\n", id);
        } else if (choice == 4) {
            printf("输入要修改的 ID: ");
            if (!fgets(buf, sizeof(buf), stdin)) continue;
            int id = atoi(buf);
            int idx = find_index_by_id(&list, id);
            if (idx < 0) { printf("未找到 ID=%d\n", id); continue; }
            char date[DATE_LEN], category[CATEGORY_LEN], note[NOTE_LEN];
            double amount;
            printf("当前：日期=%s 类别=%s 金额=%.2f 备注=%s\n",
                   list.items[idx].date, list.items[idx].category, list.items[idx].amount, list.items[idx].note);
            printf("输入新日期 (YYYY-MM-DD): ");
            if (!fgets(date, sizeof(date), stdin)) continue; trim_newline(date);
            printf("输入新类别: ");
            if (!fgets(category, sizeof(category), stdin)) continue; trim_newline(category);
            printf("输入新金额: ");
            if (!fgets(buf, sizeof(buf), stdin)) continue; amount = atof(buf);
            printf("输入新备注: ");
            if (!fgets(note, sizeof(note), stdin)) continue; trim_newline(note);
            if (update_record(&list, id, date, category, amount, note)) printf("已更新 ID=%d\n", id);
            else printf("更新失败\n");
        } else if (choice == 5) {
            /* 筛选并统计 */
            char date_from[DATE_LEN] = "", date_to[DATE_LEN] = "", category[CATEGORY_LEN] = "";
            printf("输入开始日期 (YYYY-MM-DD) 或留空: ");
            if (!fgets(buf, sizeof(buf), stdin)) continue; trim_newline(buf); strncpy(date_from, buf, DATE_LEN-1);
            printf("输入结束日期 (YYYY-MM-DD) 或留空: ");
            if (!fgets(buf, sizeof(buf), stdin)) continue; trim_newline(buf); strncpy(date_to, buf, DATE_LEN-1);
            printf("输入类别 或留空: ");
            if (!fgets(buf, sizeof(buf), stdin)) continue; trim_newline(buf); strncpy(category, buf, CATEGORY_LEN-1);
            /* 准备指针数组 */
            Record **out = malloc(sizeof(Record*) * list.size);
            if (!out) { perror("malloc"); break; }
            const char *df = (strlen(date_from) ? date_from : NULL);
            const char *dt = (strlen(date_to) ? date_to : NULL);
            const char *cat = (strlen(category) ? category : NULL);
            size_t cnt = filter_records(&list, out, df, dt, cat);
            printf("筛选到 %zu 条记录。\n", cnt);
            if (cnt == 0) { free(out); continue; }
            double *amounts = collect_amounts(out, cnt);
            Stats s = compute_stats_from_amounts(amounts, cnt);
            print_stats(&s);
            printf("\n是否显示明细？(y/n): ");
            if (!fgets(buf, sizeof(buf), stdin)) { free(out); free(amounts); break; }
            trim_newline(buf);
            if (buf[0]=='y' || buf[0]=='Y') {
                printf("ID\t日期\t\t类别\t\t金额\t备注\n");
                printf("--------------------------------------------------------------\n");
                for (size_t i=0;i<cnt;++i) {
                    Record *r = out[i];
                    printf("%d\t%-10s\t%-12s\t%10.2f\t%s\n", r->id, r->date, r->category, r->amount, r->note);
                }
            }
            free(out);
            free(amounts);
        } else if (choice == 6) {
            /* 导出筛选结果 */
            char date_from[DATE_LEN] = "", date_to[DATE_LEN] = "", category[CATEGORY_LEN] = "";
            printf("输入开始日期 (YYYY-MM-DD) 或留空: ");
            if (!fgets(buf, sizeof(buf), stdin)) continue; trim_newline(buf); strncpy(date_from, buf, DATE_LEN-1);
            printf("输入结束日期 (YYYY-MM-DD) 或留空: ");
            if (!fgets(buf, sizeof(buf), stdin)) continue; trim_newline(buf); strncpy(date_to, buf, DATE_LEN-1);
            printf("输入类别 或留空: ");
            if (!fgets(buf, sizeof(buf), stdin)) continue; trim_newline(buf); strncpy(category, buf, CATEGORY_LEN-1);
            const char *df = (strlen(date_from) ? date_from : NULL);
            const char *dt = (strlen(date_to) ? date_to : NULL);
            const char *cat = (strlen(category) ? category : NULL);
            Record **out = malloc(sizeof(Record*) * list.size);
            if (!out) { perror("malloc"); break; }
            size_t cnt = filter_records(&list, out, df, dt, cat);
            if (cnt == 0) { printf("无匹配记录，取消导出。\n"); free(out); continue; }
            printf("输出文件名（默认筛选导出 csv）：");
            if (!fgets(buf, sizeof(buf), stdin)) { free(out); break; }
            trim_newline(buf);
            char *fname = buf;
            if (strlen(fname) == 0) fname = "export.csv";
            FILE *f = fopen(fname, "w");
            if (!f) { perror("fopen"); free(out); continue; }
            fprintf(f, "id,date,category,amount,note\n");
            for (size_t i=0;i<cnt;++i) {
                Record *r = out[i];
                char note_safe[NOTE_LEN*2]; size_t p=0;
                for (size_t j=0; r->note[j] && p+1 < sizeof(note_safe); ++j) note_safe[p++] = (r->note[j]=='\"') ? '\'' : r->note[j];
                note_safe[p] = '\0';
                fprintf(f, "%d,%s,%s,%.2f,\"%s\"\n", r->id, r->date, r->category, r->amount, note_safe);
            }
            fclose(f);
            printf("已导出 %zu 条到 %s\n", cnt, fname);
            free(out);
        } else if (choice == 7) {
            if (save_to_file(&list, DATA_FILE)) printf("已保存到 %s\n", DATA_FILE);
            else printf("保存失败\n");
        } else if (choice == 8) {
            printf("从 %s 加载（追加）？输入 y 确认: ", DATA_FILE);
            if (!fgets(buf, sizeof(buf), stdin)) continue; trim_newline(buf);
            if (buf[0]=='y' || buf[0]=='Y') {
                if (load_from_file(&list, DATA_FILE)) printf("已加载，当前 %zu 条\n", list.size);
                else printf("加载失败或文件不存在\n");
            } else printf("取消\n");
        } else if (choice == 9) {
            if (save_to_file(&list, DATA_FILE)) printf("已自动保存到 %s，退出。\n", DATA_FILE);
            else printf("退出但未保存（保存失败）。\n");
            break;
        } else {
            printf("无效选择。\n");
        }
    }

    free_list(&list);
    return 0;
}
