/*
 * library_improved_commented.c
 *
 * 改进版 简单图书馆借阅管理（CSV 存储，兼容 C89）
 *
 * 设计说明：
 *  - 存储：
 *      books.csv    每行: id,title,author,total,available
 *      borrowers.csv 每行: borrower_id,book_id,borrow_date,return_date
 *    注：CSV 不支持字段内含逗号或换行（不做引号/转义解析）。
 *
 *  - 兼容性：使用 C89 标准（不依赖 C99+ 特性），以便在较老编译器上编译。
 *
 *  - 内存与文件：
 *      - 程序使用动态数组管理记录，首次分配初始容量，按需倍增。
 *      - 所有 malloc/realloc 均检查返回值；失败时程序打印错误并退出。
 *      - 保存为“原子写入”方式：先写临时文件，写入成功后重命名覆盖原文件。
 *
 *  - 数据完整性：
 *      - 在读入阶段对字段做基本合法性检查（例如 id > 0，available <= total）。
 *      - 在删除图书前检查是否存在未归还的借阅记录。
 *      - 借书时检查 available > 0；还书时更新 return_date 并恢复 available（但不会超过 total）。
 *
 *  使用限制：
 *  - 本程序适合作为小型单用户命令行管理工具。若需并发访问、事务或字段级转义，
 *    请改用数据库（如 SQLite）或引入更完整的 CSV 解析库。
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ----------------------------- 常量与配置 ----------------------------- */

#define BOOKS_CSV "books.csv"       /* 图书数据文件 */
#define BORROW_CSV "borrowers.csv"  /* 借阅记录文件 */
#define TMP_SUFFIX ".tmp"           /* 原子写入时的临时文件后缀 */

#define MAX_LINE 1024               /* 读取单行时的缓冲上限（包括换行和终止符） */
#define MAX_FIELD 256               /* 单个字段最大长度（含终止符） */

/* ----------------------------- 结构类型 ----------------------------- */

/* 图书记录：id 为正整数；title/author 为以 NUL 结尾的字符串；total >= 0；0 <= available <= total */
typedef struct {
    int id;
    char title[MAX_FIELD];
    char author[MAX_FIELD];
    int total;
    int available;
} Book;

/* 借阅记录：borrow_date/return_date 格式为 "YYYY-MM-DD"（或空字符串表示未归还） */
typedef struct {
    int borrower_id;
    int book_id;
    char borrow_date[16]; /* 足够存放 "YYYY-MM-DD\0" */
    char return_date[16];
} BorrowRecord;

/* ----------------------------- 动态数组（全局） ----------------------------- */

/* 使用静态全局指针管理动态数组，便于各函数访问与统一释放 */
static Book *books = NULL;
static size_t books_count = 0;
static size_t books_capacity = 0;

static BorrowRecord *records = NULL;
static size_t records_count = 0;
static size_t records_capacity = 0;

/* ----------------------------- 辅助函数声明 ----------------------------- */

/* 内存分配包装：检查返回值，失败时打印错误并退出 */
static void *xmalloc(size_t n);
static void *xrealloc(void *p, size_t n);

/* 字符串处理 */
static void chomp(char *s);                              /* 去除末尾 CR/LF */
static void safe_strncpy(char *dst, const char *src, size_t dstsize); /* 边界安全的拷贝 */

/* 动态数组容量保障 */
static void ensure_books_capacity(void);
static void ensure_records_capacity(void);

/* 日期与 CSV 辅助 */
static void today(char *out, size_t outlen);            /* 获取当前日期 YYYY-MM-DD */
static void split_csv_fields(const char *line, char fields[][MAX_FIELD], size_t max_fields, size_t *out_fields); /* 基础 CSV 分割 */

/* 原子写入文件（写临时文件再重命名） */
static int atomic_save_text(const char *filename, const char *content);

/* 文件读写 */
static void load_books(void);
static void save_books(void);
static void load_records(void);
static void save_records(void);

/* 核心业务操作 */
static int next_book_id(void);
static Book *find_book_by_id(int id);
static int find_book_index_by_id(int id);

static void add_book(void);
static void delete_book(void);
static void list_books(void);
static void search_books(void);
static void borrow_book(void);
static void return_book(void);
static void list_records(void);

