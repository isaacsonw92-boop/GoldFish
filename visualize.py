#!/usr/bin/env python3
"""
港股沙盘模拟 - 数据可视化
生成四张图：恒指走势+情绪热力图+Agent行为时间线+资金流向
"""
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

# 中文字体
plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "Noto Sans CJK SC",
                                    "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def load_logs(log_dir: str) -> list[dict]:
    """加载所有日志文件"""
    logs = []
    for f in sorted(Path(log_dir).glob("*.json")):
        with open(f, "r", encoding="utf-8") as fh:
            logs.append(json.load(fh))
    return logs


def plot_dashboard(logs: list[dict], output_path: str, scenario_name: str = ""):
    """生成综合仪表盘"""
    dates = [log["date"] for log in logs]
    short_dates = [d[5:] for d in dates]  # MM-DD

    hsi = [log["market_state"]["hsi_close"] for log in logs]
    changes = [log["market_state"]["daily_change_pct"] for log in logs]

    # 提取每个Agent的行为和情绪
    agent_names = ["对冲基金", "长线外资", "南下资金", "价值投资者"]
    agent_en = ["HedgeFund", "LongOnly", "Southbound", "ValueInvestor"]

    action_map = {
        "buy": 2, "cover_short": 1, "hold": 0,
        "sell": -1, "add_short": -2
    }
    action_label = {
        "buy": "买入", "cover_short": "平空头", "hold": "持有",
        "sell": "卖出", "add_short": "加空"
    }
    emotion_map = {
        "calm": 0, "anxiety": 1, "fomo": 2,
        "greed": 3, "fear": 4, "panic": 5
    }
    emotion_colors = {
        "calm": "#4CAF50", "anxiety": "#FFC107", "fomo": "#FF9800",
        "greed": "#E91E63", "fear": "#9C27B0", "panic": "#F44336"
    }

    # 构建数据矩阵
    actions = {name: [] for name in agent_names}
    emotions = {name: [] for name in agent_names}
    emotion_labels = {name: [] for name in agent_names}
    confidences = {name: [] for name in agent_names}

    for log in logs:
        decisions_by_agent = {}
        for d in log["decisions"]:
            decisions_by_agent[d["agent"]] = d

        for name in agent_names:
            if name in decisions_by_agent:
                d = decisions_by_agent[name]
                actions[name].append(action_map.get(d["action"], 0))
                emotions[name].append(emotion_map.get(d["emotion"], 0))
                emotion_labels[name].append(d["emotion"])
                confidences[name].append(d.get("confidence", 0.5))
            else:
                actions[name].append(0)
                emotions[name].append(0)
                emotion_labels[name].append("calm")
                confidences[name].append(0.5)

    # === 创建图表 ===
    fig = plt.figure(figsize=(18, 20))
    gs = GridSpec(4, 1, height_ratios=[1.2, 1, 1.2, 1], hspace=0.35)

    title = f"港股沙盘模拟 - {scenario_name}" if scenario_name else "港股沙盘模拟"
    fig.suptitle(title, fontsize=18, fontweight="bold", y=0.98)

    # --- 图1：恒指走势 + 涨跌幅 ---
    ax1 = fig.add_subplot(gs[0])
    ax1_twin = ax1.twinx()

    color_line = "#1565C0"
    ax1.plot(short_dates, hsi, color=color_line, linewidth=2.5, marker="o",
             markersize=6, zorder=5, label="恒生指数")
    ax1.fill_between(short_dates, min(hsi) * 0.98, hsi, alpha=0.1, color=color_line)

    # 涨跌幅柱状图
    bar_colors = ["#4CAF50" if c >= 0 else "#F44336" for c in changes]
    ax1_twin.bar(short_dates, changes, color=bar_colors, alpha=0.4, width=0.6, label="日涨跌幅%")
    ax1_twin.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)

    ax1.set_ylabel("恒生指数", fontsize=12, color=color_line)
    ax1_twin.set_ylabel("日涨跌幅 (%)", fontsize=12)
    ax1.set_title("恒生指数走势与日涨跌幅", fontsize=14, pad=10)
    ax1.tick_params(axis="x", rotation=45)
    ax1.grid(axis="y", alpha=0.3)

    # 标注关键事件
    for i, log in enumerate(logs):
        etype = log["event"].get("type", "")
        if etype in ("policy_bombshell", "black_swan", "expectation_miss",
                      "second_wave_crash", "political_signal", "strait_closure_confirmed"):
            label = {
                "policy_bombshell": "三部门\n联合救市",
                "black_swan": "史诗之怒\n行动",
                "expectation_miss": "发改委\n不及预期",
                "second_wave_crash": "黑色\n星期一",
                "political_signal": "政治局\n会议",
                "strait_closure_confirmed": "海峡\n封锁确认"
            }.get(etype, etype)
            ax1.annotate(label, xy=(short_dates[i], hsi[i]),
                        xytext=(0, 25), textcoords="offset points",
                        fontsize=8, ha="center", color="#D32F2F",
                        arrowprops=dict(arrowstyle="->", color="#D32F2F", lw=1.2))

    # --- 图2：情绪热力图 ---
    ax2 = fig.add_subplot(gs[1])

    emotion_matrix = []
    for name in agent_names:
        emotion_matrix.append(emotions[name])

    im = ax2.imshow(emotion_matrix, cmap="YlOrRd", aspect="auto",
                    vmin=0, vmax=5, interpolation="nearest")

    ax2.set_yticks(range(len(agent_names)))
    ax2.set_yticklabels(agent_names, fontsize=11)
    ax2.set_xticks(range(len(short_dates)))
    ax2.set_xticklabels(short_dates, fontsize=9, rotation=45)
    ax2.set_title("Agent 情绪热力图 (0=冷静 → 5=恐慌)", fontsize=14, pad=10)

    # 在每个格子里标注情绪文字
    for i, name in enumerate(agent_names):
        for j in range(len(short_dates)):
            emo = emotion_labels[name][j]
            emo_cn = {"calm": "冷静", "anxiety": "焦虑", "fomo": "FOMO",
                      "greed": "贪婪", "fear": "恐惧", "panic": "恐慌"}.get(emo, emo)
            text_color = "white" if emotions[name][j] >= 3 else "black"
            ax2.text(j, i, emo_cn, ha="center", va="center",
                    fontsize=8, color=text_color, fontweight="bold")

    cbar = plt.colorbar(im, ax=ax2, shrink=0.8)
    cbar.set_label("情绪强度", fontsize=10)

    # --- 图3：Agent行为时间线 ---
    ax3 = fig.add_subplot(gs[2])

    action_colors = {
        2: "#4CAF50",   # buy
        1: "#8BC34A",   # cover_short
        0: "#BDBDBD",   # hold
        -1: "#FF9800",  # sell
        -2: "#F44336",  # add_short
    }

    y_positions = list(range(len(agent_names)))
    bar_height = 0.6

    for i, name in enumerate(agent_names):
        for j in range(len(short_dates)):
            act = actions[name][j]
            color = action_colors.get(act, "#BDBDBD")
            conf = confidences[name][j]
            alpha = 0.4 + conf * 0.6  # 信心越高越不透明
            ax3.barh(i, 1, left=j - 0.5, height=bar_height,
                    color=color, alpha=alpha, edgecolor="white", linewidth=0.5)

    ax3.set_yticks(y_positions)
    ax3.set_yticklabels(agent_names, fontsize=11)
    ax3.set_xticks(range(len(short_dates)))
    ax3.set_xticklabels(short_dates, fontsize=9, rotation=45)
    ax3.set_title("Agent 行为时间线 (颜色=操作, 透明度=信心)", fontsize=14, pad=10)
    ax3.set_xlim(-0.5, len(short_dates) - 0.5)

    # 图例
    legend_patches = [
        mpatches.Patch(color="#4CAF50", label="买入"),
        mpatches.Patch(color="#8BC34A", label="平空头"),
        mpatches.Patch(color="#BDBDBD", label="持有"),
        mpatches.Patch(color="#FF9800", label="卖出"),
        mpatches.Patch(color="#F44336", label="加空"),
    ]
    ax3.legend(handles=legend_patches, loc="upper right", fontsize=9,
              ncol=5, framealpha=0.9)

    # 在格子里标注操作文字
    for i, name in enumerate(agent_names):
        for j in range(len(short_dates)):
            act_val = actions[name][j]
            act_text = {2: "买", 1: "平空", 0: "持", -1: "卖", -2: "空"}.get(act_val, "")
            text_color = "white" if act_val in (2, -2) else "black"
            ax3.text(j, i, act_text, ha="center", va="center",
                    fontsize=9, color=text_color, fontweight="bold")

    # --- 图4：综合信心指数 ---
    ax4 = fig.add_subplot(gs[3])

    agent_colors = {"对冲基金": "#F44336", "长线外资": "#2196F3",
                    "南下资金": "#FF9800", "价值投资者": "#4CAF50"}

    for name in agent_names:
        ax4.plot(short_dates, confidences[name], marker="s", markersize=5,
                linewidth=2, label=name, color=agent_colors[name])

    ax4.set_ylabel("决策信心", fontsize=12)
    ax4.set_title("Agent 决策信心变化", fontsize=14, pad=10)
    ax4.legend(fontsize=10, loc="lower left")
    ax4.set_ylim(0, 1.05)
    ax4.tick_params(axis="x", rotation=45)
    ax4.grid(alpha=0.3)
    ax4.axhline(y=0.5, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)

    # 保存
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"✅ 图表已保存: {output_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="港股沙盘可视化")
    parser.add_argument("--log-dir", default="output/logs", help="日志目录")
    parser.add_argument("--output", default="output/reports/dashboard.png", help="输出图片路径")
    parser.add_argument("--title", default="", help="场景名称")
    args = parser.parse_args()

    logs = load_logs(args.log_dir)
    if not logs:
        print("❌ 未找到日志文件")
        return

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    plot_dashboard(logs, args.output, args.title)


if __name__ == "__main__":
    main()
