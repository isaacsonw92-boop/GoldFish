"""
港股沙盘模拟 - 市场状态管理
支持两种模式：
  1. 回溯模式（backtest）：从YAML读预设真实数据
  2. 推演模式（forecast）：从Agent决策合成价格变化
"""
import random
import math


# Agent资金权重 — 反映对恒指定价的真实影响力
AGENT_WEIGHT = {
    "HedgeFund":     0.25,  # 对冲基金：高杠杆，短期影响大
    "LongOnly":      0.40,  # 长线外资：最大的定价权
    "Southbound":    0.25,  # 南下资金：边际定价者
    "ValueInvestor": 0.10,  # 价值投资者：交易频率低，影响小
}

# 行为→方向分数
ACTION_SCORE = {
    "buy":         +2.0,
    "cover_short": +1.0,
    "hold":         0.0,
    "sell":        -1.0,
    "add_short":   -2.0,
}

# 情绪→波动率放大器
EMOTION_AMPLIFIER = {
    "calm":    1.0,
    "anxiety": 1.2,
    "fomo":    1.4,
    "greed":   1.3,
    "fear":    1.5,
    "panic":   1.8,
}


class Market:
    """管理市场状态，汇总Agent决策后更新"""

    def __init__(self, initial_state: dict, mode: str = "backtest"):
        """
        mode: "backtest" = 从YAML读真实数据, "forecast" = 从Agent决策合成
        """
        self.mode = mode
        self.state = {
            "hsi_close": initial_state.get("hsi_close", 18200),
            "daily_change_pct": 0.0,
            "volume_hkd_billion": initial_state.get("daily_volume_hkd_billion", 80),
            "sentiment": initial_state.get("sentiment", "neutral"),
            "foreign_positioning": initial_state.get("foreign_positioning", "underweight"),
            "hedge_fund_short_interest": initial_state.get("hedge_fund_short_interest", "high"),
            "southbound_flow_trend": initial_state.get("southbound_flow_trend", "steady"),
        }
        self.history: list[dict] = []

        # 推演模式参数
        self._base_volatility: float = float(initial_state.get("base_volatility_pct", 1.2))
        self._prev_hsi: float = self.state["hsi_close"]

    def update_from_event(self, event: dict):
        """用事件数据更新状态"""
        if self.mode == "backtest":
            self._update_backtest(event)
        else:
            # 推演模式：只读事件的定性信息，不读market_data
            self._update_forecast_event(event)

    def _update_backtest(self, event: dict):
        """回溯模式：从YAML读预设真实数据"""
        market_data = event.get("market_data", {})
        if market_data:
            self.state["hsi_close"] = market_data.get("hsi_close", self.state["hsi_close"])
            self.state["daily_change_pct"] = market_data.get("daily_change_pct", 0.0)
            self.state["volume_hkd_billion"] = market_data.get("volume_hkd_billion",
                                                               self.state["volume_hkd_billion"])
        self._update_sentiment()
        self._update_external(event)

    def _update_forecast_event(self, event: dict):
        """推演模式：读事件的政策信号和地缘风险，但不读价格"""
        # 事件本身的直接冲击（如黑天鹅的初始跳空）
        event_shock = event.get("event_shock_pct", 0.0)
        if event_shock != 0:
            self._prev_hsi = self.state["hsi_close"]
            self.state["hsi_close"] = self._prev_hsi * (1 + event_shock / 100)
            self.state["daily_change_pct"] = event_shock

        self._update_external(event)

    def update_from_decisions(self, decisions: list[dict], event: dict = None):
        """
        推演模式核心：从Agent决策合成恒指变化
        公式: change% = Σ(action_score × weight × confidence) × base_vol × emotion_amp + noise
        """
        if self.mode == "backtest":
            return  # 回溯模式不合成价格

        # 1. 计算加权行为分数
        weighted_score = 0.0
        avg_emotion_amp = 0.0
        total_weight = 0.0

        for d in decisions:
            agent_en = self._agent_name_to_en(d.get("agent", ""))
            weight = AGENT_WEIGHT.get(agent_en, 0.1)
            action = d.get("action", "hold")
            confidence = d.get("confidence", 0.5)
            emotion = d.get("emotion", "calm")

            score = ACTION_SCORE.get(action, 0.0)
            amp = EMOTION_AMPLIFIER.get(emotion, 1.0)

            weighted_score += score * weight * confidence
            avg_emotion_amp += amp * weight
            total_weight += weight

        if total_weight > 0:
            avg_emotion_amp /= total_weight

        # 2. 事件冲击加成（如果有的话）
        event_bias = 0.0
        effective_vol = self._base_volatility
        if event:
            policy = event.get("policy_signal_strength", 0)
            geo_risk = event.get("geopolitical_risk", 0)
            event_bias = policy * 0.5 - geo_risk * 0.3
            # 极端事件动态扩大波动率
            shock_intensity = max(abs(policy), geo_risk)
            if shock_intensity >= 0.9:
                effective_vol = self._base_volatility * 3.5  # 重大事件日3.5倍波动
            elif shock_intensity >= 0.7:
                effective_vol = self._base_volatility * 2.0
            elif shock_intensity >= 0.4:
                effective_vol = self._base_volatility * 1.5

        # 3. 合成日变化
        raw_change = (weighted_score + event_bias) * effective_vol * avg_emotion_amp

        # 4. 加噪声（市场不是完全可预测的）
        noise = random.gauss(0, effective_vol * 0.25)
        daily_change_pct = raw_change + noise

        # 5. 限幅：单日最大±10%
        daily_change_pct = max(-10.0, min(10.0, daily_change_pct))

        # 6. 更新状态
        self._prev_hsi = self.state["hsi_close"]
        self.state["hsi_close"] = round(self._prev_hsi * (1 + daily_change_pct / 100), 0)
        self.state["daily_change_pct"] = round(daily_change_pct, 2)

        # 7. 成交量（情绪越高，成交越大）
        base_vol = 100  # 正常日成交100亿
        self.state["volume_hkd_billion"] = round(base_vol * avg_emotion_amp * (1 + abs(daily_change_pct) / 3), 0)

        self._update_sentiment()

    def _agent_name_to_en(self, name_cn: str) -> str:
        """中文名→英文名映射"""
        mapping = {
            "对冲基金": "HedgeFund",
            "长线外资": "LongOnly",
            "南下资金": "Southbound",
            "价值投资者": "ValueInvestor",
        }
        return mapping.get(name_cn, name_cn)

    def _update_sentiment(self):
        """根据涨跌幅更新情绪"""
        change = self.state["daily_change_pct"]
        if change > 3:
            self.state["sentiment"] = "euphoric"
        elif change > 1:
            self.state["sentiment"] = "bullish"
        elif change > -1:
            self.state["sentiment"] = "neutral"
        elif change > -3:
            self.state["sentiment"] = "bearish"
        else:
            self.state["sentiment"] = "panic"

    def _update_external(self, event: dict):
        """更新外部反应"""
        external = event.get("external_reactions", [])
        if external:
            self.state["external_reactions"] = external
        else:
            self.state.pop("external_reactions", None)

    def record(self, date: str, decisions: list[dict]):
        """记录当天状态和所有决策"""
        record = {
            "date": date,
            "market_state": dict(self.state),
            "decisions": decisions
        }
        self.history.append(record)

    def get_state(self) -> dict:
        return dict(self.state)