/* 资源释放 */
static void free_all(void);

/* ----------------------------- 实现：内存与字符串 ----------------------------- */

/* xmalloc/xrealloc
 *  - 在内存分配失败时打印错误并以非零状态退出，避免返回 NULL 导致后续未定义行为。
 */
static void *xmalloc(size_t n) {
    void *p = malloc(n);
    if (!p) {
        fprintf(stderr, "内存分配失败\n");
        exit(EXIT_FAILURE);
    }
    return p;
}

static void *xrealloc(void *p, size_t n) {
    void *q = realloc(p, n);
    if (!q) {
        fprintf(stderr, "内存重分配失败\n");
        free(p);
        exit(EXIT_FAILURE);
    }
    return q;
}

/* chomp：移除字符串末尾的 '\n' 和 '\r'（如果存在），以便安全地处理 fgets 返回的数据 */
static void chomp(char *s) {
    size_t len;
    if (!s) return;
    len = strlen(s);
    while (len > 0) {
        if (s[len - 1] == '\n' || s[len - 1] == '\r') s[--len] = '\0';
        else break;
    }
}

/* safe_strncpy：确保目标缓冲以 NUL 结尾，防止 strncpy 的非终止情况 */
static void safe_strncpy(char *dst, const char *src, size_t dstsize) {
    if (dstsize == 0) return;
    if (!src) { dst[0] = '\0'; return; }
    strncpy(dst, src, dstsize - 1);
    dst[dstsize - 1] = '\0';
}

/* ----------------------------- 动态数组容量管理 ----------------------------- */

/* 初始容量取 32，以减少频繁 realloc；容量以 2 倍增长策略扩展 */
static void ensure_books_capacity(void) {
    if (books_capacity == 0) {
        books_capacity = 32;
        books = (Book *)xmalloc(sizeof(Book) * books_capacity);
    } else if (books_count >= books_capacity) {
        books_capacity *= 2;
        books = (Book *)xrealloc(books, sizeof(Book) * books_capacity);
    }
}

static void ensure_records_capacity(void) {
    if (records_capacity == 0) {
        records_capacity = 32;
        records = (BorrowRecord *)xmalloc(sizeof(BorrowRecord) * records_capacity);
    } else if (records_count >= records_capacity) {
        records_capacity *= 2;
        records = (BorrowRecord *)xrealloc(records, sizeof(BorrowRecord) * records_capacity);
    }
}

/* ----------------------------- 日期与 CSV 解析 ----------------------------- */

/* today：写入当前本地日期（格式 YYYY-MM-DD）到 out，outlen 必须足够（建议 >= 11） */
static void today(char *out, size_t outlen) {
    time_t t = time(NULL);
    struct tm tm_buf;
    struct tm *tm_ptr;
    tm_ptr = localtime(&t);
    if (!tm_ptr) {
        safe_strncpy(out, "1970-01-01", outlen);
        return;
    }
    tm_buf = *tm_ptr;
    snprintf(out, outlen, "%04d-%02d-%02d", tm_buf.tm_year + 1900, tm_buf.tm_mon + 1, tm_buf.tm_mday);
}

/* split_csv_fields
 *  - 将一行按逗号分割到预分配的 fields[][] 中。
 *  - 不支持带引号、转义或字段内逗号。每个字段长度被截断到 MAX_FIELD-1。
 *  - out_fields 返回实际分割得到的字段数量（可能小于 max_fields）。
 */
static void split_csv_fields(const char *line, char fields[][MAX_FIELD], size_t max_fields, size_t *out_fields) {
    size_t i = 0;
    const char *p = line;
    const char *start;
    size_t len;
    *out_fields = 0;
    while (*p && i < max_fields) {
        start = p;
        /* 查找字段结束（逗号或字符串末尾） */
        while (*p && *p != ',') p++;
        len = (size_t)(p - start);
        if (len >= MAX_FIELD) len = MAX_FIELD - 1;
        if (len > 0) {
            memcpy(fields[i], start, len);
        }
        fields[i][len] = '\0';
        if (*p == ',') p++; /* 跳过分隔符，进入下字段 */
        i++;
    }
    *out_fields = i;
}

