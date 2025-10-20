#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
绘制并保存七种“爱情/心形”相关曲线的高清图像（PNG）。
输出文件（300 DPI）:
- heart_cardioid.png
- butterfly.png
- rose.png
- ellipse.png
- heart_algebraic.png
- inverse_heart.png
- cartesian_heart.png
- all_together.png
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib import rcParams

# 全局绘图参数（高清、无锯齿）
rcParams['figure.dpi'] = 300  # 设置图像分辨率为300DPI
rcParams['savefig.dpi'] = 300  # 设置保存图像的DPI
rcParams['font.size'] = 10  # 设置字体大小

# 通用绘图保存函数
def save_plot(fig, filename, bbox_inches='tight', transparent=False):
    """保存图像到文件，并关闭图形"""
    try:
        fig.savefig(filename, bbox_inches=bbox_inches, transparent=transparent)
        plt.close(fig)
        print(f"成功保存图像: {filename}")
    except Exception as e:
        print(f"保存图像 {filename} 时出错: {e}")

# 1. 心形曲线（Cardioid） r(θ) = 1 - sin(θ)
def plot_cardioid(filename='heart_cardioid.png'):
    """绘制心形曲线并保存"""
    try:
        theta = np.linspace(0, 2*np.pi, 2000)
        r = 1 - np.sin(theta)
        x = r * np.cos(theta)
        y = r * np.sin(theta)
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.plot(x, y, color='crimson', linewidth=2)
        ax.set_aspect('equal', 'box')
        ax.axis('off')
        save_plot(fig, filename)
    except Exception as e:
        print(f"绘制心形曲线时出错: {e}")

# 2. 蝴蝶曲线（Butterfly Curve）
def plot_butterfly(filename='butterfly.png'):
    """绘制蝴蝶曲线并保存"""
    try:
        theta = np.linspace(0, 24*np.pi, 20000)  # 扩展区间增加细节
        term = np.exp(np.cos(theta)) - 2*np.cos(4*theta) - np.sin(theta/12.0)**5
        x = np.sin(theta) * term
        y = np.cos(theta) * term
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.plot(x, y, color='darkmagenta', linewidth=0.6)
        ax.set_aspect('equal', 'box')
        ax.axis('off')
        save_plot(fig, filename)
    except Exception as e:
        print(f"绘制蝴蝶曲线时出错: {e}")

# 3. 玫瑰曲线（Rose Curve） r(θ) = a * cos(kθ)
def plot_rose(filename='rose.png', a=1.0, k=5):
    """绘制玫瑰曲线并保存"""
    try:
        theta = np.linspace(0, 2*np.pi, 4000)
        r = a * np.cos(k * theta)
        x = r * np.cos(theta)
        y = r * np.sin(theta)
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.plot(x, y, color='darkred', linewidth=2)
        ax.set_aspect('equal', 'box')
        ax.axis('off')
        save_plot(fig, filename)
    except Exception as e:
        print(f"绘制玫瑰曲线时出错: {e}")

# 4. 椭圆（Ellipse） (x^2 / a^2) + (y^2 / b^2) = 1
def plot_ellipse(filename='ellipse.png', a=2.0, b=1.0):
    """绘制椭圆曲线并保存"""
    try:
        t = np.linspace(0, 2*np.pi, 2000)
        x = a * np.cos(t)
        y = b * np.sin(t)
        fig, ax = plt.subplots(figsize=(6, 4.5))
        ax.plot(x, y, color='teal', linewidth=2)
        ax.set_aspect('equal', 'box')
        ax.axis('off')
        save_plot(fig, filename)
    except Exception as e:
        print(f"绘制椭圆曲线时出错: {e}")

# 5. 心形参数曲线（Heart Curve - algebraic）
def plot_algebraic_heart(filename='heart_algebraic.png'):
    """绘制代数心形曲线并保存"""
    try:
        res = 1200  # 更高分辨率提高精度
        rng = 1.5
        x = np.linspace(-rng, rng, res)
        y = np.linspace(-rng, rng, res)
        X, Y = np.meshgrid(x, y)
        F = (X**2 + Y**2 - 1)**3 - (X**2) * (Y**3)
        fig, ax = plt.subplots(figsize=(6, 6))
        cs = ax.contour(X, Y, F, levels=[0], colors=('crimson',), linewidths=1.2)
        ax.set_aspect('equal', 'box')
        ax.axis('off')
        save_plot(fig, filename)
    except Exception as e:
        print(f"绘制代数心形曲线时出错: {e}")

# 6. 倒心形（Inverse Heart Curve）
def plot_inverse_heart(filename='inverse_heart.png'):
    """绘制倒心形曲线并保存"""
    try:
        t = np.linspace(0, 2*np.pi, 2000)
        x = 16 * np.sin(t)**3
        y = 13 * np.cos(t) - 5 * np.cos(2*t) - 2 * np.cos(3*t) - np.cos(4*t)
        # 适当缩放使图形居中
        x /= 17.0
        y /= 17.0
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.plot(x, y, color='firebrick', linewidth=1.6)
        ax.set_aspect('equal', 'box')
        ax.axis('off')
        save_plot(fig, filename)
    except Exception as e:
        print(f"绘制倒心形曲线时出错: {e}")

# 7. 笛卡尔心形（Cartesian Heart Curve）
def plot_cartesian_heart(filename='cartesian_heart.png'):
    """绘制笛卡尔心形曲线并保存"""
    try:
        x = np.linspace(-1.5, 1.5, 2000)
        term1 = 1 - x**2
        term2 = x**2 - 1
        y_pos = np.sqrt(np.abs(term1)) * np.sqrt(np.abs(term2))
        mask = np.isfinite(y_pos) & (term1 >= 0)
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.plot(x[mask], y_pos[mask], color='darkred', linewidth=2)
        ax.plot(x[mask], -y_pos[mask], color='darkred', linewidth=2)
        ax.set_aspect('equal', 'box')
        ax.axis('off')
        save_plot(fig, filename)
    except Exception as e:
        print(f"绘制笛卡尔心形曲线时出错: {e}")

# 组合绘图：将所有曲线放在一个画布上
def plot_all_together(filename='all_together.png'):
    """将所有曲线放在一个画布中展示并保存"""
    try:
        fig, axes = plt.subplots(3, 3, figsize=(12, 12))
        axes = axes.flatten()
        # 绘制每个曲线
        plot_cardioid_on_ax(axes[0])
        plot_butterfly_on_ax(axes[1])
        plot_rose_on_ax(axes[2])
        plot_ellipse_on_ax(axes[3])
        plot_algebraic_heart_on_ax(axes[4])
        plot_inverse_heart_on_ax(axes[5])
        plot_cartesian_heart_on_ax(axes[6])
        # 空白占位符
        axes[7].axis('off')
        axes[8].axis('off')
        plt.tight_layout()
        save_plot(fig, filename)
    except Exception as e:
        print(f"绘制组合图时出错: {e}")
if __name__ == '__main__':
    # 调用每个绘图函数，逐个保存
    plot_cardioid('heart_cardioid.png')
    plot_butterfly('butterfly.png')
    plot_rose('rose.png')  # 默认 a=1, k=5
    plot_ellipse('ellipse.png', a=2.0, b=1.0)
    plot_algebraic_heart('heart_algebraic.png')
    plot_inverse_heart('inverse_heart.png')
    plot_cartesian_heart('cartesian_heart.png')
    plot_all_together('all_together.png')
    print("Finished: saved images to current directory.")
