/*
  finance_sqlite.c
  简单财务管理（SQLite 持久化）
  编译：gcc finance_sqlite.c -o finance_sqlite -lsqlite3
  运行：./finance_sqlite
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sqlite3.h>

#define MAX_TYPE_LEN 32
#define MAX_NOTE_LEN 128
#define LINE_BUF 256
#define DB_FILE "finance.db"

/* 辅助：安全读取一行，去掉换行 */
static void read_line(char *buf, size_t sz) {
    if (!fgets(buf, (int)sz, stdin)) {
        buf[0] = '\0';
        return;
    }
    size_t len = strlen(buf);
    if (len > 0 && buf[len - 1] == '\n') buf[len - 1] = '\0';
}

/* 获取今天 YYYY-MM-DD */
static void today_str(char *buf, size_t sz) {
    time_t t = time(NULL);
    struct tm tm = *localtime(&t);
    snprintf(buf, sz, "%04d-%02d-%02d", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday);
}

/* 初始化数据库并创建表（如果不存在） */
static int db_init(sqlite3 **out_db) {
    sqlite3 *db = NULL;
    int rc = sqlite3_open(DB_FILE, &db);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "无法打开数据库: %s\n", sqlite3_errmsg(db));
        if (db) sqlite3_close(db);
        return 0;
    }
    const char *sql = "CREATE TABLE IF NOT EXISTS records ("
                      "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                      "date TEXT NOT NULL,"
                      "amount REAL NOT NULL,"
                      "type TEXT,"
                      "note TEXT"
                      ");";
    char *errmsg = NULL;
    rc = sqlite3_exec(db, sql, NULL, NULL, &errmsg);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "创建表失败: %s\n", errmsg ? errmsg : "unknown");
        sqlite3_free(errmsg);
        sqlite3_close(db);
        return 0;
    }
    *out_db = db;
    return 1;
}

/* 添加记录，使用预编译语句，返回新 id（>0 成功），失败返回 0 */
static int db_insert(sqlite3 *db, const char *date, double amount, const char *type, const char *note) {
    const char *sql = "INSERT INTO records(date, amount, type, note) VALUES(?, ?, ?, ?);";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "prepare failed: %s\n", sqlite3_errmsg(db));
        return 0;
    }
    sqlite3_bind_text(stmt, 1, date, -1, SQLITE_TRANSIENT);
    sqlite3_bind_double(stmt, 2, amount);
    sqlite3_bind_text(stmt, 3, type, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, note, -1, SQLITE_TRANSIENT);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        fprintf(stderr, "执行插入失败: %s\n", sqlite3_errmsg(db));
        sqlite3_finalize(stmt);
        return 0;
    }
    sqlite3_finalize(stmt);
    long long last_id = sqlite3_last_insert_rowid(db);
    return (int)last_id;
}

/* 删除记录，按 id，返回删除行数（0 表示未找到） */
static int db_delete(sqlite3 *db, int id) {
    const char *sql = "DELETE FROM records WHERE id = ?;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "prepare failed: %s\n", sqlite3_errmsg(db));
        return 0;
    }
    sqlite3_bind_int(stmt, 1, id);
    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        fprintf(stderr, "执行删除失败: %s\n", sqlite3_errmsg(db));
        sqlite3_finalize(stmt);
        return 0;
    }
    int changes = (int)sqlite3_changes(db);
    sqlite3_finalize(stmt);
    return changes;
}

/* 更新记录，按 id，返回 1 成功，0 失败或未找到 */
static int db_update(sqlite3 *db, int id, const char *date, double amount, const char *type, const char *note) {
    const char *sql = "UPDATE records SET date = ?, amount = ?, type = ?, note = ? WHERE id = ?;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "prepare failed: %s\n", sqlite3_errmsg(db));
        return 0;
    }
    sqlite3_bind_text(stmt, 1, date, -1, SQLITE_TRANSIENT);
    sqlite3_bind_double(stmt, 2, amount);
    sqlite3_bind_text(stmt, 3, type, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, note, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(stmt, 5, id);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        fprintf(stderr, "执行更新失败: %s\n", sqlite3_errmsg(db));
        sqlite3_finalize(stmt);
        return 0;
    }
    int changes = (int)sqlite3_changes(db);
    sqlite3_finalize(stmt);
    return changes > 0;
}

