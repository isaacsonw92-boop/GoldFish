"""
港股沙盘模拟 - Agent记忆系统
每个Agent拥有完整的状态记忆：仓位、历史决策、盈亏、情绪轨迹
记忆可持久化到JSON，也可跨场景加载
"""
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class PositionState:
    """持仓状态"""
    direction: str = "flat"          # "long", "short", "flat"
    size_pct: float = 0.0            # 仓位大小（%）
    avg_entry_price: float = 0.0     # 平均入场价
    unrealized_pnl_pct: float = 0.0  # 未实现盈亏（%）
    realized_pnl_pct: float = 0.0    # 已实现盈亏（%）
    days_held: int = 0               # 持仓天数

    def to_prompt(self) -> str:
        """生成供prompt使用的仓位描述"""
        if self.direction == "flat" or self.size_pct == 0:
            return "当前空仓，无持仓。"

        dir_cn = {"long": "多头", "short": "空头"}.get(self.direction, self.direction)
        pnl_str = f"+{self.unrealized_pnl_pct:.1f}%" if self.unrealized_pnl_pct >= 0 else f"{self.unrealized_pnl_pct:.1f}%"

        return (
            f"当前持仓：{dir_cn} {self.size_pct:.1f}%，"
            f"入场均价 {self.avg_entry_price:.0f}，"
            f"浮盈亏 {pnl_str}，"
            f"已持有 {self.days_held} 个交易日。"
            f"累计已实现盈亏：{self.realized_pnl_pct:+.1f}%。"
        )


@dataclass
class DailyMemory:
    """单日记忆"""
    date: str
    action: str
    position_change_pct: float
    reasoning: str
    emotion: str
    confidence: float
    top_concern: str
    hsi_close: float
    daily_change_pct: float
    position_after: dict = field(default_factory=dict)  # PositionState快照


