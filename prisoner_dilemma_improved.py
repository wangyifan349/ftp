# prisoner_dilemma_improved.py
# 功能：
# - 配置支付参数 T,R,P,S 和模拟参数（rounds,trials,noise,seed）
# - 判定纯策略占优（严格/弱）并列出纯策略纳什均衡
# - 模拟重复博弈并比较策略平均每轮得分
# 运行： python3 prisoner_dilemma_improved.py

import numpy as np
import random

# ====================================================
# 用户可修改的参数（集中于此处）
# ====================================================
# 支付参数（数值越大越好，满足经典囚徒困境应为 T > R > P > S）
T = 5  # 诱惑：单方面背叛且对方合作时获得
R = 3  # 奖励：双方都合作时获得
P = 1  # 惩罚：双方都背叛时获得
S = 0  # 受害者：单方面被背叛时获得

# 模拟参数
ROUNDS = 200        # 每次重复博弈的轮数
TRIALS = 40         # 每对策略重复的独立试验次数（用于平均）
NOISE = 0.02        # 执行动作翻转概率（误操作/噪声），范围 [0,1]
SEED = 12345        # 随机种子（设为 None 则不固定）

# 策略集合（将在下方注册具体策略函数）
STRATEGY_NAMES = ["AllC", "AllD", "TFT", "Grim", "Rand50"]

# ====================================================
# 内部常量（通常无需修改）
# ====================================================
# 动作编码：0 = C (合作), 1 = D (背叛)
ACTIONS = {0: "C", 1: "D"}

# 支付矩阵（行：A 的动作，列：B 的动作）
# payoff_matrix[a_action, b_action] = (payoff_A, payoff_B)
payoff_matrix = np.array([
    [(R, R), (S, T)],  # A plays C
    [(T, S), (P, P)]   # A plays D
], dtype=object)

# ====================================================
# 占优策略与纳什均衡判定函数（无类）
# ====================================================
def is_dominant_action(player, action):
    """
    判断 player (0=A,1=B) 的 action (0=C,1=D) 是否为占优（至少不逊于替代动作）
    返回 (is_dominant_bool, is_strict_bool)
    is_dominant_bool: 对对手所有动作都至少不逊色
    is_strict_bool: 且在至少一个对手动作上严格优于替代动作
    """
    other_actions = [0, 1]
    at_least_equal = True
    strictly_better = False
    for oa in other_actions:
        if player == 0:
            me = payoff_matrix[action, oa][0]
            alt = payoff_matrix[1-action, oa][0]
        else:
            me = payoff_matrix[oa, action][1]
            alt = payoff_matrix[oa, 1-action][1]
        if me < alt:
            at_least_equal = False
            break
        if me > alt:
            strictly_better = True
    return at_least_equal, strictly_better

def list_pure_nash():
    """
    列出所有纯策略纳什均衡（返回动作对列表 [(a,b), ...]）
    """
    equilibria = []
    for a in [0,1]:
        for b in [0,1]:
            a_pay = payoff_matrix[a,b][0]
            b_pay = payoff_matrix[a,b][1]
            a_best = all(payoff_matrix[a_alt,b][0] <= a_pay for a_alt in [0,1])
            b_best = all(payoff_matrix[a,b_alt][1] <= b_pay for b_alt in [0,1])
            if a_best and b_best:
                equilibria.append((a,b))
    return equilibria

# ====================================================
# 单次博弈分析展示
# ====================================================
def single_game_analysis():
    print("=== 单次博弈：支付矩阵（格式： (payoff_A, payoff_B)） ===")
    for a in [0,1]:
        row = []
        for b in [0,1]:
            row.append(str(payoff_matrix[a,b]))
        print(f"A={ACTIONS[a]}: {row}")
    print()
    print("=== 占优策略检测 ===")
    for player in [0,1]:
        who = "A" if player==0 else "B"
        for action in [0,1]:
            is_dom, is_strict = is_dominant_action(player, action)
            kind = "不是占优"
            if is_dom:
                kind = "严格占优" if is_strict else "弱占优"
            print(f"玩家{who} 选择 {ACTIONS[action]}: {kind}")
    print()
    nash = list_pure_nash()
    if nash:
        print("纯策略纳什均衡：", [(ACTIONS[a], ACTIONS[b]) for a,b in nash])
    else:
        print("无纯策略纳什均衡。")
    print()

# ====================================================
# 策略实现（函数式，签名： strategy(history_self, history_opponent) -> action ）
# history 为 list[int]，元素为 0 或 1
# ====================================================
def strat_allc(history_self, history_opp):
    return 0

def strat_alld(history_self, history_opp):
    return 1

