#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---------- 冒泡排序（Bubble Sort） ---------- */
/* 稳定，最坏/平均 O(n^2)，原地 */
void bubble_sort(int *a, int n){
    if(!a||n<=1) return;
    for(int i=0;i<n-1;++i){
        int swapped=0;
        for(int j=0;j<n-1-i;++j){
            if(a[j]>a[j+1]){int t=a[j];a[j]=a[j+1];a[j+1]=t;swapped=1;}
        }
        if(!swapped) break;
    }
}

/* ---------- 选择排序（Selection Sort） ---------- */
/* 不稳定，最坏/平均 O(n^2)，原地 */
void selection_sort(int *a,int n){
    if(!a||n<=1) return;
    for(int i=0;i<n-1;++i){
        int min_idx=i;
        for(int j=i+1;j<n;++j) if(a[j]<a[min_idx]) min_idx=j;
        if(min_idx!=i){int t=a[i];a[i]=a[min_idx];a[min_idx]=t;}
    }
}

/* ---------- 插入排序（Insertion Sort） ---------- */
/* 稳定，最好 O(n)，最坏 O(n^2)，原地 */
void insertion_sort(int *a,int n){
    if(!a||n<=1) return;
    for(int i=1;i<n;++i){
        int key=a[i],j=i-1;
        while(j>=0&&a[j]>key){a[j+1]=a[j];--j;}
        a[j+1]=key;
    }
}

/* ---------- 希尔排序（Shell Sort） ---------- */
/* 不稳定，改进的插入排序，视 gap 序列而定 */
void shell_sort(int *a,int n){
    if(!a||n<=1) return;
    for(int gap=n/2;gap>0;gap/=2){
        for(int i=gap;i<n;++i){
            int temp=a[i],j=i;
            while(j>=gap&&a[j-gap]>temp){a[j]=a[j-gap];j-=gap;}
            a[j]=temp;
        }
    }
}

/* ---------- 归并排序（Merge Sort） ---------- */
/* 稳定，O(n log n)，需要 O(n) 额外空间 */
/* 辅助：合并区间 [l..m] 和 [m+1..r] 到 tmp */
void merge_ranges(int *a,int l,int m,int r,int *tmp){
    int i=l,j=m+1,k=0;
    while(i<=m&&j<=r) tmp[k++]= (a[i]<=a[j])? a[i++]: a[j++];
    while(i<=m) tmp[k++]=a[i++]; while(j<=r) tmp[k++]=a[j++];
    memcpy(a+l,tmp,k*sizeof(int));
}
/* 递归顶层函数声明与实现 */
void merge_sort_rec(int *a,int l,int r,int *tmp){
    if(l>=r) return;
    int m=l+(r-l)/2;
    merge_sort_rec(a,l,m,tmp); merge_sort_rec(a,m+1,r,tmp); merge_ranges(a,l,m,r,tmp);
}
void merge_sort(int *a,int n){
    if(!a||n<=1) return;
    int *tmp=(int*)malloc(n*sizeof(int));
    if(!tmp) return;
    merge_sort_rec(a,0,n-1,tmp);
    free(tmp);
}

/* ---------- 快速排序（Quick Sort） ---------- */
/* 不稳定，平均 O(n log n)，递归实现，原地 */
/* 分区：以 a[high] 为基准，返回分界索引 */
int partition_qs(int *a,int low,int high){
    int pivot=a[high],i=low-1;
    for(int j=low;j<high;++j) if(a[j]<=pivot){++i;int t=a[i];a[i]=a[j];a[j]=t;}
    int t=a[i+1];a[i+1]=a[high];a[high]=t;
    return i+1;
}
void quick_sort_rec(int *a,int low,int high){
    if(low<high){
        int p=partition_qs(a,low,high);
        quick_sort_rec(a,low,p-1); quick_sort_rec(a,p+1,high);
    }
}
void quick_sort(int *a,int n){ if(!a||n<=1) return; quick_sort_rec(a,0,n-1); }

/* ---------- 堆排序（Heap Sort） ---------- */
/* 不稳定，O(n log n)，原地 */
/* 堆调整：以 i 为根，对长度 n 的堆进行下沉 */
void heapify(int *a,int n,int i){
    int largest=i;
    for(;;){
        int l=2*i+1,r=2*i+2;
        if(l<n&&a[l]>a[largest]) largest=l;
        if(r<n&&a[r]>a[largest]) largest=r;
        if(largest==i) break;
        int t=a[i];a[i]=a[largest];a[largest]=t;
        i=largest;
    }
}
void heap_sort(int *a,int n){
    if(!a||n<=1) return;
    for(int i=n/2-1;i>=0;--i) heapify(a,n,i);
    for(int i=n-1;i>0;--i){int t=a[0];a[0]=a[i];a[i]=t;heapify(a,i,0);}
}

