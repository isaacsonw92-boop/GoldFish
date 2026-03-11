"""
港股沙盘模拟 - Agent交互影响计算
独立模块，负责计算Agent之间的信息传递和相互影响
迁移到CrewAI/AutoGen时，这个模块的逻辑直接映射为Agent间通信规则
"""
from typing import Optional


class InteractionEngine:
    """Agent交互引擎"""

    def __init__(self):
        # 市场层面的交互状态
        self._panic_contagion: float = 0.0   # 恐慌传染度 0-1
        self._fomo_contagion: float = 0.0    # FOMO传染度 0-1
        self._selling_pressure: float = 0.0  # 卖出压力（有多少Agent在卖）
        self._buying_pressure: float = 0.0   # 买入压力

    def compute_observable_actions(self, agents: list, current_agent) -> dict:
        """
        计算当前Agent能观察到的其他Agent行为
        包含信息延迟和遮蔽规则
        """
        others = {}
        for agent in agents:
            if agent.name_en == current_agent.name_en:
                continue

            observable = agent.get_observable_action()

            # 规则1：长线外资的行为有信息延迟
            # 前3天其他人看不到他在干嘛（大型机构操作保密性高）
            if agent.name_en == "LongOnly" and len(agent.history) < 3:
                observable = "暂无明显动作（信息延迟）"

            # 规则2：对冲基金的具体仓位不透明
            # 其他人只能看到方向，不能看到精确仓位
            if agent.name_en == "HedgeFund" and observable:
                # 只暴露方向性信息
                if "卖出" in observable or "加空" in observable:
                    observable = "偏空操作（具体仓位不详）"
                elif "买入" in observable or "平空" in observable:
                    observable = "偏多操作（具体仓位不详）"

            # 规则3：价值投资者几乎不产生可观察信号
            # 他们交易频率极低，市场感知不到他们
            if agent.name_en == "ValueInvestor":
                if not agent.history or agent.history[-1]["action"] == "hold":
                    observable = "无明显动作"

            others[agent.name] = observable

        return others

    def update_contagion(self, all_decisions: list[dict]):
        """
        根据当天所有Agent的决策更新传染指标
        下一天的Agent会感受到这些传染效应
        """
        sell_count = 0
        buy_count = 0
        panic_count = 0
        fomo_count = 0

        for d in all_decisions:
            action = d.get("action", "hold")
            emotion = d.get("emotion", "calm")

            if action in ("sell", "add_short"):
                sell_count += 1
            elif action in ("buy", "cover_short"):
                buy_count += 1

            if emotion in ("panic", "fear"):
                panic_count += 1
            elif emotion in ("fomo", "greed"):
                fomo_count += 1

        total = max(len(all_decisions), 1)

        # 传染度 = 同向行为占比（有衰减）
        self._selling_pressure = sell_count / total
        self._buying_pressure = buy_count / total
        self._panic_contagion = self._panic_contagion * 0.5 + (panic_count / total) * 0.5
        self._fomo_contagion = self._fomo_contagion * 0.5 + (fomo_count / total) * 0.5

    def get_contagion_context(self, agent_name_en: str) -> Optional[str]:
        """
        根据传染指标生成额外context注入Agent prompt
        不同类型的Agent对传染效应的敏感度不同
        """
        # 敏感度配置
        sensitivity = {
            "Southbound": {"panic": 0.9, "fomo": 0.8},   # 散户最容易被传染
            "HedgeFund":  {"panic": 0.3, "fomo": 0.4},   # 对冲基金相对理性
            "LongOnly":   {"panic": 0.5, "fomo": 0.3},   # 长线外资偏理性但也会跟风
            "ValueInvestor": {"panic": 0.1, "fomo": 0.05}, # 价值投资者几乎免疫
        }

        sens = sensitivity.get(agent_name_en, {"panic": 0.5, "fomo": 0.5})

        parts = []

        # 恐慌传染
        effective_panic = self._panic_contagion * sens["panic"]
        if effective_panic >= 0.5:
            parts.append(
                f"你能感受到市场上弥漫着强烈的恐慌情绪。"
                f"昨天{self._selling_pressure*100:.0f}%的参与者在卖出。"
                f"这种恐慌正在传染——即使你理性上觉得不该卖，"
                f"身体的求生本能在告诉你：别人都在跑，你也该跑。"
            )
        elif effective_panic >= 0.3:
            parts.append(
                f"市场情绪偏紧张，部分参与者在减仓。"
                f"你注意到卖出力量在增强，这让你有些不安。"
            )

        # FOMO传染
        effective_fomo = self._fomo_contagion * sens["fomo"]
        if effective_fomo >= 0.5:
            parts.append(
                f"你能感受到市场上的FOMO情绪。"
                f"昨天{self._buying_pressure*100:.0f}%的参与者在买入。"
                f"你的同行在赚钱，你还没上车。"
                f"这种错过的感觉比亏钱还难受。"
            )
        elif effective_fomo >= 0.3:
            parts.append(
                f"市场买入情绪升温，一些参与者在积极加仓。"
                f"你开始担心如果不跟上，可能错过这波行情。"
            )

        if parts:
            return "\n".join(parts)
        return None

    def get_peer_pressure_context(self, agent_name_en: str,
                                   all_agents: list) -> Optional[str]:
        """
        计算同类压力（peer pressure）
        例如：长线外资看到其他Long-only在加配会有压力
        """
        if agent_name_en == "LongOnly":
            # 检查南下资金和对冲基金的行为——如果都在买，长线外资压力更大
            buying_peers = 0
            for agent in all_agents:
                if agent.name_en == "LongOnly":
                    continue
                if agent.history and agent.history[-1].get("action") in ("buy", "cover_short"):
                    buying_peers += 1

            if buying_peers >= 2:
                return (
                    "你注意到：南下资金和对冲基金都已经在加仓中国。"
                    "你的全球同行基金也开始行动。"
                    "如果你继续观望，季末的排名会非常难看。"
                    "这直接关系到你的年终奖和管理费提成。"
                )
            elif buying_peers >= 1:
                return (
                    "至少有一类市场参与者已经开始加配。"
                    "你的同行可能也在行动，但你还没有确切信息。"
                )

        elif agent_name_en == "Southbound":
            # 散户看到"别人在卖"会恐慌，看到"别人在买"会FOMO
            selling_others = 0
            for agent in all_agents:
                if agent.name_en == "Southbound":
                    continue
                if agent.history and agent.history[-1].get("action") in ("sell", "add_short"):
                    selling_others += 1

            if selling_others >= 2:
                return (
                    "你发现外资和机构都在卖出。"
                    "微信群里有人说'聪明钱都在跑'。"
                    "你开始怀疑：是不是他们知道什么你不知道的？"
                )

        return None

    def get_market_microstructure_context(self, market_state: dict) -> Optional[str]:
        """
        市场微观结构信息（所有Agent都能感受到）
        基于卖出/买入压力比计算
        """
        if self._selling_pressure > 0.6:
            return (
                "市场微观结构恶化：卖盘远大于买盘，"
                "流动性在收缩，买卖价差在扩大。"
                "这种环境下大单卖出会造成更大的价格冲击。"
            )
        elif self._buying_pressure > 0.6:
            return (
                "市场微观结构转好：买盘积极，"
                "成交量放大，流动性充裕。"
                "这种环境下适合分批建仓。"
            )
        return None

    def compute_extra_context(self, agent_name_en: str,
                               all_agents: list,
                               market_state: dict) -> str:
        """
        汇总所有交互影响，生成最终的extra_context
        供scheduler注入到Agent决策中
        """
        parts = []

        # 1. 传染效应
        contagion = self.get_contagion_context(agent_name_en)
        if contagion:
            parts.append(contagion)

        # 2. 同类压力
        peer = self.get_peer_pressure_context(agent_name_en, all_agents)
        if peer:
            parts.append(peer)

        # 3. 市场微观结构
        micro = self.get_market_microstructure_context(market_state)
        if micro:
            parts.append(micro)

        return "\n\n".join(parts)
