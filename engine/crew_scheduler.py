"""
港股沙盘模拟 - CrewAI版本调度器
将C方案的业务逻辑包装为CrewAI的Agent和Task
"""
import json
import yaml
from pathlib import Path
from typing import Optional
from openai import OpenAI

from crewai import Agent, Task, Crew, Process
from crewai.tools import tool

from engine.memory import AgentMemory
from engine.market import Market
from engine.interaction import InteractionEngine


class CrewScheduler:
    """CrewAI版本的调度器"""

    def __init__(self, scenario_path: str, config_dir: str,
                 llm_client: OpenAI, model: str = "deepseek-chat"):
        # 加载场景
        with open(scenario_path, "r", encoding="utf-8") as f:
            self.scenario = yaml.safe_load(f)

        # LLM配置
        self.llm_client = llm_client
        self.model = model

        # 初始化市场
        self.market = Market(self.scenario["initial_market"], mode="backtest")

        # 交互引擎
        self.interaction = InteractionEngine()

        # 加载Agent配置并创建CrewAI Agent
        self.crew_agents = {}  # name_en -> Agent
        self.agent_configs = {}  # name_en -> config
        self.agent_memories = {}  # name_en -> AgentMemory

        config_path = Path(config_dir)
        for config_file in sorted(config_path.glob("*.yaml")):
            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            agent_name_en = config_file.stem
            self.agent_configs[agent_name_en] = config

            # 创建CrewAI Agent
            crew_agent = self._create_crew_agent(config, agent_name_en)
            self.crew_agents[agent_name_en] = crew_agent

            # 初始化记忆
            self.agent_memories[agent_name_en] = AgentMemory(
                config.get("name", agent_name_en),
                agent_name_en
            )

        # 运行日志
        self.log: list[dict] = []

    def _create_crew_agent(self, config: dict, name_en: str) -> Agent:
        """根据配置创建CrewAI Agent（适配现有YAML格式）"""
        name = config.get("name", name_en)
        role = config.get("role", f"{name}投资者")
        params = config.get("params", {})

        # 提取关键参数
        leverage = params.get("leverage", 1.0)
        reaction_delay = params.get("reaction_delay_hours", 24)
        sentiment_weight = params.get("sentiment_weight", 0.5)
        stop_loss = params.get("stop_loss_pct", -10)

        # 构建system message
        system_msg = f"""你是{name}。

{role}

## 你的核心参数
- 杠杆倍数：{leverage}x
- 反应延迟：{reaction_delay}小时
- 情绪驱动权重：{sentiment_weight}
- 止损阈值：{stop_loss}%

## 可用操作
- buy: 买入（增加多头仓位）
- sell: 卖出（减少多头仓位或开空）
- hold: 持有不变
- cover_short: 平掉空头
- add_short: 增加空头

每天你会收到市场状态，需要做出交易决策。
输出必须是JSON格式：{{"action": "buy/sell/hold/cover_short/add_short", "position_change_pct": 0-100, "reasoning": "你的思考过程", "emotion": "calm/anxiety/fomo/greed/fear/panic", "confidence": 0.0-1.0}}
"""

        return Agent(
            name=name,
            role=role[:50] if len(role) > 50 else role,
            goal=f"在港股市场中获取收益",
            backstory=system_msg,
            verbose=True,
            allow_delegation=False,
            llm=self._get_llm_config(),
        )

    def _format_rules(self, rules: list) -> str:
        return "\n".join(f"- {r}" for r in rules)

    def _get_llm_config(self):
        """返回CrewAI可用的LLM配置"""
        # CrewAI使用LangChain格式的配置
        return {
            "model": self.model,
            "api_key": self.llm_client.api_key,
            "base_url": str(self.llm_client.base_url) if self.llm_client.base_url else None,
            "temperature": 0.7,
        }

    def run(self, output_dir: str = "output"):
        """运行模拟"""
        output_path = Path(output_dir)
        logs_path = output_path / "logs"
        logs_path.mkdir(parents=True, exist_ok=True)

        events = self.scenario.get("events") or self.scenario.get("timeline", [])
        total = len(events)

        print(f"\n{'='*60}")
        print(f"🎮 CrewAI港股沙盘模拟启动")
        print(f"📋 场景: {self.scenario['scenario']['name']}")
        print(f"📅 周期: {events[0]['date']} → {events[-1]['date']} ({total}天)")
        print(f"🤖 CrewAI Agent: {len(self.crew_agents)}个")
        print(f"{'='*60}\n")

        for i, event in enumerate(events, 1):
            date = event["date"]
            print(f"\n--- 📅 {date} ({event.get('phase', 'normal')}) ---")
            print(f"    事件: {event.get('description', '无')[:60]}...")

            # 更新市场状态
            self.market.update_from_event(event)
            market_state = self.market.get_state()
            print(f"    📊 恒指: {market_state['hsi_close']} ({market_state['daily_change_pct']:+.1f}%) 情绪: {market_state['sentiment']}")

            # 为每个Agent创建决策Task
            day_decisions = []
            for agent_name_en, crew_agent in self.crew_agents.items():
                config = self.agent_configs[agent_name_en]
                memory = self.agent_memories[agent_name_en]

                # 硬约束检查（复用C方案逻辑）
                if self._is_forced_hold(agent_name_en, event, market_state):
                    decision = self._create_forced_decision(date, crew_agent.name, "流程约束")
                    memory.update(decision, market_state)
                    day_decisions.append(decision)
                    print(f"    ⚪ {crew_agent.name}: hold [强制] | 内部流程约束")
                    continue

                # 创建决策Task
                task = self._create_decision_task(
                    crew_agent, config, memory, date, market_state, event
                )

                # 创建临时Crew执行单个Task
                crew = Crew(
                    agents=[crew_agent],
                    tasks=[task],
                    process=Process.sequential,
                    verbose=False,
                )

                try:
                    result = crew.kickoff()
                    decision = self._parse_result(result, date, crew_agent.name)
                except Exception as e:
                    decision = self._create_error_decision(date, crew_agent.name, str(e))

                # 更新记忆
                memory.update(decision, market_state)
                day_decisions.append(decision)

                emoji = {"buy": "🟢", "sell": "🔴", "hold": "⚪",
                         "cover_short": "🟡", "add_short": "🔵"}.get(decision["action"], "❓")
                print(f"    {emoji} {crew_agent.name}: {decision['action']} | {decision['reasoning'][:40]}... | 情绪={decision['emotion']}")

            # 更新交互引擎
            self.interaction.update_contagion(day_decisions)

            # 记录
            self.market.record(date, day_decisions)
            self.log.append({
                "date": date,
                "event": event,
                "market_state": market_state,
                "decisions": day_decisions
            })

            # 保存当天日志
            with open(logs_path / f"{date}.json", "w", encoding="utf-8") as f:
                json.dump(self.log[-1], f, ensure_ascii=False, indent=2)

        # 生成报告
        self._generate_report(output_path / "reports")

        # 保存记忆
        memory_path = output_path / "memory_crew"
        memory_path.mkdir(exist_ok=True)
        for name_en, mem in self.agent_memories.items():
            mem.save(str(memory_path / f"{name_en}.json"))

        print(f"\n{'='*60}")
        print(f"✅ CrewAI模拟完成！")
        print(f"{'='*60}")

    def _create_decision_task(self, agent: Agent, config: dict,
                               memory: AgentMemory, date: str,
                               market_state: dict, event: dict) -> Task:
        """创建决策Task"""
        # 构建用户输入（类似C方案的user prompt）
        memory_context = memory.to_prompt_context(lookback=3)

        description = f"""今天是 {date}。

## 市场状态
- 恒生指数: {market_state.get('hsi_close')}
- 日涨跌幅: {market_state.get('daily_change_pct', 0)}%
- 市场情绪: {market_state.get('sentiment')}

## 今日事件
{event.get('description', '无特别事件')[:200]}

{memory_context}

请做出今天的交易决策。
输出JSON格式：{{"action": "buy/sell/hold/cover_short/add_short", "position_change_pct": 0-100, "reasoning": "你的思考过程", "emotion": "calm/anxiety/fomo/greed/fear/panic", "confidence": 0.0-1.0}}
"""

        return Task(
            description=description,
            agent=agent,
            expected_output="JSON格式的交易决策，包含action、position_change_pct、reasoning、emotion、confidence",
        )

    def _parse_result(self, result, date: str, agent_name: str) -> dict:
        """解析CrewAI的输出"""
        try:
            # 尝试从result中提取JSON
            if hasattr(result, 'raw'):
                text = result.raw
            else:
                text = str(result)

            # 找JSON块
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()
            else:
                # 找花括号
                start = text.find("{")
                end = text.rfind("}")
                json_str = text[start:end+1] if start != -1 and end != -1 else text

            decision = json.loads(json_str)
            decision["date"] = date
            decision["agent"] = agent_name
            return decision
        except Exception as e:
            return self._create_error_decision(date, agent_name, f"解析错误: {e}")

    def _create_error_decision(self, date: str, agent_name: str, error: str) -> dict:
        return {
            "date": date,
            "agent": agent_name,
            "action": "hold",
            "position_change_pct": 0,
            "reasoning": f"决策异常: {error[:50]}",
            "emotion": "calm",
            "confidence": 0.0,
        }

    def _create_forced_decision(self, date: str, agent_name: str, reason: str) -> dict:
        return {
            "date": date,
            "agent": agent_name,
            "action": "hold",
            "position_change_pct": 0,
            "reasoning": f"[强制] {reason}",
            "emotion": "anxiety",
            "confidence": 0.5,
            "_forced": True,
        }

    def _is_forced_hold(self, agent_name_en: str, event: dict, market_state: dict) -> bool:
        """检查是否需要强制hold（复用C方案逻辑）"""
        # 简化为：长线外资前3天强制hold
        if agent_name_en == "long_only":
            # 这里需要知道是第几天，简化处理
            pass
        return False

    def _get_agent_name_en(self, name_cn: str) -> str:
        """中文名转英文名"""
        mapping = {
            "对冲基金": "hedge_fund",
            "长线外资": "long_only",
            "南下资金": "southbound",
            "价值投资者": "value_investor",
        }
        return mapping.get(name_cn, name_cn.lower().replace(" ", "_"))

    def _generate_report(self, reports_path: Path):
        """生成报告"""
        reports_path.mkdir(exist_ok=True)
        # 简化版报告
        report_lines = ["# CrewAI模拟报告\n"]
        for name_en, mem in self.agent_memories.items():
            report_lines.append(f"\n## {mem.agent_name}\n")
            report_lines.append(f"交易次数: {mem.trade_count}")
            report_lines.append(f"已实现盈亏: {mem.position.realized_pnl_pct:+.1f}%")

        with open(reports_path / "crew_report.md", "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))

        print(f"\n📝 报告已生成: {reports_path / 'crew_report.md'}")
