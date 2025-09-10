// classic_puzzles.rs
// 更完整的经典“鸡兔同笼”等代数题实现（Rust）
// - 支持命令行交互
// - solve_chicken_rabbit(): 专用解法（整数量/验证）
// - solve_linear_2(): 克莱姆法则整数检查
// - solve_linear_enum_n(): 对 n 个未知数的简单有界枚举（用于小规模问题）
// - 单元测试覆盖若干情形

use std::io::{self, Write};
use std::num::ParseIntError;

/// 专用鸡兔同笼求解（鸡 2 条腿，兔 4 条腿）
/// heads >= 0, legs >= 0
/// 返回 Some((chickens, rabbits)) 或 None（无非负整数解）
fn solve_chicken_rabbit(heads: i32, legs: i32) -> Option<(i32, i32)> {
    if heads < 0 || legs < 0 {
        return None;
    }
    // 设鸡 x，兔 y：
    // x + y = heads
    // 2x + 4y = legs
    // 解：y = (legs - 2*heads)/2
    let diff = legs - 2 * heads;
    if diff < 0 || diff % 2 != 0 {
        return None;
    }
    let rabbits = diff / 2;
    let chickens = heads - rabbits;
    if chickens < 0 {
        return None;
    }
    Some((chickens, rabbits))
}

/// 用克莱姆法则求解 2x2 整数线性方程组：
/// a1*x + b1*y = c1
/// a2*x + b2*y = c2
/// 仅在存在唯一整数解时返回 Some((x,y))
fn solve_linear_2(
    a1: i64,
    b1: i64,
    c1: i64,
    a2: i64,
    b2: i64,
    c2: i64,
) -> Option<(i64, i64)> {
    let det = a1 * b2 - a2 * b1;
    if det == 0 {
        return None;
    }
    let det_x = c1 * b2 - c2 * b1;
    let det_y = a1 * c2 - a2 * c1;
    if det_x % det != 0 || det_y % det != 0 {
        return None;
    }
    Some((det_x / det, det_y / det))
}

/// 对 n 个未知数构造的简单有界枚举求解器（适用于小规模、可界定的整数问题）
/// - coeffs: m x n 矩阵（m 方程，n 未知数），按行扁平化: coeffs.len() == m * n
/// - consts: 右侧常数向量，长度 m
/// - bounds: 每个未知数的上界（包含 0 到 bounds[i] 的整数枚举）
/// 返回符合所有方程的整数解向量（第一个找到的），或 None
fn solve_linear_enum_n(
    coeffs: &[i64],
    consts: &[i64],
    m: usize,
    n: usize,
    bounds: &[i64],
) -> Option<Vec<i64>> {
    if coeffs.len() != m * n || consts.len() != m || bounds.len() != n {
        return None;
    }
    // 递归枚举
    let mut current = vec![0i64; n];
    fn check_partial(
        coeffs: &[i64],
        consts: &[i64],
        m: usize,
        n: usize,
        current: &Vec<i64>,
    ) -> bool {
        // 检查所有方程在当前赋值下是否已经被违反（只在所有变量赋完值时完全检查）
        for i in 0..m {
            let mut sum = 0i128;
            for j in 0..n {
                let a = coeffs[i * n + j] as i128;
                let x = current[j] as i128;
                sum += a * x;
            }
            if sum as i64 != consts[i] {
                return false;
            }
        }
        true
    }
    fn dfs(
        idx: usize,
        coeffs: &[i64],
        consts: &[i64],
        m: usize,
        n: usize,
        bounds: &[i64],
        current: &mut Vec<i64>,
    ) -> Option<Vec<i64>> {
        if idx == n {
            // 全部变量赋值，检查是否满足所有方程
            if check_partial(coeffs, consts, m, n, current) {
                return Some(current.clone());
            } else {
                return None;
            }
        }
        for v in 0..=bounds[idx] {
            current[idx] = v;
            // 对于效率可加入部分约束提前剪枝，但为保持通用性这里不做复杂剪枝
            if let Some(sol) = dfs(idx + 1, coeffs, consts, m, n, bounds, current) {
                return Some(sol);
            }
        }
        current[idx] = 0;
        None
    }
    dfs(0, coeffs, consts, m, n, bounds, &mut current)
}

/// 读取一行并解析为 i64
fn read_i64(prompt: &str) -> Result<i64, ParseIntError> {
    print!("{}", prompt);
    let _ = io::stdout().flush();
    let mut input = String::new();
    io::stdin().read_line(&mut input).ok();
    input.trim().parse::<i64>()
}

