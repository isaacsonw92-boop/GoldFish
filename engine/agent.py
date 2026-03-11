"""
港股沙盘模拟 - Agent基类
每个Agent = 一个LLM prompt + 参数配置 + 决策逻辑
"""
import json
import yaml
from pathlib import Path
from openai import OpenAI
from engine.memory import AgentMemory


class Agent:
    """沙盘Agent基类"""

    def __init__(self, config_path: str, llm_client: OpenAI, model: str = "deepseek-chat"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.name = self.config["name"]
        self.name_en = self.config["name_en"]
        self.role = self.config["role"]
        self.params = self.config["params"]
        self.psychology = self.config["psychology"]
        self.llm = llm_client
        self.model = model
        self.history: list[dict] = []  # 历史决策记录（兼容旧代码）
        self.memory = AgentMemory(self.name, self.name_en)  # 新记忆系统

    def _build_system_prompt(self) -> str:
        """构建Agent的系统prompt"""
        params_str = "\n".join(f"  - {k}: {v}" for k, v in self.params.items())
        psych_str = "\n".join(f"  - {k}: {v}" for k, v in self.psychology.items())

        return f"""你正在参与一个港股市场沙盘模拟。你必须完全代入以下角色做决策。

## 你的角色
{self.role.strip()}

## 你的参数
{params_str}

## 你的心理特征
{psych_str}

## 决策规则
1. 你必须基于你的角色、参数和心理特征做决策，不要跳出角色
2. 你能看到市场状态和部分其他参与者的行为（但信息不完全）
3. 你的决策必须用第一人称解释
4. 每次决策输出严格的JSON格式

## 输出格式（严格JSON）
{{
  "action": "buy" | "sell" | "hold" | "cover_short" | "add_short",
  "position_change_pct": 0-100的数字（本次操作涉及的仓位百分比变化）,
  "reasoning": "50字以内的决策理由（第一人称）",
  "emotion": "fear" | "greed" | "anxiety" | "calm" | "panic" | "fomo",
  "top_concern": "你当前最担心的一件事",
  "confidence": 0.0-1.0（对这个决策的信心）
}}

只输出JSON，不要任何其他文字。"""

    def _build_user_prompt(self, date: str, market_state: dict, event: dict,
                           other_agents_actions: dict) -> str:
        """构建每天的决策prompt"""
        # 从记忆系统获取上下文（仓位+历史+情绪+统计）
        memory_context = self.memory.to_prompt_context(lookback=5)

        # 其他Agent的可观察行为
        others_str = ""
        for agent_name, action_info in other_agents_actions.items():
            if action_info:
                others_str += f"\n  - {agent_name}: {action_info}"
            else:
                others_str += f"\n  - {agent_name}: 暂无明显动作"

        return f"""## 今天是 {date}

## 市场状态
- 恒生指数: {market_state.get('hsi_close', 'N/A')}
- 日涨跌幅: {market_state.get('daily_change_pct', 0)}%
- 成交额: {market_state.get('volume_hkd_billion', 'N/A')}亿港元
- 市场情绪: {market_state.get('sentiment', 'N/A')}

## 今日事件
{event.get('description', '无特别事件').strip()}
政策信号强度: {event.get('policy_signal_strength', 0)}（-1到1，1为最强利好，-1为最强利空）

## 你能观察到的其他参与者行为
{others_str}

{memory_context}

请做出今天的决策。"""

    def decide(self, date: str, market_state: dict, event: dict,
               other_agents_actions: dict, extra_context: str = "") -> dict:
        """调用LLM做出决策"""
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(date, market_state, event, other_agents_actions)
        if extra_context:
            user_prompt += f"\n\n## ⚠️ 重要提醒\n{extra_context}"

        try:
            response = self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=500,
                response_format={"type": "json_object"}
            )

            decision = json.loads(response.choices[0].message.content)
            decision["date"] = date
            decision["agent"] = self.name
            self.history.append(decision)
            self.memory.update(decision, market_state)
            return decision

        except Exception as e:
            # 出错时返回默认持有
            fallback = {
                "date": date,
                "agent": self.name,
                "action": "hold",
                "position_change_pct": 0,
                "reasoning": f"决策异常，默认持有: {str(e)[:50]}",
                "emotion": "calm",
                "top_concern": "系统异常",
                "confidence": 0.0
            }
            self.history.append(fallback)
            self.memory.update(fallback, market_state)
            return fallback

    def get_observable_action(self) -> str | None:
        """返回最近一次决策的可观察描述（供其他Agent参考）"""
        if not self.history:
            return None
        last = self.history[-1]
        action_map = {
            "buy": "买入",
            "sell": "卖出",
            "hold": "按兵不动",
            "cover_short": "平空头（回补）",
            "add_short": "加空仓"
        }
        action_cn = action_map.get(last["action"], last["action"])
        return f"{action_cn}，情绪={last['emotion']}，信心={last.get('confidence', 'N/A')}"