/* ----------------------------- 原子写入文本 ----------------------------- */

/* atomic_save_text
 *  - 将 content 写入 filename 的临时文件，然后用 rename 原子替换目标文件（跨平台注意：rename 行为在某些平台可能不同）。
 *  - 返回 1 表示成功，0 表示失败（并打印消息）。
 */
static int atomic_save_text(const char *filename, const char *content) {
    char tmpname[512];
    FILE *f;
    size_t len;
    /* 构造临时文件名（简单拼接后缀） */
    strncpy(tmpname, filename, sizeof(tmpname) - 1);
    tmpname[sizeof(tmpname) - 1] = '\0';
    strncat(tmpname, TMP_SUFFIX, sizeof(tmpname) - strlen(tmpname) - 1);
    f = fopen(tmpname, "w");
    if (!f) {
        fprintf(stderr, "无法打开临时文件 %s 写入\n", tmpname);
        return 0;
    }
    len = strlen(content);
    if (len > 0) {
        if (fwrite(content, 1, len, f) != len) {
            fprintf(stderr, "写入临时文件失败\n");
            fclose(f);
            remove(tmpname);
            return 0;
        }
    }
    if (fclose(f) != 0) {
        fprintf(stderr, "关闭临时文件失败\n");
        remove(tmpname);
        return 0;
    }
    /* 尝试删除目标（若存在），然后重命名临时文件为目标名 */
    remove(filename); /* 忽略返回值：目标可能不存在 */
    if (rename(tmpname, filename) != 0) {
        fprintf(stderr, "重命名临时文件失败\n"); /* 此时临时文件已保留，可用于排查 */
        remove(tmpname);
        return 0;
    }
    return 1;
}

/* ----------------------------- 文件读写实现 ----------------------------- */

/* load_books
 *  - 从 BOOKS_CSV 读入所有行并解析为 Book 结构，做基本字段合法性检查后加入内存数组。
 *  - 忽略空行或格式不完整的行；读取完成后关闭文件。
 */
static void load_books(void) {
    FILE *f = fopen(BOOKS_CSV, "r");
    char line[MAX_LINE];
    if (!f) {
        /* 文件不存在，视为空集合 */
        return;
    }
    while (fgets(line, sizeof(line), f)) {
        char fields[8][MAX_FIELD];
        size_t nfields;
        Book b;
        int ok = 0;
        chomp(line);
        if (line[0] == '\0') continue; /* 跳过空行 */
        split_csv_fields(line, fields, 8, &nfields);
        if (nfields < 5) continue; /* 字段不足，忽略该行 */
        /* 解析字段并做基本验证 */
        b.id = atoi(fields[0]);
        safe_strncpy(b.title, fields[1], sizeof(b.title));
        safe_strncpy(b.author, fields[2], sizeof(b.author));
        b.total = atoi(fields[3]);
        b.available = atoi(fields[4]);
        /* 验证：id > 0，total >= 0，0 <= available <= total */
        if (b.id > 0 && b.total >= 0 && b.available >= 0 && b.available <= b.total) ok = 1;
        if (ok) {
            ensure_books_capacity();
            books[books_count++] = b;
        }
    }
    if (fclose(f) != 0) {
        fprintf(stderr, "关闭文件 %s 时出错\n", BOOKS_CSV);
    }
}

/* save_books
 *  - 将当前内存中所有 Book 记录序列化为文本（一次性构建到内存缓冲），然后通过 atomic_save_text 写入磁盘。
 */
static void save_books(void) {
    size_t i;
    size_t cap = books_count * 256 + 1024;
    char *buf = (char *)xmalloc(cap);
    size_t pos = 0;
    for (i = 0; i < books_count; i++) {
        Book *b = &books[i];
        int needed;
        /* 计算格式化后长度并在必要时扩容 */
        needed = snprintf(NULL, 0, "%d,%s,%s,%d,%d\n", b->id, b->title, b->author, b->total, b->available);
        if (pos + (size_t)needed + 1 > cap) {
            cap = (cap + (size_t)needed + 1024) * 2;
            buf = (char *)xrealloc(buf, cap);
        }
        snprintf(buf + pos, cap - pos, "%d,%s,%s,%d,%d\n", b->id, b->title, b->author, b->total, b->available);
        pos += (size_t)needed;
    }
    if (!atomic_save_text(BOOKS_CSV, buf)) {
        fprintf(stderr, "保存 %s 失败\n", BOOKS_CSV);
    }
    free(buf);
}