fn main() {
    println!("经典问题求解器：");
    println!("1) 鸡兔同笼（鸡2条腿，兔4条腿）");
    println!("2) 通用 2x2 整数线性方程组");
    println!("3) 有界枚举求解 n 未知数线性方程（适合小规模）");
    print!("请选择 (1/2/3)：");
    let _ = io::stdout().flush();

    let mut choice = String::new();
    io::stdin().read_line(&mut choice).ok();
    match choice.trim() {
        "1" => {
            let heads = loop {
                match read_i64("请输入头数 heads (非负整数): ") {
                    Ok(v) if v >= 0 => break v as i32,
                    _ => println!("请输入非负整数。"),
                }
            };
            let legs = loop {
                match read_i64("请输入腿数 legs (非负整数): ") {
                    Ok(v) if v >= 0 => break v as i32,
                    _ => println!("请输入非负整数。"),
                }
            };
            match solve_chicken_rabbit(heads, legs) {
                Some((c, r)) => println!("解：鸡 = {}, 兔 = {}", c, r),
                None => println!("无非负整数解。"),
            }
        }
        "2" => {
            println!("求解 a1*x + b1*y = c1; a2*x + b2*y = c2");
            let a1 = read_i64("a1 = ").unwrap_or(0);
            let b1 = read_i64("b1 = ").unwrap_or(0);
            let c1 = read_i64("c1 = ").unwrap_or(0);
            let a2 = read_i64("a2 = ").unwrap_or(0);
            let b2 = read_i64("b2 = ").unwrap_or(0);
            let c2 = read_i64("c2 = ").unwrap_or(0);
            match solve_linear_2(a1, b1, c1, a2, b2, c2) {
                Some((x, y)) => println!("整数解：x = {}, y = {}", x, y),
                None => println!("无唯一整数解（可能无解、无限解或非整数解）。"),
            }
        }
        "3" => {
            println!("输入 m 个方程、n 个未知数 (m 行，n 列系数)");
            let n = loop {
                match read_i64("未知数个数 n (1..6 建议) = ") {
                    Ok(v) if v >= 1 && v <= 10 => break v as usize,
                    _ => println!("请输入 1 到 10 之间的整数（建议不超过 6）。"),
                }
            };
            let m = loop {
                match read_i64("方程个数 m = ") {
                    Ok(v) if v >= 1 && v <= 10 => break v as usize,
                    _ => println!("请输入 1 到 10 之间的整数。"),
                }
            };
            println!("依次输入每个方程的系数（按行），共 {} 行，每行 {} 个整数，用回车分隔。", m, n);
            let mut coeffs = Vec::with_capacity(m * n);
            for i in 0..m {
                for j in 0..n {
                    let prompt = format!("a[{}][{}] = ", i + 1, j + 1);
                    let a = loop {
                        match read_i64(&prompt) {
                            Ok(v) => break v,
                            Err(_) => println!("请输入整数。"),
                        }
                    };
                    coeffs.push(a);
                }
            }
            println!("输入每个方程的常数项 c_i：");
            let mut consts = Vec::with_capacity(m);
            for i in 0..m {
                let prompt = format!("c[{}] = ", i + 1);
                let c = loop {
                    match read_i64(&prompt) {
                        Ok(v) => break v,
                        Err(_) => println!("请输入整数。"),
                    }
                };
                consts.push(c);
            }
            println!("为每个未知数设置枚举上界（从 0 到 bound）：");
            let mut bounds = Vec::with_capacity(n);
            for j in 0..n {
                let prompt = format!("bound[{}] = ", j + 1);
                let b = loop {
                    match read_i64(&prompt) {
                        Ok(v) if v >= 0 => break v,
                        _ => println!("请输入非负整数。"),
                    }
                };
                bounds.push(b);
            }
            match solve_linear_enum_n(&coeffs, &consts, m, n, &bounds) {
                Some(sol) => {
                    println!("找到解向量：");
                    for (i, v) in sol.iter().enumerate() {
                        println!("x[{}] = {}", i + 1, v);
                    }
                }
                None => println!("在给定 bounds 下未找到整数解。"),
            }
        }
        _ => println!("无效选择。"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_chicken_rabbit_basic() {
        assert_eq!(solve_chicken_rabbit(35, 94), Some((12, 23)));
        assert_eq!(solve_chicken_rabbit(10, 28), Some((6, 4)));
        assert_eq!(solve_chicken_rabbit(10, 27), None); // 腿数奇数，不可能
        assert_eq!(solve_chicken_rabbit(-1, 10), None);
    }

    #[test]
    fn test_solve_linear_2() {
        // x + y = 3; 2x + 4y = 8 -> 解 x=2, y=1
        assert_eq!(solve_linear_2(1, 1, 3, 2, 4, 8), Some((2, 1)));
        // 无唯一解示例：
        assert_eq!(solve_linear_2(1, 1, 2, 2, 2, 4), None); // det = 0 (无穷多或无解)
        // 非整数解：
        assert_eq!(solve_linear_2(1, 1, 1, 1, -1, 0), None); // 解 x=0.5,y=0.5
    }

    #[test]
    fn test_solve_enum_n() {
        // 简单：x + y = 3; 2x + 4y = 8 -> 解 x=2,y=1
        let coeffs = vec![1, 1, 2, 4]; // 2x2 行主序
        let consts = vec![3, 8];
        let sol = solve_linear_enum_n(&coeffs, &consts, 2, 2, &[5, 5]).unwrap();
        assert_eq!(sol, vec![2, 1]);

        // 无解示例（在小 bounds 内）
        let coeffs = vec![1, 1];
        let consts = vec![10];
        assert!(solve_linear_enum_n(&coeffs, &consts, 1, 2, &[3, 3]).is_none());
    }
}
