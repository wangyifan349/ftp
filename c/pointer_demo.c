#include <stdio.h>
#include <stdlib.h>

void pointerBasics() {
    // 基本指针操作
    int a = 10;
    int *ptr = &a;  // ptr指向a的地址

    printf("Pointer Basics:\n");
    printf("Value of a: %d\n", a);
    printf("Address of a: %p\n", &a);
    printf("Pointer ptr points to address: %p\n", ptr);
    printf("Value pointed to by ptr: %d\n", *ptr);  // 解引用，输出a的值
}

void pointerArray() {
    // 指针与数组
    int arr[] = {1, 2, 3, 4, 5};
    int *ptr = arr;  // 数组名就是指向数组首元素的指针

    printf("\nPointer with Array:\n");
    printf("Array elements accessed using pointer arithmetic:\n");
    for (int i = 0; i < 5; i++) {
        printf("%d ", *(ptr + i));  // 通过指针偏移访问数组元素
    }
    printf("\n");
}

void pointerAndFunction() {
    // 指针作为函数参数
    int a = 10;
    printf("\nPointer as Function Argument:\n");
    printf("Before change: %d\n", a);
    
    // 修改函数传入的值
    void changeValue(int *p) {
        *p = 20;  // 解引用并修改指向的值
    }
    changeValue(&a);  // 传递a的地址给函数
    printf("After change: %d\n", a);
}

void dynamicMemoryAllocation() {
    // 动态内存分配和释放
    printf("\nDynamic Memory Allocation:\n");
    
    // 动态分配一个整数的内存
    int *ptr = (int*) malloc(sizeof(int));  // 使用malloc分配内存
    if (ptr == NULL) {
        printf("Memory allocation failed\n");
        return;
    }
    
    *ptr = 100;  // 给动态分配的内存赋值
    printf("Dynamically allocated value: %d\n", *ptr);

    free(ptr);  // 释放动态分配的内存
    printf("Memory freed.\n");
}

void pointerErrors() {
    // 常见的指针错误：空指针和野指针
    int *ptr = NULL;  // 空指针
    printf("\nPointer Errors:\n");
    
    // 处理空指针
    if (ptr != NULL) {
        printf("Dereferencing ptr: %d\n", *ptr);  // 只有ptr非空时才解引用
    } else {
        printf("ptr is NULL, cannot dereference.\n");
    }

    // 野指针示例
    int a = 10;
    int *wildPtr = &a;
    free(wildPtr);  // 错误：释放一个局部变量的指针会导致野指针
    // 现在wildPtr是野指针，解引用会导致未定义行为
    // printf("Dereferencing wild pointer: %d\n", *wildPtr); // 错误：可能崩溃
}

void pointerArithmetic() {
    // 指针运算
    int arr[] = {10, 20, 30, 40, 50};
    int *ptr = arr;

    printf("\nPointer Arithmetic:\n");
    printf("First element: %d\n", *ptr);
    ptr++;  // 指针加1，指向下一个元素
    printf("Second element: %d\n", *ptr);
    ptr += 2;  // 指针加2，指向第三个元素
    printf("Fourth element: %d\n", *ptr);
}

int main() {
    pointerBasics();         // 演示基本的指针操作
    pointerArray();          // 演示指针与数组结合
    pointerAndFunction();    // 演示指针作为函数参数
    dynamicMemoryAllocation(); // 演示动态内存分配和释放
    pointerErrors();         // 演示指针错误处理
    pointerArithmetic();     // 演示指针运算

    return 0;
}