class AgentMemory:
    """Agent完整记忆"""

    def __init__(self, agent_name: str, agent_name_en: str):
        self.agent_name = agent_name
        self.agent_name_en = agent_name_en
        self.position = PositionState()
        self.daily_log: list[DailyMemory] = []
        self.emotion_trajectory: list[str] = []
        self.trade_count: int = 0

    def update(self, decision: dict, market_state: dict):
        """根据决策更新记忆"""
        action = decision.get("action", "hold")
        change_pct = decision.get("position_change_pct", 0)
        hsi = market_state.get("hsi_close", 0)

        # 更新仓位
        self._update_position(action, change_pct, hsi)

        # 更新浮盈亏
        if self.position.direction != "flat" and self.position.avg_entry_price > 0:
            if self.position.direction == "long":
                self.position.unrealized_pnl_pct = (hsi - self.position.avg_entry_price) / self.position.avg_entry_price * 100
            elif self.position.direction == "short":
                self.position.unrealized_pnl_pct = (self.position.avg_entry_price - hsi) / self.position.avg_entry_price * 100

        # 持仓天数
        if self.position.direction != "flat":
            self.position.days_held += 1
        else:
            self.position.days_held = 0

        # 记录每日记忆
        daily = DailyMemory(
            date=decision.get("date", ""),
            action=action,
            position_change_pct=change_pct,
            reasoning=decision.get("reasoning", ""),
            emotion=decision.get("emotion", "calm"),
            confidence=decision.get("confidence", 0.5),
            top_concern=decision.get("top_concern", ""),
            hsi_close=hsi,
            daily_change_pct=market_state.get("daily_change_pct", 0),
            position_after=asdict(self.position),
        )
        self.daily_log.append(daily)
        self.emotion_trajectory.append(decision.get("emotion", "calm"))

        if action != "hold":
            self.trade_count += 1

    def _update_position(self, action: str, change_pct: float, current_price: float):
        """根据操作更新仓位状态"""
        if action == "buy":
            if self.position.direction == "short":
                # 先平空头再建多头
                self.position.realized_pnl_pct += self.position.unrealized_pnl_pct * (self.position.size_pct / 100)
                self.position.direction = "long"
                self.position.size_pct = change_pct
                self.position.avg_entry_price = current_price
                self.position.unrealized_pnl_pct = 0
            elif self.position.direction == "long":
                # 加仓：更新均价
                old_val = self.position.size_pct * self.position.avg_entry_price
                new_val = change_pct * current_price
                total_size = self.position.size_pct + change_pct
                if total_size > 0:
                    self.position.avg_entry_price = (old_val + new_val) / total_size
                self.position.size_pct = total_size
            else:
                # 从空仓建多头
                self.position.direction = "long"
                self.position.size_pct = change_pct
                self.position.avg_entry_price = current_price
                self.position.unrealized_pnl_pct = 0

        elif action == "sell":
            if self.position.direction == "long":
                # 卖出多头
                sell_pct = min(change_pct, self.position.size_pct)
                self.position.realized_pnl_pct += self.position.unrealized_pnl_pct * (sell_pct / max(self.position.size_pct, 0.01))
                self.position.size_pct -= sell_pct
                if self.position.size_pct <= 0.01:
                    self.position.direction = "flat"
                    self.position.size_pct = 0
                    self.position.unrealized_pnl_pct = 0
            elif self.position.direction == "flat":
                # 空仓卖出 = 开空
                self.position.direction = "short"
                self.position.size_pct = change_pct
                self.position.avg_entry_price = current_price
                self.position.unrealized_pnl_pct = 0

        elif action == "cover_short":
            if self.position.direction == "short":
                cover_pct = min(change_pct, self.position.size_pct)
                self.position.realized_pnl_pct += self.position.unrealized_pnl_pct * (cover_pct / max(self.position.size_pct, 0.01))
                self.position.size_pct -= cover_pct
                if self.position.size_pct <= 0.01:
                    self.position.direction = "flat"
                    self.position.size_pct = 0
                    self.position.unrealized_pnl_pct = 0

        elif action == "add_short":
            if self.position.direction == "short":
                # 加空
                old_val = self.position.size_pct * self.position.avg_entry_price
                new_val = change_pct * current_price
                total_size = self.position.size_pct + change_pct
                if total_size > 0:
                    self.position.avg_entry_price = (old_val + new_val) / total_size
                self.position.size_pct = total_size
            elif self.position.direction == "flat":
                self.position.direction = "short"
                self.position.size_pct = change_pct
                self.position.avg_entry_price = current_price
                self.position.unrealized_pnl_pct = 0

    def to_prompt_context(self, lookback: int = 5) -> str:
        """生成供Agent prompt使用的记忆上下文"""
        parts = []

        # 仓位状态
        parts.append(f"## 你的当前仓位\n{self.position.to_prompt()}")

        # 最近N天历史
        if self.daily_log:
            recent = self.daily_log[-lookback:]
            history_lines = []
            for m in recent:
                pnl_info = ""
                pos = m.position_after
                if pos.get("direction") != "flat":
                    pnl_info = f" | 浮盈亏{pos.get('unrealized_pnl_pct', 0):+.1f}%"
                history_lines.append(
                    f"  - {m.date}: {m.action}({m.emotion}, 信心{m.confidence}){pnl_info} — {m.reasoning[:40]}"
                )
            parts.append(f"## 你的最近{len(recent)}天操作记录\n" + "\n".join(history_lines))

        # 情绪轨迹摘要
        if len(self.emotion_trajectory) >= 3:
            recent_emo = self.emotion_trajectory[-5:]
            parts.append(f"## 你的情绪轨迹\n  最近: {' → '.join(recent_emo)}")

        # 交易统计
        parts.append(f"## 交易统计\n  总交易次数: {self.trade_count}，累计已实现盈亏: {self.position.realized_pnl_pct:+.1f}%")

        return "\n\n".join(parts)

    def save(self, path: str):
        """持久化记忆到JSON"""
        data = {
            "agent_name": self.agent_name,
            "agent_name_en": self.agent_name_en,
            "position": asdict(self.position),
            "daily_log": [asdict(m) for m in self.daily_log],
            "emotion_trajectory": self.emotion_trajectory,
            "trade_count": self.trade_count,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "AgentMemory":
        """从JSON加载记忆"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        mem = cls(data["agent_name"], data["agent_name_en"])
        mem.position = PositionState(**data["position"])
        mem.daily_log = [DailyMemory(**d) for d in data["daily_log"]]
        mem.emotion_trajectory = data["emotion_trajectory"]
        mem.trade_count = data["trade_count"]
        return mem
