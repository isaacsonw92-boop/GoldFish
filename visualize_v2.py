#!/usr/bin/env python3
"""
港股沙盘模拟 - V2 战场态势可视化
把Agent画成在价格线上博弈的力量箭头，更直觉更生动
"""
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import numpy as np

plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def load_logs(log_dir: str) -> list[dict]:
    logs = []
    for f in sorted(Path(log_dir).glob("*.json")):
        with open(f, "r", encoding="utf-8") as fh:
            logs.append(json.load(fh))
    return logs


# ── Agent 视觉配置 ──
AGENT_STYLE = {
    "对冲基金":  {"color": "#E53935", "marker": "v", "label_en": "Hedge Fund",   "y_slot": 0},
    "长线外资":  {"color": "#1E88E5", "marker": "D", "label_en": "Long-Only",    "y_slot": 1},
    "南下资金":  {"color": "#FB8C00", "marker": "^", "label_en": "Southbound",   "y_slot": 2},
    "价值投资者": {"color": "#43A047", "marker": "s", "label_en": "Value",        "y_slot": 3},
}

ACTION_ARROW = {
    "buy":         {"dy": 1,  "label": "买", "intensity": 1.0},
    "cover_short": {"dy": 1,  "label": "平空", "intensity": 0.6},
    "hold":        {"dy": 0,  "label": "持", "intensity": 0.0},
    "sell":        {"dy": -1, "label": "卖", "intensity": 1.0},
    "add_short":   {"dy": -1, "label": "空", "intensity": 1.0},
}

EMOTION_FACE = {
    "calm": "冷静", "anxiety": "焦虑", "fomo": "FOMO",
    "greed": "贪婪", "fear": "恐惧", "panic": "恐慌",
}

EMOTION_COLOR = {
    "calm": "#4CAF50", "anxiety": "#FFC107", "fomo": "#FF9800",
    "greed": "#E91E63", "fear": "#9C27B0", "panic": "#F44336",
}


