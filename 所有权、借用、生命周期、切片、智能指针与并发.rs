// main.rs
// 完整示例：所有权、借用、生命周期、切片、智能指针与并发。
// 2025-09-22 示例 — 供学习与实践，可直接用 `cargo run` 运行。
// 注：所有会导致编译错误的示例保留为注释并附解释。

use std::rc::Rc;
use std::cell::RefCell;
use std::thread;
use std::sync::Arc;
use std::sync::Mutex;

// 辅助函数：分割线打印（仅用于输出清晰）
fn sep(title: &str) {
    println!("\n--- {} ---", title);
}

fn main() {
    sep("Ownership: move vs clone vs copy");
    // String 不实现 Copy，因此赋值是 move（转移所有权）
    let s1 = String::from("hello");
    let s2 = s1; // s1 的所有权被移动到 s2
    // println!("{}", s1); // 编译错误 E0382: borrow of moved value
    println!("s2: {}", s2);

    // 若需要两个变量各自拥有独立数据，使用 clone()
    let s3 = s2.clone();
    println!("s2 (still valid): {}, s3 (clone): {}", s2, s3);

    // 基本标量类型（例如 i32）实现 Copy，所以赋值执行按位复制，源仍有效
    let x: i32 = 100;
    let y = x; // copy
    println!("x: {}, y: {}", x, y);

    sep("Passing ownership to functions");
    let s4 = String::from("owned by caller");
    takes_ownership(s4);
    // s4 已被移动到 takes_ownership 中，不能再使用
    // println!("{}", s4); // E0382

    let z = 42;
    makes_copy(z); // i32 被复制，z 仍然可用
    println!("z still accessible: {}", z);

    sep("Returning ownership from functions");
    let s5 = gives_ownership();
    println!("s5 from gives_ownership: {}", s5);

    let s6 = String::from("take and give back");
    let s6 = takes_and_gives_back(s6); // 所有权被传入并返回
    println!("s6: {}", s6);

    sep("Borrowing: immutable references (&T)");
    let s7 = String::from("borrow immutably");
    let len = calculate_length(&s7); // 不转移所有权，传入不可变引用
    println!("'{}' length: {}", s7, len); // s7 仍可用

    sep("Borrowing: mutable references (&mut T)");
    let mut s8 = String::from("hello");
    change(&mut s8);
    println!("s8 after change: {}", s8);

    sep("Borrow rules: multiple & vs single &mut");
    let mut s9 = String::from("abc");
    {
        let r1 = &s9;
        let r2 = &s9;
        println!("r1: {}, r2: {}", r1, r2);
        // r1 和 r2 在此内部作用域结束后失效
    }
    // 现在可以创建可变引用
    {
        let r3 = &mut s9;
        r3.push_str("def");
        println!("r3: {}", r3);
    }

    // 如果尝试同时存在不可变引用与可变引用会导致借用冲突（编译错误）
    /*
    let mut s10 = String::from("x");
    let r1 = &s10;
    let r2 = &mut s10; // error: cannot borrow `s10` as mutable because it is also borrowed as immutable
    println!("{}, {}", r1, r2);
    */

    sep("Dangling references: impossible in safe Rust");
    // 以下函数被注释，因为会导致悬挂引用（返回指向局部变量的引用）
    /*
    fn dangle() -> &String {
        let s = String::from("hello");
        &s // 错误：s 在函数结束时被 drop，不能返回引用
    }
    */

    sep("Slices: &str and array slices");
    let s11 = String::from("hello world");
    let first_word_idx = first_word(&s11);
    println!("first_word index: {}", first_word_idx);
    let first_word_slice = first_word_slice(&s11);
    println!("first word slice: {}", first_word_slice);

    let arr = [10, 20, 30, 40, 50];
    let arr_slice = &arr[1..4]; // &[20,30,40]
    println!("array slice: {:?}", arr_slice);

    sep("Lifetimes: simple explicit lifetime example");
    // 当返回一个引用时，函数签名通常需要显式生命周期参数。
    // 下面是一个示例函数调用与定义在文件底部（longest）。
    let s12 = String::from("abcd");
    let s13 = String::from("xyz");
    let result = longest(&s12, &s13);
    println!("longest of '{}' and '{}' is '{}'", s12, s13, result);

    sep("Smart pointers: Box<T>, Rc<T>, RefCell<T>");
    // Box<T>：用于在堆上分配并拥有数据（单一所有者）
    let b = Box::new(5);
    println!("boxed: {}", b);

    // Rc<T>：引用计数，允许多所有者（单线程）
    let rc1 = Rc::new(String::from("rc string"));
    let rc2 = Rc::clone(&rc1); // 增加引用计数
    println!("rc1: {}, rc2: {}", rc1, rc2);
    println!("Rc strong_count: {}", Rc::strong_count(&rc1));

    // RefCell<T>：提供运行时可变借用检查（interior mutability）
    let rc_ref = Rc::new(RefCell::new(vec![1, 2, 3]));
    {
        let mut_borrow = rc_ref.borrow_mut(); // 运行时检查可变借用是否安全
        // mut_borrow.push(4); // 编译允许，在运行时保证安全
        drop(mut_borrow); // 释放可变借用
    }
    {
        let borrow1 = rc_ref.borrow();
        let borrow2 = rc_ref.borrow();
        println!("RefCell borrows (read): {:?}, {:?}", borrow1, borrow2);
    }

    sep("Shared ownership across threads: Arc + Mutex");
    // Rc 不能跨线程，但 Arc 可以。Mutex 提供线程内可变性保护。
    let counter = Arc::new(Mutex::new(0));
    let mut handles = vec![];
    for _ in 0..4 {
        let counter_clone = Arc::clone(&counter);
        let handle = thread::spawn(move || {
            let mut num = counter_clone.lock().unwrap();
            *num += 1;
            // MutexGuard 在离开作用域时自动解锁
        });
        handles.push(handle);
    }
    for h in handles {
        h.join().unwrap();
    }
    println!("counter after threads: {}", *counter.lock().unwrap());

    sep("Send/Sync brief demonstration (ownership to thread)");
    // 将拥有的值移动到线程中（所有权转移），父线程不再可访问
    let s_thread = String::from("moved to thread");
    let handle = thread::spawn(move || {
        println!("in thread: {}", s_thread);
    });
    handle.join().unwrap();

    sep("Common compiler errors (examples & fixes)");
    // E0382: borrow of moved value — 见上面 s1->s2
    // Borrow conflict: simultaneous & and &mut — 见注释示例
    // Lifetime mismatch: 如果返回引用，确保引用的生命周期长于函数调用者
    println!("See commented examples in code for error cases and fixes.");
}

