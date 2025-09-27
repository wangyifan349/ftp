// win_threads_full_example.c
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct {
    int start;
    int step;
    int id;
} ThreadArg;

CRITICAL_SECTION cs;
int shared_counter = 0;

DWORD WINAPI worker(LPVOID lpParam) {
    ThreadArg *a = (ThreadArg *)lpParam;
    for (int i = 0; i < 10; ++i) {
        int val = a->start + i * a->step;
        EnterCriticalSection(&cs);
        shared_counter += 1;
        printf("Thread %d: computed %d, shared_counter=%d\n", a->id, val, shared_counter);
        LeaveCriticalSection(&cs);
        Sleep(100);
    }
    return 0;
}

int main(void) {
    ThreadArg *a1 = (ThreadArg *)malloc(sizeof(ThreadArg));
    ThreadArg *a2 = (ThreadArg *)malloc(sizeof(ThreadArg));
    if (!a1 || !a2) return 1;
    a1->start = 0; a1->step = 1; a1->id = 1;
    a2->start = 100; a2->step = 3; a2->id = 2;

    InitializeCriticalSection(&cs);

    HANDLE h1 = CreateThread(NULL, 0, worker, a1, 0, NULL);
    if (h1 == NULL) { DeleteCriticalSection(&cs); free(a1); free(a2); return 1; }
    HANDLE h2 = CreateThread(NULL, 0, worker, a2, 0, NULL);
    if (h2 == NULL) { TerminateThread(h1, 0); CloseHandle(h1); DeleteCriticalSection(&cs); free(a1); free(a2); return 1; }

    WaitForSingleObject(h1, INFINITE);
    WaitForSingleObject(h2, INFINITE);

    CloseHandle(h1);
    CloseHandle(h2);

    DeleteCriticalSection(&cs);

    printf("Final shared_counter=%d\n", shared_counter);

    free(a1);
    free(a2);
    return 0;
}