def plot_battlefield(logs, output_path, scenario_name=""):
    n = len(logs)
    dates = [l["date"][5:] for l in logs]
    hsi = [l["market_state"]["hsi_close"] for l in logs]
    changes = [l["market_state"]["daily_change_pct"] for l in logs]

    fig = plt.figure(figsize=(20, 14), facecolor="#0D1117")
    gs = GridSpec(3, 1, height_ratios=[2.5, 1, 0.8], hspace=0.15,
                  left=0.07, right=0.93, top=0.92, bottom=0.06)

    title = f"港股沙盘 | {scenario_name}" if scenario_name else "港股沙盘"
    fig.suptitle(title, fontsize=22, fontweight="bold", color="white", y=0.97)

    # ═══════════════════════════════════════════
    # 图1: 战场主图 — 价格线 + Agent力量箭头
    # ═══════════════════════════════════════════
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor("#0D1117")

    # 价格区域填充
    hsi_arr = np.array(hsi)
    x = np.arange(n)
    # 涨跌着色
    for i in range(1, n):
        c = "#26A69A" if hsi[i] >= hsi[i-1] else "#EF5350"
        ax1.fill_between([i-1, i], [hsi[i-1], hsi[i]], min(hsi)*0.995, color=c, alpha=0.08)

    # 主价格线
    ax1.plot(x, hsi, color="#E0E0E0", linewidth=2.5, zorder=5, alpha=0.9)
    ax1.scatter(x, hsi, color="white", s=30, zorder=6, edgecolors="#555", linewidths=0.5)

    # 在价格线上标注每日涨跌
    for i in range(n):
        c_text = "#26A69A" if changes[i] >= 0 else "#EF5350"
        sign = "+" if changes[i] >= 0 else ""
        ax1.annotate(f"{sign}{changes[i]:.1f}%",
                     xy=(i, hsi[i]), xytext=(0, 14), textcoords="offset points",
                     fontsize=8, color=c_text, ha="center", fontweight="bold")

    # Agent力量箭头
    hsi_range = max(hsi) - min(hsi)
    arrow_base_len = hsi_range * 0.12  # 箭头基础长度

    for log_idx, log in enumerate(logs):
        decisions_by_name = {d["agent"]: d for d in log["decisions"]}

        for agent_name, style in AGENT_STYLE.items():
            if agent_name not in decisions_by_name:
                continue
            d = decisions_by_name[agent_name]
            act = d["action"]
            conf = d.get("confidence", 0.5)
            emotion = d.get("emotion", "calm")
            arrow_info = ACTION_ARROW.get(act, ACTION_ARROW["hold"])

            if arrow_info["dy"] == 0:
                # hold: 画一个小圆点
                dot_y = hsi[log_idx] + (style["y_slot"] - 1.5) * hsi_range * 0.02
                ax1.scatter(log_idx, dot_y, color=style["color"], marker="o",
                           s=25, alpha=0.3, zorder=7)
                continue

            # 箭头：方向=买/卖，长度=信心，颜色=Agent
            arrow_len = arrow_base_len * conf * arrow_info["intensity"]
            y_start = hsi[log_idx]
            y_end = y_start + arrow_info["dy"] * arrow_len

            # 微调x避免重叠
            x_offset = (style["y_slot"] - 1.5) * 0.12
            xi = log_idx + x_offset

            ax1.annotate("",
                xy=(xi, y_end), xytext=(xi, y_start),
                arrowprops=dict(
                    arrowstyle="->,head_width=0.4,head_length=0.3",
                    color=style["color"],
                    lw=2.0 + conf * 1.5,
                    alpha=0.5 + conf * 0.5,
                ),
                zorder=8)

            # 箭头尖端放情绪标签
            emo_label = EMOTION_FACE.get(emotion, "")
            emo_color = EMOTION_COLOR.get(emotion, "#999")
            ax1.text(xi, y_end + arrow_info["dy"] * hsi_range * 0.015,
                    emo_label,
                    fontsize=7, ha="center", va="center", zorder=9,
                    color=emo_color, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.15", fc="#0D1117", ec=emo_color, alpha=0.7, lw=0.5))

    # 关键事件标注
    event_labels = {
        "policy_bombshell": "三部门\n联合救市",
        "black_swan": "史诗之怒\n行动",
        "expectation_miss": "发改委\n不及预期",
        "second_wave_crash": "黑色\n星期一",
        "political_signal": "政治局\n会议",
        "strait_closure_confirmed": "海峡\n封锁确认",
    }
    for i, log in enumerate(logs):
        etype = log["event"].get("type", "")
        if etype in event_labels:
            ax1.annotate(event_labels[etype],
                xy=(i, hsi[i]), xytext=(0, -55), textcoords="offset points",
                fontsize=9, ha="center", color="#FFD54F", fontweight="bold",
                arrowprops=dict(arrowstyle="-", color="#FFD54F", lw=1, ls="--"),
                bbox=dict(boxstyle="round,pad=0.3", fc="#1A237E", ec="#FFD54F", alpha=0.8))

    ax1.set_xticks(x)
    ax1.set_xticklabels(dates, color="#999", fontsize=10)
    ax1.set_ylabel("恒生指数", color="#999", fontsize=12)
    ax1.tick_params(colors="#666")
    ax1.spines[:].set_color("#333")
    ax1.grid(axis="y", color="#1a1a2e", alpha=0.5)

    # Agent图例
    legend_elements = []
    for name, s in AGENT_STYLE.items():
        legend_elements.append(mpatches.Patch(color=s["color"], label=f"{name}"))
    legend_elements.append(mpatches.Patch(color="#26A69A", label="↑ 买入力量"))
    legend_elements.append(mpatches.Patch(color="#EF5350", label="↓ 卖出力量"))
    ax1.legend(handles=legend_elements, loc="upper right", fontsize=9,
              facecolor="#1a1a2e", edgecolor="#333", labelcolor="white",
              ncol=3, framealpha=0.9)

    # ═══════════════════════════════════════════
    # 图2: 多空力量对比柱状图
    # ═══════════════════════════════════════════
    ax2 = fig.add_subplot(gs[1])
    ax2.set_facecolor("#0D1117")

    bull_power = []  # 多方力量
    bear_power = []  # 空方力量

    for log in logs:
        bp, sp = 0, 0
        for d in log["decisions"]:
            conf = d.get("confidence", 0.5)
            act = d["action"]
            if act in ("buy", "cover_short"):
                bp += conf * (1.0 if act == "buy" else 0.6)
            elif act in ("sell", "add_short"):
                sp += conf * (1.0 if act in ("sell", "add_short") else 0.6)
        bull_power.append(bp)
        bear_power.append(-sp)

    bar_width = 0.4
    ax2.bar(x, bull_power, width=bar_width, color="#26A69A", alpha=0.8, label="多方力量")
    ax2.bar(x, bear_power, width=bar_width, color="#EF5350", alpha=0.8, label="空方力量")
    ax2.axhline(y=0, color="#444", linewidth=0.8)

    # 净力量线
    net = [b + s for b, s in zip(bull_power, bear_power)]
    ax2.plot(x, net, color="#FFD54F", linewidth=2, marker="D", markersize=5,
            label="净力量", zorder=5)

    ax2.set_xticks(x)
    ax2.set_xticklabels(dates, color="#999", fontsize=10)
    ax2.set_ylabel("力量强度", color="#999", fontsize=11)
    ax2.tick_params(colors="#666")
    ax2.spines[:].set_color("#333")
    ax2.legend(loc="upper right", fontsize=9, facecolor="#1a1a2e",
              edgecolor="#333", labelcolor="white", ncol=3)
    ax2.set_title("多空力量对比", color="#CCC", fontsize=13, pad=8)

    # ═══════════════════════════════════════════
    # 图3: Agent状态条 — emoji时间轴
    # ═══════════════════════════════════════════
    ax3 = fig.add_subplot(gs[2])
    ax3.set_facecolor("#0D1117")
    ax3.set_xlim(-0.5, n - 0.5)
    ax3.set_ylim(-0.6, 3.8)

    agent_order = list(AGENT_STYLE.keys())
    for log_idx, log in enumerate(logs):
        decisions_by_name = {d["agent"]: d for d in log["decisions"]}
        for ai, agent_name in enumerate(agent_order):
            if agent_name not in decisions_by_name:
                continue
            d = decisions_by_name[agent_name]
            act = d["action"]
            emotion = d.get("emotion", "calm")

            # 操作标签
            act_label = ACTION_ARROW.get(act, {}).get("label", "?")
            act_color = "#26A69A" if ACTION_ARROW.get(act, {}).get("dy", 0) > 0 else \
                        "#EF5350" if ACTION_ARROW.get(act, {}).get("dy", 0) < 0 else "#666"

            emoji = EMOTION_FACE.get(emotion, "")
            emo_c = EMOTION_COLOR.get(emotion, "#666")
            ax3.text(log_idx, ai, f"{act_label}",
                    ha="center", va="center", fontsize=9, color=act_color,
                    fontweight="bold")
            # 情绪小标签在下方
            ax3.text(log_idx, ai - 0.25, emoji,
                    ha="center", va="center", fontsize=6.5, color=emo_c, alpha=0.8)

    ax3.set_xticks(x)
    ax3.set_xticklabels(dates, color="#999", fontsize=9)
    ax3.set_yticks(range(len(agent_order)))
    ax3.set_yticklabels(agent_order, color="#CCC", fontsize=10)
    ax3.tick_params(colors="#666", length=0)
    ax3.spines[:].set_color("#333")
    for spine in ax3.spines.values():
        spine.set_visible(False)

    # 保存
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="#0D1117")
    plt.close()
    print(f"✅ 图表已保存: {output_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", default="output/logs")
    parser.add_argument("--output", default="output/reports/battlefield.png")
    parser.add_argument("--title", default="")
    args = parser.parse_args()

    logs = load_logs(args.log_dir)
    if not logs:
        print("❌ 未找到日志文件")
        return

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    plot_battlefield(logs, args.output, args.title)


if __name__ == "__main__":
    main()