// ---------- 所有权相关函数 ----------
fn takes_ownership(s: String) {
    println!("takes_ownership got: {}", s);
} // s 离开作用域并被 drop

fn makes_copy(x: i32) {
    println!("makes_copy got: {}", x);
} // x 是 Copy

fn gives_ownership() -> String {
    let s = String::from("given ownership");
    s // 返回并转移所有权
}

fn takes_and_gives_back(s: String) -> String {
    s // 接收并返回所有权
}

// ---------- 借用相关函数 ----------
fn calculate_length(s: &String) -> usize {
    // 不可变借用：只能读不能改
    s.len()
}

fn change(s: &mut String) {
    // 可变借用：可以修改数据
    s.push_str(", world");
}

// ---------- 切片相关 ----------
fn first_word(s: &String) -> usize {
    // 返回第一个空格的位置（索引）
    let bytes = s.as_bytes();
    for (i, &b) in bytes.iter().enumerate() {
        if b == b' ' {
            return i;
        }
    }
    s.len()
}

fn first_word_slice(s: &String) -> &str {
    // 返回字符串切片（借用数据的一部分）
    let bytes = s.as_bytes();
    for (i, &b) in bytes.iter().enumerate() {
        if b == b' ' {
            return &s[..i];
        }
    }
    &s[..]
}

// ---------- 生命周期示例 ----------
// 当函数参数包含引用且函数返回引用时，通常需要生命周期参数
// 下面 longest 函数返回两个引用中较长的那个。借用者的生命周期必须至少覆盖返回值的使用。
fn longest<'a>(x: &'a str, y: &'a str) -> &'a str {
    // 注：'a 表示一个通用的生命周期，确保返回引用与其中某个参数的生命周期一致
    if x.len() >= y.len() { x } else { y }
}
