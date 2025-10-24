#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>
#include <ctype.h>

sqlite3 *db;  // SQLite数据库连接对象

// 回调函数，执行查询时会调用
static int callback(void *data, int argc, char **argv, char **azColName) {
    int i;
    for (i = 0; i < argc; i++) {
        printf("%s = %s\n", azColName[i], argv[i] ? argv[i] : "NULL");
    }
    return 0;
}

// 检查字符串是否是有效的数字
int is_valid_double(const char *str) {
    if (str == NULL || *str == '\0') {
        return 0;
    }
    char *endptr;
    strtod(str, &endptr);
    return *endptr == '\0';  // 检查是否完全转换为数字
}

// 检查日期格式（YYYY-MM-DD）
int is_valid_date(const char *date) {
    if (strlen(date) != 10) return 0;
    if (date[4] != '-' || date[7] != '-') return 0;

    for (int i = 0; i < 10; i++) {
        if (i == 4 || i == 7) continue;
        if (!isdigit(date[i])) return 0;
    }
    return 1;
}

// 初始化数据库
int init_db() {
    int rc = sqlite3_open("finance.db", &db);  // 打开/创建数据库
    if (rc) {
        printf("Can't open database: %s\n", sqlite3_errmsg(db));
        return rc;
    }

    // 创建表格，如果表格不存在
    const char *create_table_sql = "CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, amount REAL, description TEXT, date TEXT);";
    char *err_msg = 0;
    rc = sqlite3_exec(db, create_table_sql, 0, 0, &err_msg);
    if (rc != SQLITE_OK) {
        printf("SQL error: %s\n", err_msg);
        sqlite3_free(err_msg);
        return rc;
    }
    return SQLITE_OK;
}

// 添加记录
int add_record(const char *type, double amount, const char *description, const char *date) {
    const char *insert_sql = "INSERT INTO records (type, amount, description, date) VALUES (?, ?, ?, ?);";
    sqlite3_stmt *stmt;
    int rc = sqlite3_prepare_v2(db, insert_sql, -1, &stmt, 0);
    if (rc != SQLITE_OK) {
        printf("Failed to prepare statement: %s\n", sqlite3_errmsg(db));
        return rc;
    }

    sqlite3_bind_text(stmt, 1, type, -1, SQLITE_STATIC);
    sqlite3_bind_double(stmt, 2, amount);
    sqlite3_bind_text(stmt, 3, description, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 4, date, -1, SQLITE_STATIC);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        printf("Execution failed: %s\n", sqlite3_errmsg(db));
    }

    sqlite3_finalize(stmt);
    return rc;
}

// 删除记录
int delete_record(int id) {
    const char *delete_sql = "DELETE FROM records WHERE id = ?;";
    sqlite3_stmt *stmt;
    int rc = sqlite3_prepare_v2(db, delete_sql, -1, &stmt, 0);
    if (rc != SQLITE_OK) {
        printf("Failed to prepare statement: %s\n", sqlite3_errmsg(db));
        return rc;
    }

    sqlite3_bind_int(stmt, 1, id);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        printf("Execution failed: %s\n", sqlite3_errmsg(db));
    }

    sqlite3_finalize(stmt);
    return rc;
}

// 更新记录
int update_record(int id, const char *type, double amount, const char *description, const char *date) {
    const char *update_sql = "UPDATE records SET type = ?, amount = ?, description = ?, date = ? WHERE id = ?;";
    sqlite3_stmt *stmt;
    int rc = sqlite3_prepare_v2(db, update_sql, -1, &stmt, 0);
    if (rc != SQLITE_OK) {
        printf("Failed to prepare statement: %s\n", sqlite3_errmsg(db));
        return rc;
    }

    sqlite3_bind_text(stmt, 1, type, -1, SQLITE_STATIC);
    sqlite3_bind_double(stmt, 2, amount);
    sqlite3_bind_text(stmt, 3, description, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 4, date, -1, SQLITE_STATIC);
    sqlite3_bind_int(stmt, 5, id);

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        printf("Execution failed: %s\n", sqlite3_errmsg(db));
    }

    sqlite3_finalize(stmt);
    return rc;
}