def strat_tft(history_self, history_opp):
    # Tit-for-Tat：首轮合作，之后复制对手上一轮动作
    return 0 if len(history_opp)==0 else history_opp[-1]

def strat_grim(history_self, history_opp):
    # Grim trigger：先合作，若对方曾背叛过一次则永远背叛
    return 0 if (len(history_opp)==0 or 1 not in history_opp) else 1

def strat_rand50(history_self, history_opp):
    return 1 if random.random() < 0.5 else 0

# 策略注册（名字到函数）
STRATEGIES = {
    "AllC": strat_allc,
    "AllD": strat_alld,
    "TFT": strat_tft,
    "Grim": strat_grim,
    "Rand50": strat_rand50
}

# ====================================================
# 重复博弈模拟函数（无类）
# ====================================================
def apply_noise(action, noise):
    """以概率 noise 翻转 action（0<->1）"""
    if noise <= 0:
        return action
    return 1-action if random.random() < noise else action

def play_once(action_a, action_b):
    """返回该轮的 (payoff_A, payoff_B)"""
    return payoff_matrix[action_a, action_b]

def simulate_pair(stratA, stratB, rounds=ROUNDS, noise=NOISE, seed=None):
    """
    模拟 stratA vs stratB 的重复博弈
    stratX: 函数 (history_self, history_opponent) -> action (0/1)
    返回： (total_A, total_B, history_A, history_B, per_round_A, per_round_B)
    """
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)
    history_a, history_b = [], []
    per_a, per_b = [], []
    for t in range(rounds):
        a = stratA(history_a, history_b)
        b = stratB(history_b, history_a)  # 注意参数次序：对方历史传入第二个参数
        a = apply_noise(a, noise)
        b = apply_noise(b, noise)
        pa, pb = play_once(a, b)
        history_a.append(a)
        history_b.append(b)
        per_a.append(pa)
        per_b.append(pb)
    return sum(per_a), sum(per_b), history_a, history_b, per_a, per_b

# ====================================================
# 策略间全面比较（多试验平均）
# ====================================================
def compare_all(rounds=ROUNDS, trials=TRIALS, noise=NOISE, seed=SEED):
    names = STRATEGY_NAMES
    results = {}
    for nameA in names:
        for nameB in names:
            total_a = 0.0
            total_b = 0.0
            for t in range(trials):
                sA = STRATEGIES[nameA]
                sB = STRATEGIES[nameB]
                # 使用不同 seed 保证试验间随机性可复现（若 seed 为 None 则随机）
                trial_seed = None if seed is None else seed + t
                suma, sumb, _, _, _, _ = simulate_pair(sA, sB, rounds=rounds, noise=noise, seed=trial_seed)
                total_a += suma
                total_b += sumb
            avg_per_round_a = total_a / (trials * rounds)
            avg_per_round_b = total_b / (trials * rounds)
            results[(nameA, nameB)] = (avg_per_round_a, avg_per_round_b)
    return results

# ====================================================
# 主程序
# ====================================================
def main():
    # 打印当前参数
    print("=== 参数设置 ===")
    print(f"T={T}, R={R}, P={P}, S={S}   (应满足 T>R>P>S 才为典型囚徒困境)")
    print(f"ROUNDS={ROUNDS}, TRIALS={TRIALS}, NOISE={NOISE}, SEED={SEED}")
    print(f"策略集合: {STRATEGY_NAMES}")
    print()

    single_game_analysis()

    print("=== 重复博弈：策略平均每轮得分比较（无噪声） ===")
    res_no_noise = compare_all(rounds=ROUNDS, trials=TRIALS, noise=0.0, seed=SEED)
    # 打印表头
    header = " " * 8 + "".join([f"{n:12s}" for n in STRATEGY_NAMES])
    print(header)
    for na in STRATEGY_NAMES:
        row = f"{na:8s}"
        for nb in STRATEGY_NAMES:
            aavg, bavg = res_no_noise[(na, nb)]
            row += f"{aavg:6.3f}/{bavg:6.3f}    "
        print(row)
    print()

    print("=== 重复博弈：策略比较（带噪声 NOISE） ===")
    res_noise = compare_all(rounds=ROUNDS, trials=TRIALS, noise=NOISE, seed=SEED)
    print(header)
    for na in STRATEGY_NAMES:
        row = f"{na:8s}"
        for nb in STRATEGY_NAMES:
            aavg, bavg = res_noise[(na, nb)]
            row += f"{aavg:6.3f}/{bavg:6.3f}    "
        print(row)
    print()

    print("说明：每项为 A_avg_per_round / B_avg_per_round（平均每轮得分），数值越大越好。")

if __name__ == "__main__":
    main()