/* load_records
 *  - 从 BORROW_CSV 读入借阅记录，解析字段并进行基本合法性检查后加载到内存数组。
 */
static void load_records(void) {
    FILE *f = fopen(BORROW_CSV, "r");
    char line[MAX_LINE];
    if (!f) return;
    while (fgets(line, sizeof(line), f)) {
        char fields[8][MAX_FIELD];
        size_t nfields;
        BorrowRecord r;
        int ok = 0;
        chomp(line);
        if (line[0] == '\0') continue;
        split_csv_fields(line, fields, 8, &nfields);
        if (nfields < 4) continue;
        r.borrower_id = atoi(fields[0]);
        r.book_id = atoi(fields[1]);
        safe_strncpy(r.borrow_date, fields[2], sizeof(r.borrow_date));
        safe_strncpy(r.return_date, fields[3], sizeof(r.return_date));
        /* 验证：borrower_id>0, book_id>0, borrow_date 非空 */
        if (r.borrower_id > 0 && r.book_id > 0 && r.borrow_date[0] != '\0') ok = 1;
        if (ok) {
            ensure_records_capacity();
            records[records_count++] = r;
        }
    }
    if (fclose(f) != 0) {
        fprintf(stderr, "关闭文件 %s 时出错\n", BORROW_CSV);
    }
}

/* save_records
 *  - 将内存借阅记录序列化并原子写入磁盘。
 */
static void save_records(void) {
    size_t i;
    size_t cap = records_count * 128 + 512;
    char *buf = (char *)xmalloc(cap);
    size_t pos = 0;
    for (i = 0; i < records_count; i++) {
        BorrowRecord *r = &records[i];
        int needed;
        needed = snprintf(NULL, 0, "%d,%d,%s,%s\n", r->borrower_id, r->book_id, r->borrow_date, r->return_date[0] ? r->return_date : "");
        if (pos + (size_t)needed + 1 > cap) {
            cap = (cap + (size_t)needed + 512) * 2;
            buf = (char *)xrealloc(buf, cap);
        }
        snprintf(buf + pos, cap - pos, "%d,%d,%s,%s\n", r->borrower_id, r->book_id, r->borrow_date, r->return_date[0] ? r->return_date : "");
        pos += (size_t)needed;
    }
    if (!atomic_save_text(BORROW_CSV, buf)) {
        fprintf(stderr, "保存 %s 失败\n", BORROW_CSV);
    }
    free(buf);
}

/* ----------------------------- 查询与业务逻辑 ----------------------------- */

/* next_book_id：返回比当前最大 id 大 1 的值，保证新书 id 唯一（相对简单的自增策略） */
static int next_book_id(void) {
    size_t i;
    int max = 0;
    for (i = 0; i < books_count; i++) {
        if (books[i].id > max) max = books[i].id;
    }
    return max + 1;
}

/* 根据 id 查找 Book 指针（找不到返回 NULL） */
static Book *find_book_by_id(int id) {
    size_t i;
    for (i = 0; i < books_count; i++) {
        if (books[i].id == id) return &books[i];
    }
    return NULL;
}

/* 根据 id 查找数组下标（找不到返回 -1） */
static int find_book_index_by_id(int id) {
    size_t i;
    for (i = 0; i < books_count; i++) {
        if (books[i].id == id) return (int)i;
    }
    return -1;
}