// 查询记录
int query_records() {
    const char *select_sql = "SELECT * FROM records;";
    char *err_msg = 0;
    int rc = sqlite3_exec(db, select_sql, callback, 0, &err_msg);
    if (rc != SQLITE_OK) {
        printf("SQL error: %s\n", err_msg);
        sqlite3_free(err_msg);
    }
    return rc;
}

// 根据金额范围查询记录
int query_by_amount_range(double min_amount, double max_amount) {
    sqlite3_stmt *stmt;
    const char *select_sql = "SELECT * FROM records WHERE amount BETWEEN ? AND ?;";
    int rc = sqlite3_prepare_v2(db, select_sql, -1, &stmt, 0);
    if (rc != SQLITE_OK) {
        printf("Failed to prepare statement: %s\n", sqlite3_errmsg(db));
        return rc;
    }

    sqlite3_bind_double(stmt, 1, min_amount);
    sqlite3_bind_double(stmt, 2, max_amount);

    rc = sqlite3_step(stmt);
    while (rc == SQLITE_ROW) {
        printf("ID: %d, Type: %s, Amount: %.2f, Description: %s, Date: %s\n",
               sqlite3_column_int(stmt, 0),
               sqlite3_column_text(stmt, 1),
               sqlite3_column_double(stmt, 2),
               sqlite3_column_text(stmt, 3),
               sqlite3_column_text(stmt, 4));
        rc = sqlite3_step(stmt);
    }

    sqlite3_finalize(stmt);
    return rc;
}

int main() {
    if (init_db() != SQLITE_OK) {
        return 1; // 初始化数据库失败
    }

    int choice;
    do {
        printf("\n=== 财务管理系统 ===\n");
        printf("1. 添加记录\n");
        printf("2. 删除记录\n");
        printf("3. 更新记录\n");
        printf("4. 查询所有记录\n");
        printf("5. 查询按金额范围\n");
        printf("6. 退出\n");
        printf("请选择操作: ");
        scanf("%d", &choice);

        if (choice == 1) {
            char type[10], description[100], date[20];
            double amount;
            printf("请输入记录类型（收入/支出）: ");
            scanf("%s", type);
            printf("请输入金额: ");
            while (1) {
                char amount_str[20];
                scanf("%s", amount_str);
                if (is_valid_double(amount_str)) {
                    amount = atof(amount_str);
                    break;
                } else {
                    printf("无效的金额，请重新输入: ");
                }
            }

            printf("请输入描述: ");
            getchar();  // 清除缓冲区的换行符
            fgets(description, 100, stdin);
            description[strcspn(description, "\n")] = '\0';  // 去掉换行符

            printf("请输入日期 (格式: YYYY-MM-DD): ");
            while (1) {
                scanf("%s", date);
                if (is_valid_date(date)) {
                    break;
                } else {
                    printf("无效的日期格式，请重新输入: ");
                }
            }

            add_record(type, amount, description, date);
        }
        else if (choice == 2) {
            int id;
            printf("请输入要删除的记录ID: ");
            scanf("%d", &id);
            delete_record(id);
        }
        else if (choice == 3) {
            int id;
            char type[10], description[100], date[20];
            double amount;
            printf("请输入要更新的记录ID: ");
            scanf("%d", &id);
            printf("请输入新的记录类型（收入/支出）: ");
            scanf("%s", type);
            printf("请输入新的金额: ");
            while (1) {
                char amount_str[20];
                scanf("%s", amount_str);
                if (is_valid_double(amount_str)) {
                    amount = atof(amount_str);
                    break;
                } else {
                    printf("无效的金额，请重新输入: ");
                }
            }

            printf("请输入新的描述: ");
            getchar();
            fgets(description, 100, stdin);
            description[strcspn(description, "\n")] = '\0';
            printf("请输入新的日期: ");
            while (1) {
                scanf("%s", date);
                if (is_valid_date(date)) {
                    break;
                } else {
                    printf("无效的日期格式，请重新输入: ");
                }
            }

            update_record(id, type, amount, description, date);
        }
        else if (choice == 4) {
            query_records();
        }
        else if (choice == 5) {
            double min_amount, max_amount;
            printf("请输入最小金额: ");
            scanf("%lf", &min_amount);
            printf("请输入最大金额: ");
            scanf("%lf", &max_amount);

            query_by_amount_range(min_amount, max_amount);
        }

    } while (choice != 6);

    sqlite3_close(db);  // 关闭数据库连接
    return 0;
}