/* 列出所有记录 */
static void db_list_all(sqlite3 *db) {
    const char *sql = "SELECT id, date, amount, type, note FROM records ORDER BY date, id;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "prepare failed: %s\n", sqlite3_errmsg(db));
        return;
    }
    printf("ID   日期        金额        类型           备注\n");
    printf("---------------------------------------------------------------\n");
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        int id = sqlite3_column_int(stmt, 0);
        const unsigned char *date = sqlite3_column_text(stmt, 1);
        double amount = sqlite3_column_double(stmt, 2);
        const unsigned char *type = sqlite3_column_text(stmt, 3);
        const unsigned char *note = sqlite3_column_text(stmt, 4);
        printf("%-4d %-10s %10.2f   %-12s %s\n",
               id,
               date ? (const char*)date : "",
               amount,
               type ? (const char*)type : "",
               note ? (const char*)note : "");
    }
    if (rc != SQLITE_DONE) {
        fprintf(stderr, "查询失败: %s\n", sqlite3_errmsg(db));
    }
    sqlite3_finalize(stmt);
}

/* 按日期查询（精确匹配 YYYY-MM-DD） */
static void db_query_by_date(sqlite3 *db, const char *date) {
    const char *sql = "SELECT id, date, amount, type, note FROM records WHERE date = ? ORDER BY id;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "prepare failed: %s\n", sqlite3_errmsg(db));
        return;
    }
    sqlite3_bind_text(stmt, 1, date, -1, SQLITE_TRANSIENT);
    int found = 0;
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        if (!found) {
            printf("ID   日期        金额        类型           备注\n");
            printf("---------------------------------------------------------------\n");
            found = 1;
        }
        int id = sqlite3_column_int(stmt, 0);
        const unsigned char *dt = sqlite3_column_text(stmt, 1);
        double amount = sqlite3_column_double(stmt, 2);
        const unsigned char *type = sqlite3_column_text(stmt, 3);
        const unsigned char *note = sqlite3_column_text(stmt, 4);
        printf("%-4d %-10s %10.2f   %-12s %s\n",
               id,
               dt ? (const char*)dt : "",
               amount,
               type ? (const char*)type : "",
               note ? (const char*)note : "");
    }
    if (!found) printf("未找到指定日期的记录。\n");
    if (rc != SQLITE_DONE) fprintf(stderr, "查询失败: %s\n", sqlite3_errmsg(db));
    sqlite3_finalize(stmt);
}

/* 按类型模糊查询（LIKE %keyword%） */
static void db_query_by_type(sqlite3 *db, const char *keyword) {
    const char *sql = "SELECT id, date, amount, type, note FROM records WHERE type LIKE ? ORDER BY date, id;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "prepare failed: %s\n", sqlite3_errmsg(db));
        return;
    }
    /* 构造 %keyword% 安全地（不拼接到 SQL，使用 bind） */
    char likebuf[MAX_TYPE_LEN + 4];
    if (snprintf(likebuf, sizeof(likebuf), "%%%s%%", keyword) >= (int)sizeof(likebuf)) {
        /* 截断 keyword 保证安全 */
        likebuf[sizeof(likebuf)-1] = '\0';
    }
    sqlite3_bind_text(stmt, 1, likebuf, -1, SQLITE_TRANSIENT);
    int found = 0;
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        if (!found) {
            printf("ID   日期        金额        类型           备注\n");
            printf("---------------------------------------------------------------\n");
            found = 1;
        }
        int id = sqlite3_column_int(stmt, 0);
        const unsigned char *dt = sqlite3_column_text(stmt, 1);
        double amount = sqlite3_column_double(stmt, 2);
        const unsigned char *type = sqlite3_column_text(stmt, 3);
        const unsigned char *note = sqlite3_column_text(stmt, 4);
        printf("%-4d %-10s %10.2f   %-12s %s\n",
               id,
               dt ? (const char*)dt : "",
               amount,
               type ? (const char*)type : "",
               note ? (const char*)note : "");
    }
    if (!found) printf("未找到匹配类型的记录。\n");
    if (rc != SQLITE_DONE) fprintf(stderr, "查询失败: %s\n", sqlite3_errmsg(db));
    sqlite3_finalize(stmt);
}