/* add_book：从 stdin 读取书名、作者和总册数，校验并加入内存，然后保存到磁盘 */
static void add_book(void) {
    char line[MAX_LINE];
    char title[MAX_FIELD];
    char author[MAX_FIELD];
    int total = 0;
    printf("输入书名: ");
    if (!fgets(line, sizeof(line), stdin)) return;
    chomp(line);
    safe_strncpy(title, line, sizeof(title));
    if (title[0] == '\0') { printf("书名不能为空\n"); return; }
    printf("输入作者: ");
    if (!fgets(line, sizeof(line), stdin)) return;
    chomp(line);
    safe_strncpy(author, line, sizeof(author));
    if (author[0] == '\0') { printf("作者不能为空\n"); return; }
    printf("输入总册数(正整数): ");
    if (!fgets(line, sizeof(line), stdin)) return;
    chomp(line);
    total = atoi(line);
    if (total <= 0) { printf("数量必须为正整数\n"); return; }
    ensure_books_capacity();
    Book b;
    b.id = next_book_id();
    safe_strncpy(b.title, title, sizeof(b.title));
    safe_strncpy(b.author, author, sizeof(b.author));
    b.total = total;
    b.available = total;
    books[books_count++] = b;
    save_books();
    printf("已添加: ID=%d\n", b.id);
}

/* delete_book：按 id 删除图书。删除前检查是否有未归还的借阅记录以避免数据不一致 */
static void delete_book(void) {
    char line[MAX_LINE];
    int id;
    int idx;
    size_t i;
    printf("输入要删除的图书 ID: ");
    if (!fgets(line, sizeof(line), stdin)) return;
    chomp(line);
    id = atoi(line);
    if (id <= 0) { printf("无效 ID\n"); return; }
    for (i = 0; i < records_count; i++) {
        if (records[i].book_id == id && records[i].return_date[0] == '\0') {
            printf("该书有未归还记录，不能删除。\n");
            return;
        }
    }
    idx = find_book_index_by_id(id);
    if (idx < 0) { printf("未找到 ID=%d 的图书。\n", id); return; }
    /* 移除元素并紧凑数组 */
    for (; (size_t)idx + 1 < books_count; idx++) books[idx] = books[idx + 1];
    books_count--;
    save_books();
    printf("已删除 ID=%d\n", id);
}

/* list_books：列出内存中所有图书信息（紧凑表格形式） */
static void list_books(void) {
    size_t i;
    printf("ID\t可借/总数\t作者\t标题\n");
    for (i = 0; i < books_count; i++) {
        Book *b = &books[i];
        printf("%d\t%d/%d\t%s\t%s\n", b->id, b->available, b->total, b->author, b->title);
    }
}

/* search_books：支持按 ID 精确查找或按标题子串匹配（大小写敏感） */
static void search_books(void) {
    char line[MAX_LINE];
    size_t i;
    printf("输入 ID 或 标题关键字: ");
    if (!fgets(line, sizeof(line), stdin)) return;
    chomp(line);
    if (line[0] == '\0') return;
    if (atoi(line) > 0) {
        int id = atoi(line);
        Book *b = find_book_by_id(id);
        if (b) {
            printf("找到: ID=%d, 标题=%s, 作者=%s, 可借=%d, 总=%d\n", b->id, b->title, b->author, b->available, b->total);
        } else {
            printf("未找到 ID=%d 的图书。\n", id);
        }
        return;
    }
    printf("搜索结果:\n");
    for (i = 0; i < books_count; i++) {
        if (strstr(books[i].title, line) != NULL) {
            Book *b = &books[i];
            printf("ID=%d 标题=%s 作者=%s 可借=%d 总=%d\n", b->id, b->title, b->author, b->available, b->total);
        }
    }
}

/* borrow_book：记录借书操作
 *  - 校验 borrower_id 与 book_id（均为正整数）
 *  - 校验图书存在且有可借副本
 *  - 创建借阅记录并减少 available，随后保存到磁盘
 */
static void borrow_book(void) {
    char line[MAX_LINE];
    int borrower_id;
    int book_id;
    size_t i;
    printf("借书人 ID: ");
    if (!fgets(line, sizeof(line), stdin)) return;
    chomp(line);
    borrower_id = atoi(line);
    if (borrower_id <= 0) { printf("无效的借书人 ID\n"); return; }
    printf("图书 ID: ");
    if (!fgets(line, sizeof(line), stdin)) return;
    chomp(line);
    book_id = atoi(line);
    if (book_id <= 0) { printf("无效的图书 ID\n"); return; }
    Book *b = find_book_by_id(book_id);
    if (!b) { printf("未找到图书 ID=%d\n", book_id); return; }
    if (b->available <= 0) { printf("无可用副本。\n"); return; }
    ensure_records_capacity();
    BorrowRecord r;
    r.borrower_id = borrower_id;
    r.book_id = book_id;
    today(r.borrow_date, sizeof(r.borrow_date));
    r.return_date[0] = '\0';
    records[records_count++] = r;
    b->available -= 1;
    save_books();
    save_records();
    printf("借阅成功: 借书人 %d 借走 图书 %d\n", borrower_id, book_id);
    /* 备注：当前实现允许同一借书人多次借相同书（形成多条记录），如需限制可在此处添加检查逻辑 */
    for (i = 0; i < records_count; i++) { (void)i; } /* 占位，便于未来扩展 */
}

