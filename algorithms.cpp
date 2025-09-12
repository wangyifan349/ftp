#include <bits/stdc++.h>
using namespace std;

// 1) 斐波那契 — 递归
long long fib_recursive(int n) {
    if (n <= 1) return n;
    return fib_recursive(n-1) + fib_recursive(n-2);
}

// 2) 斐波那契 — 迭代
long long fib_iterative(int n) {
    if (n <= 1) return n;
    long long a = 0, b = 1;
    for (int i = 2; i <= n; ++i) {
        long long c = a + b;
        a = b;
        b = c;
    }
    return b;
}

// 3) 斐波那契 — 带记忆（DP）
long long fib_dp(int n) {
    if (n <= 1) return n;
    vector<long long> dp(n+1);
    dp[0]=0; dp[1]=1;
    for (int i=2;i<=n;++i) dp[i]=dp[i-1]+dp[i-2];
    return dp[n];
}

// 4) 阶乘（递归）
long long fact_recursive(int n) {
    if (n <= 1) return 1;
    return n * fact_recursive(n-1);
}

// 5) 阶乘（迭代）
long long fact_iterative(int n) {
    long long res = 1;
    for (int i=2;i<=n;++i) res *= i;
    return res;
}

// 6) 最大公约数（GCD）
long long gcd_ll(long long a, long long b) {
    while (b) {
        long long t = a % b;
        a = b;
        b = t;
    }
    return a;
}

// 7) 快速幂（支持模运算）
long long mod_pow(long long a, long long e, long long mod) {
    long long res = 1;
    a %= mod;
    while (e > 0) {
        if (e & 1) res = (__int128)res * a % mod;
        a = (__int128)a * a % mod;
        e >>= 1;
    }
    return res;
}

// 8) 二分查找（有序数组）
int binary_search_vec(const vector<int>& a, int target) {
    int l = 0, r = (int)a.size() - 1;
    while (l <= r) {
        int m = l + (r - l) / 2;
        if (a[m] == target) return m;
        if (a[m] < target) l = m + 1;
        else r = m - 1;
    }
    return -1; // not found
}

// 9) 判断素数（简单方法）
bool is_prime_ll(long long n) {
    if (n <= 1) return false;
    if (n <= 3) return true;
    if (n % 2 == 0) return false;
    for (long long i = 3; i * i <= n; i += 2)
        if (n % i == 0) return false;
    return true;
}

// 10) 素数筛（埃拉托斯特尼筛）
vector<int> sieve(int n) {
    if (n < 2) return {};
    vector<char> is_prime(n+1, true);
    is_prime[0]=is_prime[1]=false;
    for (int i=2;i*(long long)i<=n;++i) {
        if (is_prime[i]) {
            for (int j=i*i;j<=n;j+=i) is_prime[j]=false;
        }
    }
    vector<int> res;
    for (int i=2;i<=n;++i) if (is_prime[i]) res.push_back(i);
    return res;
}

// 11) 组合数 nCr（模质数下，预处理阶乘与逆元）
struct Comb {
    int n;
    long long mod;
    vector<long long> fact, ifact;
    Comb(int n_ = 0, long long mod_ = 1000000007): n(n_), mod(mod_), fact(), ifact() {
        if (n > 0) init(n, mod);
    }
    void init(int n_, long long mod_) {
        n = n_;
        mod = mod_;
        fact.assign(n+1, 1);
        ifact.assign(n+1, 1);
        for (int i=1;i<=n;i++) fact[i]=fact[i-1]*i%mod;
        ifact[n]=mod_pow(fact[n], mod-2, mod);
        for (int i=n;i>0;i--) ifact[i-1]=ifact[i]*i%mod;
    }
    long long C(int N,int K) const {
        if (K<0||K> N) return 0;
        return fact[N]*ifact[K]%mod*ifact[N-K]%mod;
    }
};

// Helper: print vector<int>
void print_vec(const vector<int>& v) {
    for (size_t i=0;i<v.size();++i) {
        if (i) cout << ' ';
        cout << v[i];
    }
    cout << '\n';
}

// Print menu
void print_menu() {
    cout << "\n===== 演示菜单 =====\n";
    cout << "0 退出\n";
    cout << "1 斐波那契（递归）\n";
    cout << "2 斐波那契（迭代）\n";
    cout << "3 斐波那契（DP）\n";
    cout << "4 阶乘（递归）\n";
    cout << "5 阶乘（迭代）\n";
    cout << "6 最大公约数（GCD）\n";
    cout << "7 快速幂（模）\n";
    cout << "8 二分查找（有序数组）\n";
    cout << "9 判断素数\n";
    cout << "10 素数筛（埃拉托斯特尼）\n";
    cout << "11 组合数 nCr（模质数，预处理）\n";
    cout << "a 显示菜单\n";
    cout << "====================\n";
}

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    print_menu();
    Comb comb; // can init later when needed

    while (true) {
        cout << "\n选择项 (输入 a 显示菜单): ";
        string cmd;
        if (!(cin >> cmd)) break;
        if (cmd == "0") break;
        if (cmd == "a" || cmd == "A") { print_menu(); continue; }

        if (cmd == "1") {
            int n; cout << "n: "; cin >> n;
            cout << fib_recursive(n) << '\n';
        } else if (cmd == "2") {
            int n; cout << "n: "; cin >> n;
            cout << fib_iterative(n) << '\n';
        } else if (cmd == "3") {
            int n; cout << "n: "; cin >> n;
            cout << fib_dp(n) << '\n';
        } else if (cmd == "4") {
            int n; cout << "n: "; cin >> n;
            cout << fact_recursive(n) << '\n';
        } else if (cmd == "5") {
            int n; cout << "n: "; cin >> n;
            cout << fact_iterative(n) << '\n';
        } else if (cmd == "6") {
            long long a,b; cout << "a b: "; cin >> a >> b;
            cout << gcd_ll(a,b) << '\n';
        } else if (cmd == "7") {
            long long a,e,mod; cout << "a e mod: "; cin >> a >> e >> mod;
            cout << mod_pow(a,e,mod) << '\n';
        } else if (cmd == "8") {
            int n; cout << "数组长度 n: "; cin >> n;
            vector<int> a(n);
            cout << "输入 " << n << " 个已排序整数: ";
            for (int i=0;i<n;i++) cin >> a[i];
            int t; cout << "target: "; cin >> t;
            cout << binary_search_vec(a,t) << '\n';
        } else if (cmd == "9") {
            long long x; cout << "x: "; cin >> x;
            cout << (is_prime_ll(x) ? "1\n" : "0\n");
        } else if (cmd == "10") {
            int n; cout << "n: "; cin >> n;
            auto p = sieve(n);
            print_vec(p);
        } else if (cmd == "11") {
            int maxn; long long mod;
            cout << "输入预处理上限 maxn 和 mod（质数）: "; cin >> maxn >> mod;
            comb.init(maxn, mod);
            int N,K; cout << "查询 N K: "; cin >> N >> K;
            cout << comb.C(N,K) << '\n';
        } else {
            cout << "未知命令，输入 a 显示菜单\n";
        }
    }

    cout << "退出。\n";
    return 0;
}