/* 显示汇总（总余额、总收入、总支出） */
static void db_show_summary(sqlite3 *db) {
    const char *sql = "SELECT SUM(amount) as total, "
                      "SUM(CASE WHEN amount>0 THEN amount ELSE 0 END) as income, "
                      "SUM(CASE WHEN amount<0 THEN amount ELSE 0 END) as expense "
                      "FROM records;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) {
        fprintf(stderr, "prepare failed: %s\n", sqlite3_errmsg(db));
        return;
    }
    rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        double total = sqlite3_column_double(stmt, 0);
        double income = sqlite3_column_double(stmt, 1);
        double expense = sqlite3_column_double(stmt, 2);
        printf("总余额: %.2f， 总收入: %.2f， 总支出: %.2f\n", total, income, expense);
    } else {
        fprintf(stderr, "汇总查询失败: %s\n", sqlite3_errmsg(db));
    }
    sqlite3_finalize(stmt);
}

/* 检查记录是否存在（按 id），返回 1 存在，0 不存在 */
static int db_exists(sqlite3 *db, int id) {
    const char *sql = "SELECT 1 FROM records WHERE id = ? LIMIT 1;";
    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) return 0;
    sqlite3_bind_int(stmt, 1, id);
    rc = sqlite3_step(stmt);
    int exists = (rc == SQLITE_ROW) ? 1 : 0;
    sqlite3_finalize(stmt);
    return exists;
}