/* return_book：记录还书操作
 *  - 根据借书人 ID 与图书 ID，从最近的未归还记录开始向前查找并标记归还日期
 *  - 同步更新图书的 available 字段（但不会使其超过 total）
 */
static void return_book(void) {
    char line[MAX_LINE];
    int borrower_id;
    int book_id;
    int i;
    printf("借书人 ID: ");
    if (!fgets(line, sizeof(line), stdin)) return;
    chomp(line);
    borrower_id = atoi(line);
    if (borrower_id <= 0) { printf("无效的借书人 ID\n"); return; }
    printf("图书 ID: ");
    if (!fgets(line, sizeof(line), stdin)) return;
    chomp(line);
    book_id = atoi(line);
    if (book_id <= 0) { printf("无效的图书 ID\n"); return; }
    for (i = (int)records_count - 1; i >= 0; i--) {
        if (records[i].borrower_id == borrower_id && records[i].book_id == book_id && records[i].return_date[0] == '\0') {
            today(records[i].return_date, sizeof(records[i].return_date));
            Book *b = find_book_by_id(book_id);
            if (b) {
                if (b->available < b->total) b->available += 1;
            }
            save_books();
            save_records();
            printf("还书成功: 借书人 %d 归还 图书 %d\n", borrower_id, book_id);
            return;
        }
    }
    printf("未找到匹配的未归还记录。\n");
}

/* list_records：按照添加顺序列出所有借阅记录，未归还的 return_date 显示为 '-' */
static void list_records(void) {
    size_t i;
    printf("借书人\t图书ID\t借出日期\t归还日期\n");
    for (i = 0; i < records_count; i++) {
        BorrowRecord *r = &records[i];
        printf("%d\t%d\t%s\t%s\n", r->borrower_id, r->book_id, r->borrow_date, r->return_date[0] ? r->return_date : "-");
    }
}

/* ----------------------------- 资源释放 ----------------------------- */

/* free_all：释放由程序分配的所有动态内存，并重置计数与容量 */
static void free_all(void) {
    if (books) {
        free(books);
        books = NULL;
    }
    books_count = books_capacity = 0;
    if (records) {
        free(records);
        records = NULL;
    }
    records_count = records_capacity = 0;
}

/* ----------------------------- 主程序与菜单 ----------------------------- */

static void print_menu(void) {
    printf("\n图书馆管理\n");
    printf("1. 添加图书\n");
    printf("2. 删除图书\n");
    printf("3. 列出所有图书\n");
    printf("4. 查询图书\n");
    printf("5. 借书\n");
    printf("6. 还书\n");
    printf("7. 列出借阅记录\n");
    printf("8. 保存并退出\n");
    printf("请选择(1-8): ");
}

int main(void) {
    char line[MAX_LINE];
    load_books();
    load_records();
    for (;;) {
        print_menu();
        if (!fgets(line, sizeof(line), stdin)) break;
        chomp(line);
        switch (atoi(line)) {
            case 1: add_book(); break;
            case 2: delete_book(); break;
            case 3: list_books(); break;
            case 4: search_books(); break;
            case 5: borrow_book(); break;
            case 6: return_book(); break;
            case 7: list_records(); break;
            case 8:
                save_books();
                save_records();
                free_all();
                printf("保存完成，退出。\n");
                return 0;
            default:
                printf("无效选择。\n");
        }
    }
    /* 程序被中断或 EOF，尽量保存并释放资源后退出 */
    save_books();
    save_records();
    free_all();
    return 0;
}