/* ---------- 计数排序（Counting Sort） ---------- */
/* 稳定（实现中使用稳定方式），线性 O(n+k)，适合小范围整数 */
void counting_sort(int *a,int n){
    if(!a||n<=1) return;
    int minv=a[0],maxv=a[0];
    for(int i=1;i<n;++i){if(a[i]<minv) minv=a[i]; if(a[i]>maxv) maxv=a[i];}
    int range=maxv-minv+1; if(range<=0) return;
    int *cnt=(int*)calloc(range,sizeof(int)); if(!cnt) return;
    for(int i=0;i<n;++i) cnt[a[i]-minv]++;
    for(int i=1;i<range;++i) cnt[i]+=cnt[i-1];
    int *out=(int*)malloc(n*sizeof(int)); if(!out){free(cnt);return;}
    for(int i=n-1;i>=0;--i) out[--cnt[a[i]-minv]]=a[i];
    memcpy(a,out,n*sizeof(int)); free(cnt); free(out);
}

/* ---------- 基数排序 LSD（Radix Sort） ---------- */
/* 稳定，适合非负整数，按十进制位处理 */
void radix_sort(int *a,int n){
    if(!a||n<=1) return;
    int maxv=a[0]; for(int i=1;i<n;++i) if(a[i]>maxv) maxv=a[i];
    int *out=(int*)malloc(n*sizeof(int)); int *cnt=(int*)malloc(10*sizeof(int));
    if(!out||!cnt){free(out);free(cnt);return;}
    for(int exp=1;maxv/exp>0;exp*=10){
        memset(cnt,0,10*sizeof(int));
        for(int i=0;i<n;++i) cnt[(a[i]/exp)%10]++;
        for(int i=1;i<10;++i) cnt[i]+=cnt[i-1];
        for(int i=n-1;i>=0;--i){int d=(a[i]/exp)%10; out[--cnt[d]]=a[i];}
        memcpy(a,out,n*sizeof(int));
    }
    free(out); free(cnt);
}

/* ---------- 桶排序（Bucket Sort） ---------- */
/* 对整数的简单桶实现，桶内用插入排序，适合均匀分布 */
void bucket_sort(int *a,int n){
    if(!a||n<=1) return;
    int minv=a[0],maxv=a[0]; for(int i=1;i<n;++i){if(a[i]<minv) minv=a[i]; if(a[i]>maxv) maxv=a[i];}
    int range=maxv-minv+1; if(range==0) return;
    int bucket_count=n; if(bucket_count<=0) return;
    int *counts=(int*)calloc(bucket_count,sizeof(int)); int **buckets=(int**)malloc(bucket_count*sizeof(int*));
    if(!counts||!buckets){free(counts);free(buckets);return;}
    for(int i=0;i<bucket_count;++i) buckets[i]=NULL;
    for(int i=0;i<n;++i){
        int idx=(int)((long long)(a[i]-minv)*(bucket_count-1)/(range-1));
        counts[idx]++; buckets[idx]=(int*)realloc(buckets[idx],counts[idx]*sizeof(int)); buckets[idx][counts[idx]-1]=a[i];
    }
    int pos=0;
    for(int i=0;i<bucket_count;++i){
        if(counts[i]==0) continue;
        for(int x=1;x<counts[i];++x){int key=buckets[i][x],y=x-1; while(y>=0&&buckets[i][y]>key){buckets[i][y+1]=buckets[i][y];--y;} buckets[i][y+1]=key;}
        for(int j=0;j<counts[i];++j) a[pos++]=buckets[i][j];
        free(buckets[i]);
    }
    free(buckets); free(counts);
}

/* ---------- 辅助：打印数组 ---------- */
void print_array(const char *msg,int *a,int n){ if(msg) printf("%s",msg); for(int i=0;i<n;++i){ if(i) printf(" "); printf("%d",a[i]); } printf("\n"); }

/* ---------- main 测试 ---------- */
int main(void){
    int arr[]={29,10,14,37,14,3,78,45,10,0,-5,100}; int n=sizeof(arr)/sizeof(arr[0]);
    int *b=(int*)malloc(n*sizeof(int)); if(!b) return 1;
    memcpy(b,arr,n*sizeof(int)); bubble_sort(b,n); print_array("bubble: ",b,n);
    memcpy(b,arr,n*sizeof(int)); selection_sort(b,n); print_array("selection: ",b,n);
    memcpy(b,arr,n*sizeof(int)); insertion_sort(b,n); print_array("insertion: ",b,n);
    memcpy(b,arr,n*sizeof(int)); shell_sort(b,n); print_array("shell: ",b,n);
    memcpy(b,arr,n*sizeof(int)); merge_sort(b,n); print_array("merge: ",b,n);
    memcpy(b,arr,n*sizeof(int)); quick_sort(b,n); print_array("quick: ",b,n);
    memcpy(b,arr,n*sizeof(int)); heap_sort(b,n); print_array("heap: ",b,n);
    memcpy(b,arr,n*sizeof(int)); counting_sort(b,n); print_array("counting: ",b,n);
    memcpy(b,arr,n*sizeof(int)); radix_sort(b,n); print_array("radix: ",b,n);
    memcpy(b,arr,n*sizeof(int)); bucket_sort(b,n); print_array("bucket: ",b,n);
    free(b); return 0;
}
