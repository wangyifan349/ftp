import random

# 产生公平的 0/1（0 → 左，1 → 右）
def fair_coin():
    return random.getrandbits(1)

print("=== 一维公平随机游走 ===")
position = 0          # 当前位移
step = 0              # 已进行的步数

while True:
    step += 1
    print(f"\n第 {step} 步，当前位移 = {position}")

    # 读取玩家操作
    act = input("操作 (c=继续, s=停止, l=加杠杆): ").strip().lower()
    while act not in ("c", "s", "l"):
        act = input("无效，请输入 c、s 或 l: ").strip().lower()

    if act == "s":
        print(f"\n游戏结束，最终位移 = {position}")
        break

    # 决定本轮方向
    direction = fair_coin()          # 0 或 1
    move = 1 if direction == 1 else -1

    # 如需杠杆，读取倍率并放大本轮移动
    if act == "l":
        lev = input("输入杠杆倍率 (>=2): ").strip()
        while not lev.isdigit() or int(lev) < 2:
            lev = input("请输⼊大于等于 2 的整数: ").strip()
        move *= int(lev)
        print(f"使用杠杆 ×{lev}，本轮移动 {move}")
    else:
        print(f"本轮移动 {move}")

    position += move
