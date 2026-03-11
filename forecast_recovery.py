#!/usr/bin/env python3
"""
霍尔木兹危机缓和后一个月推演图 — 基于规则引擎（非LLM）
假设3月15日美伊巴黎谈判达成初步共识，3月18日海峡部分重开
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

# ═══════════════════════════════════════════
# 场景假设与数据
# ═══════════════════════════════════════════

# 交易日（跳过周末）
dates = [
    # Week 1: 3/11-3/14 (危机尾声)
    "3/11", "3/12", "3/13", "3/14",
    # Week 2: 3/15 谈判突破 → 3/18 海峡重开
    "3/15", "3/16", "3/17", "3/18", "3/19",
    # Week 3
    "3/22", "3/23", "3/24", "3/25", "3/26",
    # Week 4
    "3/29", "3/30", "3/31", "4/1", "4/2",
    # Week 5
    "4/5", "4/6", "4/7", "4/8", "4/9",
]

# 恒指走势（人工建模）
hsi = [
    # Week 1: 底部震荡
    23600, 23450, 23300, 23400,
    # Week 2: 谈判消息→跳空高开→海峡重开确认
    24200, 24600, 24500, 25100, 25400,
    # Week 3: 快速回补
    25600, 25800, 25500, 25700, 25900,
    # Week 4: 回归正常化
    26000, 25800, 26100, 26200, 26350,
    # Week 5: 收敛到新均衡
    26300, 26400, 26200, 26350, 26500,
]

oil = [
    # Week 1: 高位震荡
    95, 93, 91, 90,
    # Week 2: 谈判→油价悬崖式跌
    82, 78, 76, 72, 70,
    # Week 3: 继续回落
    69, 68, 70, 69, 67,
    # Week 4: 接近正常
    66, 67, 65, 64, 63,
    # Week 5: 新均衡
    64, 63, 64, 63, 62,
]

# 关键事件标注
events = {
    0: ("当前", "#FFD54F"),
    4: ("美伊巴黎\n谈判突破", "#4CAF50"),
    7: ("海峡\n部分重开", "#4CAF50"),
    11: ("小米Q4\n财报", "#64B5F6"),
    15: ("特朗普\n访华", "#FFD54F"),
}

# ═══════════════════════════════════════════
# Agent行为建模 — 基于已验证的行为规则
# ═══════════════════════════════════════════

# 行为: 2=强买, 1=轻买, 0=持有, -1=轻卖, -2=强卖
# 情绪: 0=冷静, 1=焦虑, 2=FOMO, 3=贪婪, 4=恐惧, 5=恐慌

agents = {
    "对冲基金": {
        "color": "#E53935",
        "actions": [
            # W1: 还在做空，但开始减仓
            0, 0, 1, 1,
            # W2: 谈判消息→紧急平空头→反手做多
            1, 2, 1, 2, 1,
            # W3: 做多获利→开始减仓
            0, 0, -1, 0, -1,
            # W4: 波段操作
            0, -1, 1, 0, 0,
            # W5: 回归正常
            0, 0, -1, 0, 0,
        ],
        "emotions": [
            1, 1, 1, 0,  # W1: 焦虑→冷静
            2, 3, 2, 2, 0,  # W2: FOMO→贪婪→回归
            0, 0, 0, 0, 0,  # W3: 冷静
            0, 0, 0, 0, 0,  # W4
            0, 0, 0, 0, 0,  # W5
        ],
    },
    "长线外资": {
        "color": "#1E88E5",
        "actions": [
            # W1: 继续观望
            0, 0, 0, 0,
            # W2: 谈判→启动内部评估(3天)→开始买
            0, 0, 0, 1, 1,
            # W3: 缓慢建仓（每天回补总量的15-20%）
            1, 1, 0, 1, 1,
            # W4: 继续建仓
            1, 0, 1, 1, 0,
            # W5: 接近目标配置，减速
            0, 1, 0, 0, 0,
        ],
        "emotions": [
            1, 1, 1, 1,  # W1: 焦虑
            1, 1, 0, 0, 0,  # W2: 焦虑→冷静
            0, 0, 0, 0, 0,  # W3: 冷静
            0, 0, 0, 0, 0,  # W4
            0, 0, 0, 0, 0,  # W5
        ],
    },
    "南下资金": {
        "color": "#FB8C00",
        "actions": [
            # W1: 焦虑持有
            0, 0, 0, 0,
            # W2: 谈判消息→FOMO抄底
            2, 2, 1, 2, 1,
            # W3: 继续买但开始犹豫
            1, 0, -1, 1, 0,
            # W4: 情绪消退
            0, -1, 0, 0, 0,
            # W5: 回归正常
            0, 0, 0, 0, 0,
        ],
        "emotions": [
            1, 1, 4, 1,  # W1: 焦虑
            2, 2, 2, 3, 2,  # W2: FOMO→贪婪
            2, 1, 1, 0, 0,  # W3: FOMO消退
            0, 0, 0, 0, 0,  # W4
            0, 0, 0, 0, 0,  # W5
        ],
    },
    "价值投资者": {
        "color": "#43A047",
        "actions": [
            # W1: 全程hold（跌幅不够）
            0, 0, 0, 0,
            # W2: 反弹开始→错过底部→继续hold
            0, 0, 0, 0, 0,
            # W3: hold
            0, 0, 0, 0, 0,
            # W4: hold
            0, 0, 0, 0, 0,
            # W5: hold
            0, 0, 0, 0, 0,
        ],
        "emotions": [
            0, 0, 0, 0,
            0, 0, 0, 0, 0,
            0, 0, 0, 0, 0,
            0, 0, 0, 0, 0,
            0, 0, 0, 0, 0,
        ],
    },
}

emotion_label = {0: "冷静", 1: "焦虑", 2: "FOMO", 3: "贪婪", 4: "恐惧", 5: "恐慌"}
emotion_color = {0: "#4CAF50", 1: "#FFC107", 2: "#FF9800", 3: "#E91E63", 4: "#9C27B0", 5: "#F44336"}
action_label = {-2: "强卖", -1: "轻卖", 0: "持有", 1: "轻买", 2: "强买"}
action_color_map = {-2: "#F44336", -1: "#FF9800", 0: "#666", 1: "#8BC34A", 2: "#4CAF50"}

n = len(dates)
x = np.arange(n)

# ═══════════════════════════════════════════
# 绘图
# ═══════════════════════════════════════════

fig = plt.figure(figsize=(24, 18), facecolor="#0D1117")
fig.suptitle("霍尔木兹危机缓和推演 | 海峡重开后一个月", fontsize=22,
             fontweight="bold", color="white", y=0.97)

from matplotlib.gridspec import GridSpec
gs = GridSpec(4, 1, height_ratios=[2, 0.8, 1.5, 1.2], hspace=0.25,
              left=0.06, right=0.94, top=0.93, bottom=0.04)

# ── 图1: 恒指 + 油价双轴 ──
ax1 = fig.add_subplot(gs[0])
ax1.set_facecolor("#0D1117")
ax1_oil = ax1.twinx()

# 恒指
for i in range(1, n):
    c = "#26A69A" if hsi[i] >= hsi[i-1] else "#EF5350"
    ax1.fill_between([i-1, i], [hsi[i-1], hsi[i]], min(hsi)*0.995, color=c, alpha=0.06)
ax1.plot(x, hsi, color="#E0E0E0", linewidth=2.5, marker="o", markersize=4, zorder=5)

# 油价
ax1_oil.plot(x, oil, color="#FF7043", linewidth=2, linestyle="--", marker="s",
             markersize=3, alpha=0.8, label="布伦特原油 ($/桶)")
ax1_oil.fill_between(x, oil, min(oil)*0.95, color="#FF7043", alpha=0.05)

# 阶段分区
phase_spans = [
    (0, 3, "危机尾声", "#F44336", 0.06),
    (4, 8, "V型反转", "#4CAF50", 0.06),
    (9, 13, "快速回补", "#2196F3", 0.06),
    (14, 18, "正常化", "#9E9E9E", 0.04),
    (19, 23, "新均衡", "#9E9E9E", 0.03),
]
for start, end, label, color, alpha in phase_spans:
    ax1.axvspan(start - 0.5, end + 0.5, color=color, alpha=alpha)
    mid = (start + end) / 2
    ax1.text(mid, max(hsi) * 1.005, label, ha="center", va="bottom",
            fontsize=10, color=color, fontweight="bold", alpha=0.8)

# 关键事件
for idx, (label, color) in events.items():
    ax1.annotate(label, xy=(idx, hsi[idx]),
                xytext=(0, -50), textcoords="offset points",
                fontsize=9, ha="center", color=color, fontweight="bold",
                arrowprops=dict(arrowstyle="-", color=color, lw=1, ls="--"),
                bbox=dict(boxstyle="round,pad=0.3", fc="#1A237E", ec=color, alpha=0.8))

# Agent力量箭头
hsi_range = max(hsi) - min(hsi)
arrow_base = hsi_range * 0.15
agent_names = list(agents.keys())
for ai, (name, cfg) in enumerate(agents.items()):
    for i in range(n):
        act = cfg["actions"][i]
        if act == 0:
            continue
        direction = 1 if act > 0 else -1
        strength = abs(act) / 2.0
        y_start = hsi[i]
        y_end = y_start + direction * arrow_base * strength
        x_off = (ai - 1.5) * 0.12
        ax1.annotate("",
            xy=(i + x_off, y_end), xytext=(i + x_off, y_start),
            arrowprops=dict(arrowstyle="->,head_width=0.3,head_length=0.2",
                           color=cfg["color"], lw=1.5 + strength * 1.5,
                           alpha=0.5 + strength * 0.4),
            zorder=8)

ax1.set_xticks(x)
ax1.set_xticklabels(dates, color="#999", fontsize=9, rotation=45)
ax1.set_ylabel("恒生指数", color="#999", fontsize=12)
ax1_oil.set_ylabel("布伦特原油 ($/桶)", color="#FF7043", fontsize=11)
ax1.tick_params(colors="#666")
ax1_oil.tick_params(colors="#FF7043")
ax1.spines[:].set_color("#333")
ax1_oil.spines[:].set_color("#333")

legend_elements = [mpatches.Patch(color=c["color"], label=n) for n, c in agents.items()]
legend_elements.append(plt.Line2D([0], [0], color="#FF7043", linestyle="--", label="布伦特原油"))
ax1.legend(handles=legend_elements, loc="upper left", fontsize=9,
          facecolor="#1a1a2e", edgecolor="#333", labelcolor="white", ncol=5)

# ── 图2: 油价变化率 ──
ax_oil2 = fig.add_subplot(gs[1])
ax_oil2.set_facecolor("#0D1117")
oil_changes = [0] + [(oil[i] - oil[i-1]) / oil[i-1] * 100 for i in range(1, n)]
bar_colors = ["#26A69A" if c <= 0 else "#EF5350" for c in oil_changes]  # 油价跌=利好
ax_oil2.bar(x, oil_changes, color=bar_colors, alpha=0.7, width=0.6)
ax_oil2.axhline(y=0, color="#444", linewidth=0.5)
ax_oil2.set_xticks(x)
ax_oil2.set_xticklabels(dates, color="#999", fontsize=8, rotation=45)
ax_oil2.set_ylabel("油价日变%", color="#999", fontsize=10)
ax_oil2.set_title("油价变化率 (绿=利好港股)", color="#CCC", fontsize=11, pad=5)
ax_oil2.tick_params(colors="#666")
ax_oil2.spines[:].set_color("#333")

# ── 图3: Agent行为热力图 ──
ax3 = fig.add_subplot(gs[2])
ax3.set_facecolor("#0D1117")

action_matrix = np.array([agents[name]["actions"] for name in agent_names])

# 用 RdYlGn colormap: 红=卖, 黄=持有, 绿=买
from matplotlib.colors import TwoSlopeNorm
norm = TwoSlopeNorm(vmin=-2, vcenter=0, vmax=2)
im = ax3.imshow(action_matrix, cmap="RdYlGn", aspect="auto", norm=norm, interpolation="nearest")

ax3.set_yticks(range(len(agent_names)))
ax3.set_yticklabels(agent_names, color="#CCC", fontsize=11)
ax3.set_xticks(x)
ax3.set_xticklabels(dates, color="#999", fontsize=8, rotation=45)
ax3.set_title("Agent 操作热力图 (红=卖出  黄=持有  绿=买入)", color="#CCC", fontsize=12, pad=8)

# 标注文字
for i, name in enumerate(agent_names):
    for j in range(n):
        act = agents[name]["actions"][j]
        label = action_label[act]
        tc = "white" if abs(act) >= 2 else ("#CCC" if act != 0 else "#666")
        ax3.text(j, i, label, ha="center", va="center", fontsize=7,
                color=tc, fontweight="bold")

cbar = plt.colorbar(im, ax=ax3, shrink=0.6, pad=0.02)
cbar.set_label("操作方向", color="#999", fontsize=9)
cbar.ax.tick_params(colors="#666")

# ── 图4: Agent情绪时间线 ──
ax4 = fig.add_subplot(gs[3])
ax4.set_facecolor("#0D1117")

emotion_matrix = np.array([agents[name]["emotions"] for name in agent_names])
im2 = ax4.imshow(emotion_matrix, cmap="YlOrRd", aspect="auto", vmin=0, vmax=5,
                 interpolation="nearest")

ax4.set_yticks(range(len(agent_names)))
ax4.set_yticklabels(agent_names, color="#CCC", fontsize=11)
ax4.set_xticks(x)
ax4.set_xticklabels(dates, color="#999", fontsize=8, rotation=45)
ax4.set_title("Agent 情绪变化 (0=冷静 → 5=恐慌)", color="#CCC", fontsize=12, pad=8)

for i, name in enumerate(agent_names):
    for j in range(n):
        emo = agents[name]["emotions"][j]
        label = emotion_label[emo]
        tc = "white" if emo >= 3 else ("#CCC" if emo > 0 else "#666")
        ax4.text(j, i, label, ha="center", va="center", fontsize=7,
                color=tc, fontweight="bold")

cbar2 = plt.colorbar(im2, ax=ax4, shrink=0.6, pad=0.02)
cbar2.set_label("情绪强度", color="#999", fontsize=9)
cbar2.ax.tick_params(colors="#666")

# 保存
out = Path("output/reports/hormuz_recovery_forecast.png")
out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor="#0D1117")
plt.close()
print(f"✅ 推演图已保存: {out}")