/* 主菜单 */
static void menu_loop(sqlite3 *db) {
    char line[LINE_BUF];
    while (1) {
        printf("\n--- 财务管理（SQLite）---\n");
        printf("1. 添加记录\n");
        printf("2. 删除记录（按ID）\n");
        printf("3. 修改记录（按ID）\n");
        printf("4. 显示所有记录\n");
        printf("5. 按日期查询\n        ");
        printf("6. 按类型查询\n");
        printf("7. 显示汇总\n");
        printf("8. 退出\n");
        printf("请选择(1-8): ");
        read_line(line, sizeof(line));
        int choice = atoi(line);
        if (choice == 1) {
            char date[16] = {0}, type[MAX_TYPE_LEN] = {0}, note[MAX_NOTE_LEN] = {0}, amt_str[64] = {0};
            today_str(date, sizeof(date));
            printf("日期 (YYYY-MM-DD, 默认 %s): ", date);
            read_line(line, sizeof(line));
            if (line[0]) {
                strncpy(date, line, sizeof(date)-1);
                date[sizeof(date)-1] = '\0';
            }
            printf("金额（正为收入，负为支出）: ");
            read_line(amt_str, sizeof(amt_str));
            double amt = atof(amt_str);
            printf("类型（例如：工资/餐饮）: ");
            read_line(type, sizeof(type));
            printf("备注: ");
            read_line(note, sizeof(note));
            int new_id = db_insert(db, date, amt, type, note);
            if (new_id > 0) printf("已添加，ID=%d\n", new_id);
            else printf("添加失败。\n");
        } else if (choice == 2) {
            printf("输入要删除的ID: ");
            read_line(line, sizeof(line));
            int id = atoi(line);
            if (id <= 0) { printf("无效的ID。\n"); continue; }
            int deleted = db_delete(db, id);
            if (deleted) printf("删除成功（%d 行）。\n", deleted);
            else printf("未找到ID=%d。\n", id);
        } else if (choice == 3) {
            printf("输入要修改的ID: ");
            read_line(line, sizeof(line));
            int id = atoi(line);
            if (id <= 0) { printf("无效的ID。\n"); continue; }
            if (!db_exists(db, id)) { printf("未找到ID=%d。\n", id); continue; }
            /* 读取当前记录以显示默认值 */
            const char *sel_sql = "SELECT date, amount, type, note FROM records WHERE id = ? LIMIT 1;";
            sqlite3_stmt *sel = NULL;
            if (sqlite3_prepare_v2(db, sel_sql, -1, &sel, NULL) != SQLITE_OK) {
                fprintf(stderr, "查询失败: %s\n", sqlite3_errmsg(db));
                if (sel) sqlite3_finalize(sel);
                continue;
            }
            sqlite3_bind_int(sel, 1, id);
            char cur_date[16] = {0}, cur_type[MAX_TYPE_LEN] = {0}, cur_note[MAX_NOTE_LEN] = {0};
            double cur_amount = 0.0;
            int rc = sqlite3_step(sel);
            if (rc == SQLITE_ROW) {
                const unsigned char *d = sqlite3_column_text(sel, 0);
                if (d) strncpy(cur_date, (const char*)d, sizeof(cur_date)-1);
                cur_amount = sqlite3_column_double(sel, 1);
                const unsigned char *t = sqlite3_column_text(sel, 2);
                if (t) strncpy(cur_type, (const char*)t, sizeof(cur_type)-1);
                const unsigned char *n = sqlite3_column_text(sel, 3);
                if (n) strncpy(cur_note, (const char*)n, sizeof(cur_note)-1);
            } else {
                printf("读取当前记录失败。\n");
                sqlite3_finalize(sel);
                continue;
            }
            sqlite3_finalize(sel);

            char date[16], type[MAX_TYPE_LEN], note[MAX_NOTE_LEN], amt_str[64];
            strncpy(date, cur_date, sizeof(date)-1);
            date[sizeof(date)-1] = '\0';
            printf("日期 (默认 %s): ", date);
            read_line(line, sizeof(line));
            if (line[0]) {
                strncpy(date, line, sizeof(date)-1);
                date[sizeof(date)-1] = '\0';
            }
            printf("金额 (当前 %.2f): ", cur_amount);
            read_line(amt_str, sizeof(amt_str));
            double amt = (amt_str[0]) ? atof(amt_str) : cur_amount;
            strncpy(type, cur_type, sizeof(type)-1);
            type[sizeof(type)-1] = '\0';
            printf("类型 (默认 %s): ", type);
            read_line(line, sizeof(line));
            if (line[0]) {
                strncpy(type, line, sizeof(type)-1);
                type[sizeof(type)-1] = '\0';
            }
            strncpy(note, cur_note, sizeof(note)-1);
            note[sizeof(note)-1] = '\0';
            printf("备注 (默认 %s): ", note);
            read_line(line, sizeof(line));
            if (line[0]) {
                strncpy(note, line, sizeof(note)-1);
                note[sizeof(note)-1] = '\0';
            }
            if (db_update(db, id, date, amt, type, note)) printf("修改成功。\n");
            else printf("修改失败或未改变。\n");
        } else if (choice == 4) {
            db_list_all(db);
        } else if (choice == 5) {
            char date[16];
            printf("输入日期 (YYYY-MM-DD): ");
            read_line(date, sizeof(date));
            if (!date[0]) { printf("无效日期。\n"); continue; }
            db_query_by_date(db, date);
        } else if (choice == 6) {
            char kw[MAX_TYPE_LEN];
            printf("输入类型关键字: ");
            read_line(kw, sizeof(kw));
            if (!kw[0]) { printf("关键字为空。\n"); continue; }
            db_query_by_type(db, kw);
        } else if (choice == 7) {
            db_show_summary(db);
        } else if (choice == 8) {
            printf("退出。\n");
            break;
        } else {
            printf("无效选择。\n");
        }
    }
}

int main(void) {
    sqlite3 *db = NULL;
    if (!db_init(&db)) {
        fprintf(stderr, "数据库初始化失败。\n");
        return EXIT_FAILURE;
    }
    menu_loop(db);
    if (db) sqlite3_close(db);
    return EXIT_SUCCESS;
}
