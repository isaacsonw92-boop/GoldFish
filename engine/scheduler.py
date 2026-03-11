"""
港股沙盘模拟 - 调度器
按天推进模拟，协调Agent决策和市场状态更新
"""
import json
import yaml
from pathlib import Path
from datetime import datetime

from engine.agent import Agent
from engine.market import Market
from engine.interaction import InteractionEngine


class Scheduler:
    """沙盘调度器"""

    def __init__(self, scenario_path: str, config_dir: str,
                 llm_client, model: str = "deepseek-chat", mode: str = "backtest"):
        # 加载场景
        with open(scenario_path, "r", encoding="utf-8") as f:
            self.scenario = yaml.safe_load(f)

        # 运行模式
        self.mode = mode  # "backtest" or "forecast"

        # 初始化市场
        self.market = Market(self.scenario["initial_market"], mode=mode)

        # 初始化四类Agent
        self.agents: list[Agent] = []
        config_path = Path(config_dir)
        for cfg_file in ["hedge_fund.yaml", "long_only.yaml",
                         "southbound.yaml", "value_investor.yaml"]:
            agent = Agent(
                config_path=str(config_path / cfg_file),
                llm_client=llm_client,
                model=model
            )
            self.agents.append(agent)

        # 事件索引（兼容 events / timeline 两种key）
        self.events_by_date = {}
        events_list = self.scenario.get("events") or self.scenario.get("timeline", [])
        for event in events_list:
            self.events_by_date[event["date"]] = event

        # 运行日志
        self.log: list[dict] = []

        # 交互引擎
        self.interaction = InteractionEngine()

        # 长线外资反应延迟追踪
        self._catalyst_date: str | None = None  # 第一个强催化剂的日期
        self._catalyst_type: str | None = None  # "policy" 或 "geopolitical"
        self._trading_days_since_catalyst: int = 0  # 催化剂后经过的交易日数

        # 对冲基金仓位追踪（从场景初始状态推断）
        short_interest = self.scenario["initial_market"].get("hedge_fund_short_interest", "moderate")
        self._hedge_fund_short_pct: float = {
            "historically_high": 25.0, "high": 20.0, "moderate": 10.0, "low": 5.0
        }.get(short_interest, 10.0)

        # 市场起始价（用于计算累计跌幅）
        self._initial_hsi: float = float(self.scenario["initial_market"].get("hsi_close", 20000))

    def _get_observable_actions(self, current_agent: Agent) -> dict:
        """获取其他Agent的可观察行为（委托给交互引擎）"""
        return self.interaction.compute_observable_actions(self.agents, current_agent)

    def run(self, output_dir: str = "output"):
        """运行完整模拟"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        logs_path = output_path / "logs"
        logs_path.mkdir(exist_ok=True)

        events = self.scenario.get("events") or self.scenario.get("timeline", [])
        total = len(events)

        print(f"\n{'='*60}")
        print(f"🎮 港股沙盘模拟启动")
        print(f"📋 场景: {self.scenario['scenario']['name']}")
        print(f"📅 周期: {events[0]['date']} → {events[-1]['date']} ({total}天)")
        print(f"🤖 Agent: {', '.join(a.name for a in self.agents)}")
        print(f"{'='*60}\n")

        for i, event in enumerate(events):
            date = event["date"]
            event_type = event.get("type", "normal")

            print(f"\n--- 📅 {date} ({event_type}) ---")
            print(f"    事件: {event['description'][:60]}...")

            # 跳过假期
            if event_type == "holiday":
                print(f"    🏖️ 休市")
                continue

            # 更新市场状态
            self.market.update_from_event(event)
            market_state = self.market.get_state()
            print(f"    📊 恒指: {market_state['hsi_close']} ({market_state['daily_change_pct']:+.1f}%) "
                  f"情绪: {market_state['sentiment']}")

            # 追踪催化剂日期（政策信号或地缘冲击）
            policy_strength = event.get("policy_signal_strength", 0)
            geo_risk = event.get("geopolitical_risk", 0)
            if self._catalyst_date is None:
                if policy_strength >= 0.8:
                    self._catalyst_date = date
                    self._catalyst_type = "policy"
                    self._trading_days_since_catalyst = 0
                elif geo_risk >= 0.9:
                    self._catalyst_date = date
                    self._catalyst_type = "geopolitical"
                    self._trading_days_since_catalyst = 0
            elif self._catalyst_date is not None:
                self._trading_days_since_catalyst += 1

            # 长线外资延迟天数：政策冲击3天，地缘冲击1天（risk-off是标准流程）
            longonly_delay = 3 if self._catalyst_type == "policy" else 1

            # 每个Agent做决策
            day_decisions = []
            for agent in self.agents:
                # 硬约束：长线外资在催化剂后前3个交易日强制hold
                if (agent.name_en == "LongOnly"
                        and self._catalyst_date is not None
                        and self._trading_days_since_catalyst < longonly_delay):
                    decision = {
                        "date": date,
                        "agent": agent.name,
                        "action": "hold",
                        "position_change_pct": 0,
                        "reasoning": f"内部评估流程进行中（催化剂后第{self._trading_days_since_catalyst+1}天/需3-7天），暂无法操作",
                        "emotion": "anxiety",
                        "top_concern": "同行可能在加仓但我的流程还没走完",
                        "confidence": 0.5,
                        "_forced": True
                    }
                    agent.history.append(decision)
                    agent.memory.update(decision, market_state)
                    day_decisions.append(decision)
                else:
                    others = self._get_observable_actions(agent)
                    extra_context = ""

                    # 对冲基金特殊context：追踪空头仓位
                    if agent.name_en == "HedgeFund":
                        if self._hedge_fund_short_pct <= 2.0:
                            extra_context = (
                                f"你的空头仓位已经基本清完（剩余约{self._hedge_fund_short_pct:.0f}%）。\n"
                                f"你现在是接近空仓状态。你需要决定：\n"
                                f"- 建立新的多头仓位（如果你认为上涨趋势会持续）\n"
                                f"- 重新建立空头仓位（如果你认为反弹结束了）\n"
                                f"- 保持空仓观望\n"
                                f"注意：你不能再'平空头'了，因为已经没有空头可平。"
                            )
                        else:
                            extra_context = (
                                f"你当前剩余空头仓位约{self._hedge_fund_short_pct:.0f}%。"
                            )

                    # 长线外资特殊context：根据市场环境和催化剂类型切换模式
                    if (agent.name_en == "LongOnly"
                            and self._catalyst_date is not None
                            and self._trading_days_since_catalyst >= longonly_delay):
                        days_since = self._trading_days_since_catalyst
                        daily_change = market_state.get("daily_change_pct", 0)

                        if self._catalyst_type == "geopolitical":
                            # 地缘冲击场景：risk-off模式
                            if daily_change <= -2.5:
                                extra_context = (
                                    f"地缘危机持续（催化剂后第{days_since+1}天）。今日市场暴跌{daily_change:.1f}%。\n"
                                    f"作为全球资产管理公司，你正在执行标准的risk-off流程：\n"
                                    f"- 减配新兴市场（不只是中国，是整个EM）\n"
                                    f"- 增配美元现金、美国国债、黄金等避险资产\n"
                                    f"- 这是机构面对地缘不确定性的标准操作，不需要委员会特别批准\n"
                                    f"你的首要任务是保护组合，减少风险敞口。卖出是合理的。"
                                )
                            elif daily_change >= 0:
                                extra_context = (
                                    f"地缘危机中出现短暂喘息（催化剂后第{days_since+1}天），今日市场微涨{daily_change:.1f}%。\n"
                                    f"但霍尔木兹海峡仍处于封锁状态，不确定性未消除。\n"
                                    f"大多数Long-only基金在这种情况下选择观望，不会在反弹中加仓。\n"
                                    f"你可以维持现有仓位，但不应新增买入——等局势明朗再说。"
                                )
                            else:
                                extra_context = (
                                    f"地缘危机持续（催化剂后第{days_since+1}天），今日市场跌{daily_change:.1f}%。\n"
                                    f"你正在执行risk-off减配。跌幅温和时可以放慢减仓节奏，但方向不变。"
                                )
                        else:
                            # 政策冲击场景
                            if daily_change <= -5.0:
                                # 暴跌日：风控模式，暂停建仓
                                extra_context = (
                                    f"你的内部流程已完成（催化剂后第{days_since+1}天），但今天市场暴跌{daily_change:.1f}%。\n"
                                    f"在这种极端波动下，你的风控委员会要求暂停所有新建仓操作，等待市场企稳后重新评估。\n"
                                    f"这是标准操作流程——大型机构在单日暴跌超过5%时不会逆势加仓，而是先保护现有仓位。\n"
                                    f"你可以维持现有仓位不动，但不应在今天新增买入。"
                                )
                            elif daily_change <= -2.0:
                                # 明显回调：谨慎模式，减速建仓
                                extra_context = (
                                    f"你的内部流程已完成（催化剂后第{days_since+1}天）。\n"
                                    f"关键事实：你目前中国配置仅2%，基准5%，低配3个百分点。同行已在加配。\n"
                                    f"但今天市场下跌{daily_change:.1f}%，情绪转弱。你需要权衡：\n"
                                    f"- 继续加配有跑输基准的风险如果不加\n"
                                    f"- 但在下跌趋势中加仓可能面临短期亏损，需要向委员会解释\n"
                                    f"大多数同行在这种情况下会放慢建仓节奏或暂停观望1-2天。"
                                )
                            else:
                                # 正常/上涨日：建仓模式
                                extra_context = (
                                    f"你的全球资产配置委员会内部评估流程已经完成（催化剂后第{days_since+1}天）。你现在可以自由操作了。\n"
                                    f"关键事实：你目前中国配置仅2%，基准是5%，低配3个百分点。"
                                    f"你的同行（其他Long-only基金）在过去几天已经开始加配中国。"
                                    f"大摩、高盛已上调中国股票评级。\n"
                                    f"如果你继续不动，你将面临严重的跑输基准风险。这直接关系到你的年度考核和排名。\n"
                                    f"你不需要一次性加满，可以分批建仓（每天加配总回补量的20%）。"
                                )

                    # 南下资金特殊context：地缘危机时降低政策信仰
                    if agent.name_en == "Southbound":
                        geo_risk = event.get("geopolitical_risk", 0)
                        daily_change = market_state.get("daily_change_pct", 0)
                        if geo_risk >= 0.9 and daily_change <= -2.5:
                            extra_context = (
                                f"⚠️ 当前地缘危机严重程度：{geo_risk}（极高）。今日市场暴跌{daily_change:.1f}%。\n"
                                f"这不是普通的政策调控式下跌——这是战争级别的黑天鹅事件。\n"
                                f"你平时相信'国家队会救市'，但这次不同：\n"
                                f"- 霍尔木兹海峡封锁不是中国政策能解决的问题\n"
                                f"- 油价暴涨会直接冲击中国经济（进口通胀+制造业成本上升）\n"
                                f"- 你周围的散户朋友已经开始恐慌卖出\n"
                                f"- 微信群和社交媒体充斥着'世界大战'的讨论\n"
                                f"在这种极端恐惧面前，你的政策信仰正在动摇。卖出是正常的求生本能。"
                            )
                        elif geo_risk >= 0.85 and daily_change <= -1.0:
                            extra_context = (
                                f"地缘风险持续（{geo_risk}），市场跌{daily_change:.1f}%。\n"
                                f"你的政策信仰在动摇——国家队能救经济，但救不了中东战争。\n"
                                f"你开始犹豫：是该继续扛着，还是先减仓避险？\n"
                                f"周围越来越多的人在讨论卖出。"
                            )

                    # 价值投资者特殊context：累计跌幅未达安全边际时不出手
                    if agent.name_en == "ValueInvestor":
                        current_hsi = market_state.get("hsi_close", self._initial_hsi)
                        cumulative_drop_pct = (current_hsi - self._initial_hsi) / self._initial_hsi * 100
                        if cumulative_drop_pct > -10.0:
                            extra_context = (
                                f"恒指从{self._initial_hsi:.0f}跌到{current_hsi:.0f}，累计跌幅仅{cumulative_drop_pct:.1f}%。\n"
                                f"你的安全边际要求是30-50%的折扣。当前跌幅远未达到你的买入标准。\n"
                                f"提醒自己：不要因为'觉得便宜'就买。真正的安全边际需要更大的跌幅。\n"
                                f"巴菲特在2008年金融危机时也是等到市场跌了40%以上才大规模出手。\n"
                                f"现在应该保持现金，耐心等待。"
                            )
                        elif cumulative_drop_pct > -15.0:
                            extra_context = (
                                f"恒指从{self._initial_hsi:.0f}跌到{current_hsi:.0f}，累计跌幅{cumulative_drop_pct:.1f}%。\n"
                                f"开始接近你的关注区间，但安全边际仍不足。\n"
                                f"你可以开始评估个别优质公司的估值，但不急于大规模建仓。\n"
                                f"试探性小仓位（5-10%现金）买入最有信心的标的是合理的。"
                            )
                        else:
                            extra_context = (
                                f"恒指从{self._initial_hsi:.0f}跌到{current_hsi:.0f}，累计跌幅{cumulative_drop_pct:.1f}%。\n"
                                f"安全边际开始出现。'别人恐惧时我贪婪'的时刻可能到了。\n"
                                f"你可以开始分批买入优质公司。但仍保持至少20%现金应对进一步下跌。"
                            )

                    # 合并交互引擎产生的context
                    interaction_ctx = self.interaction.compute_extra_context(
                        agent.name_en, self.agents, market_state
                    )
                    if interaction_ctx:
                        extra_context = (extra_context + "\n\n" + interaction_ctx) if extra_context else interaction_ctx

                    decision = agent.decide(date, market_state, event, others, extra_context=extra_context)
                    day_decisions.append(decision)

                    # 更新对冲基金空头仓位追踪
                    if agent.name_en == "HedgeFund":
                        change = decision.get("position_change_pct", 0)
                        if decision["action"] == "cover_short":
                            self._hedge_fund_short_pct = max(0, self._hedge_fund_short_pct - change)
                        elif decision["action"] == "add_short":
                            self._hedge_fund_short_pct += change

                emoji = {"buy": "🟢", "sell": "🔴", "hold": "⚪",
                         "cover_short": "🟡", "add_short": "🔵"}.get(decision["action"], "❓")
                forced_tag = " [强制]" if decision.get("_forced") else ""
                print(f"    {emoji} {agent.name}: {decision['action']}{forced_tag} "
                      f"| {decision['reasoning'][:40]}... "
                      f"| 情绪={decision['emotion']} 信心={decision.get('confidence', 'N/A')}")

            # 更新交互引擎的传染指标（影响下一天）
            self.interaction.update_contagion(day_decisions)

            # 推演模式：从Agent决策合成市场价格
            if self.mode == "forecast":
                self.market.update_from_decisions(day_decisions, event)
                updated_state = self.market.get_state()
                print(f"    📈 合成恒指: {updated_state['hsi_close']:.0f} ({updated_state['daily_change_pct']:+.2f}%)")

            # 记录
            self.market.record(date, day_decisions)

            # 保存当天日志
            day_log = {
                "date": date,
                "event": event,
                "market_state": market_state,
                "decisions": day_decisions
            }
            self.log.append(day_log)

            with open(logs_path / f"{date}.json", "w", encoding="utf-8") as f:
                json.dump(day_log, f, ensure_ascii=False, indent=2)

        # 生成总结报告
        self._generate_report(output_path / "reports")

        # 持久化Agent记忆
        memory_path = output_path / "memory"
        memory_path.mkdir(exist_ok=True)
        for agent in self.agents:
            agent.memory.save(str(memory_path / f"{agent.name_en}.json"))

        print(f"\n{'='*60}")
        print(f"✅ 模拟完成！日志保存在 {logs_path}")
        print(f"💾 Agent记忆保存在 {memory_path}")
        print(f"{'='*60}")

    def _generate_report(self, reports_path: Path):
        """生成模拟总结报告（含自动分析）"""
        reports_path.mkdir(exist_ok=True)

        report_lines = []
        report_lines.append(f"# 港股沙盘模拟报告\n")
        report_lines.append(f"**场景:** {self.scenario['scenario']['name']}  ")
        report_lines.append(f"**模式:** {self.mode}  ")
        report_lines.append(f"**Agent总数:** {len(self.agents)}  \n")
        report_lines.append(f"---\n")

        # ── 1. Agent盈亏统计 ──
        report_lines.append("## 一、Agent盈亏统计\n")
        report_lines.append("| Agent | 交易次数 | 持仓方向 | 持仓大小 | 浮盈亏 | 已实现盈亏 |")
        report_lines.append("|-------|---------|---------|---------|--------|-----------|")
        for agent in self.agents:
            mem = agent.memory
            pos = mem.position
            report_lines.append(
                f"| {agent.name} | {mem.trade_count} | {pos.direction} | "
                f"{pos.size_pct:.0f}% | {pos.unrealized_pnl_pct:+.1f}% | {pos.realized_pnl_pct:+.1f}% |"
            )

        # ── 2. 行为时间线 ──
        report_lines.append("\n## 二、Agent行为时间线\n")
        for agent in self.agents:
            report_lines.append(f"\n### {agent.name}\n")
            report_lines.append("| 日期 | 操作 | 情绪 | 信心 | 仓位后 | 浮盈亏 | 理由 |")
            report_lines.append("|------|------|------|------|--------|--------|------|")
            for h in agent.memory.daily_log:
                pos = h.position_after
                report_lines.append(
                    f"| {h.date} | {h.action} | {h.emotion} | {h.confidence:.1f} | "
                    f"{pos.get('direction','?')} {pos.get('size_pct',0):.0f}% | "
                    f"{pos.get('unrealized_pnl_pct',0):+.1f}% | {h.reasoning[:30]} |"
                )

        # ── 3. 行为一致性分析 ──
        report_lines.append("\n## 三、自动分析\n")

        # 统计每天的多空力量
        action_score = {"buy": 2, "cover_short": 1, "hold": 0, "sell": -1, "add_short": -2}
        net_forces = []
        for day_log in self.log:
            net = sum(action_score.get(d["action"], 0) for d in day_log["decisions"])
            net_forces.append((day_log["date"], net))

        strongest_buy = max(net_forces, key=lambda x: x[1])
        strongest_sell = min(net_forces, key=lambda x: x[1])
        report_lines.append(f"- **最强买入日**: {strongest_buy[0]}（净力量={strongest_buy[1]}）")
        report_lines.append(f"- **最强卖出日**: {strongest_sell[0]}（净力量={strongest_sell[1]}）")

        # 情绪统计
        all_emotions = []
        for agent in self.agents:
            all_emotions.extend(agent.memory.emotion_trajectory)
        from collections import Counter
        emo_count = Counter(all_emotions)
        dominant_emo = emo_count.most_common(1)[0]
        report_lines.append(f"- **主导情绪**: {dominant_emo[0]}（{dominant_emo[1]}次，占{dominant_emo[1]/len(all_emotions)*100:.0f}%）")

        # 行为分化度（每天四Agent一致性）
        divergence_days = []
        for day_log in self.log:
            actions = [d["action"] for d in day_log["decisions"]]
            unique = len(set(actions))
            if unique >= 3:
                divergence_days.append(day_log["date"])
        if divergence_days:
            report_lines.append(f"- **高分化日（≥3种操作）**: {', '.join(divergence_days)}")

        # forecast模式：对比标准答案
        expected = self.scenario.get("expected_behavior", {})
        if expected:
            report_lines.append(f"\n## 四、标准答案对比\n")
            report_lines.append(f"- **预期反应顺序**: {expected.get('reaction_order', 'N/A')}")
            report_lines.append(f"- **预期退出顺序**: {expected.get('exit_order', 'N/A')}")
            report_lines.append(f"- **预期恒指轨迹**: {expected.get('hsi_trajectory', 'N/A')}")

        report_text = "\n".join(report_lines)
        report_file = reports_path / "simulation_report.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report_text)

        print(f"\n📝 报告已生成: {report_file}")
