#!/usr/bin/env python3
"""
CrewAI完整版 - 关键节点触发对话
复用C方案所有业务逻辑，只在关键节点插入Agent对话
"""
import os
import json
import yaml
from pathlib import Path
from openai import OpenAI
from engine.memory import AgentMemory
from engine.market import Market

# 配置
api_key = os.environ.get("LLM_API_KEY") or "sk-bf316c318b77410a91dc8f4bceca6b93"
base_url = os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com"
client = OpenAI(api_key=api_key, base_url=base_url)

# Agent配置缓存
AGENT_CONFIGS = {}

def load_configs(config_dir="config"):
    """加载Agent配置"""
    for f in Path(config_dir).glob("*.yaml"):
        with open(f) as fp:
            AGENT_CONFIGS[f.stem] = yaml.safe_load(fp)

def should_trigger_dialogue(event: dict, market_state: dict, prev_states: list) -> tuple:
    """检查是否触发对话"""
    change = abs(market_state.get("daily_change_pct", 0))
    policy = abs(event.get("policy_signal_strength", 0))

    # 条件1：单日涨跌幅>3%
    if change > 3:
        return True, f"单日波动{change:.1f}%触发"

    # 条件2：政策信号强度>0.7
    if policy > 0.7:
        return True, f"政策信号{policy}触发"

    # 条件3：连续3天同向运动
    if len(prev_states) >= 2:
        directions = [s.get("daily_change_pct", 0) > 0 for s in prev_states[-2:]]
        current_up = market_state.get("daily_change_pct", 0) > 0
        if all(d == current_up for d in directions) and current_up != 0:
            return True, "连续3天同向运动触发"

    return False, ""

def run_dialogue(agent_names: list, topic: str, market_summary: str) -> dict:
    """
    运行Agent群聊
    简化为：每个Agent看到话题，基于自己的立场发言
    """
    print(f"\n{'='*60}")
    print(f"🗣️ Agent群聊触发：{topic}")
    print(f"{'='*60}")

    responses = {}

    for name in agent_names:
        config = AGENT_CONFIGS.get(name, {})
        role = config.get("role", f"你是{name}")[:500]

        prompt = f"""{role}

当前市场情况：
{market_summary}

群聊话题：{topic}

其他Agent正在讨论这个话题。请发表你的看法，1-2句话。
要体现你的身份特征（对冲基金关注风险/南下资金关注政策/长线外资关注基准/价值投资者关注安全边际）。
"""
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=150
        )
        reply = response.choices[0].message.content.strip()
        responses[name] = reply
        print(f"\n{'🟡' if 'hedge' in name else '🟢' if 'south' in name else '⚪' if 'long' in name else '🔵'} {name}: {reply[:100]}...")

    return responses

def run_simulation(scenario_path: str, output_dir: str = "output_crew_full"):
    """运行完整模拟"""
    # 加载场景
    with open(scenario_path) as f:
        scenario = yaml.safe_load(f)

    load_configs()

    # 初始化
    market = Market(scenario["initial_market"], mode="backtest")
    events = scenario.get("events") or scenario.get("timeline", [])

    # Agent记忆
    memories = {
        "hedge_fund": AgentMemory("对冲基金", "hedge_fund"),
        "long_only": AgentMemory("长线外资", "long_only"),
        "southbound": AgentMemory("南下资金", "southbound"),
        "value_investor": AgentMemory("价值投资者", "value_investor"),
    }

    # 记录市场历史用于触发判断
    prev_market_states = []

    # 记录对话触发点
    dialogue_triggers = []

    # 催化剂后计数（用于长线外资硬约束）
    catalyst_day = None

    print(f"\n{'='*60}")
    print(f"🎮 CrewAI完整版模拟启动")
    print(f"📋 场景: {scenario['scenario']['name']}")
    print(f"📅 周期: {events[0]['date']} → {events[-1]['date']}")
    print(f"{'='*60}\n")

    for day_idx, event in enumerate(events):
        date = event["date"]
        print(f"\n--- 📅 {date} ---")

        # 更新市场
        market.update_from_event(event)
        market_state = market.get_state()
        prev_market_states.append(market_state)

        change = market_state.get("daily_change_pct", 0)
        print(f"📊 恒指: {market_state['hsi_close']} ({change:+.1f}%) 情绪: {market_state['sentiment']}")

        # 催化剂检测（政策信号>0.7且是第一天）
        if catalyst_day is None and event.get("policy_signal_strength", 0) > 0.7:
            catalyst_day = day_idx
            print(f"    ⚡ 检测到催化剂，长线外资进入3天冷静期")

        days_since_catalyst = day_idx - catalyst_day if catalyst_day is not None else -1

        # 检查是否触发对话
        trigger, reason = should_trigger_dialogue(event, market_state, prev_market_states[:-1])

        dialogue_context = ""
        if trigger:
            market_summary = f"恒指{market_state['hsi_close']} ({change:+.1f}%)，情绪{market_state['sentiment']}"
            topic = f"今天市场{('暴涨' if change > 3 else '暴跌' if change < -3 else '波动')}，大家怎么看？"

            responses = run_dialogue(
                ["hedge_fund", "southbound", "long_only", "value_investor"],
                topic,
                market_summary
            )

            dialogue_context = f"\n今日群聊：{reason}\n" + "\n".join([f"- {k}: {v[:50]}..." for k, v in responses.items()])
            dialogue_triggers.append({"date": date, "reason": reason, "responses": responses})

        # 每个Agent做决策
        for name_en, memory in memories.items():
            # 硬约束：长线外资催化剂后前3天强制hold
            if name_en == "long_only" and days_since_catalyst >= 0 and days_since_catalyst < 3:
                decision = {
                    "date": date, "agent": memory.agent_name,
                    "action": "hold", "position_change_pct": 0,
                    "reasoning": f"[强制] 内部评估流程进行中（催化剂后第{days_since_catalyst+1}天/需3天）",
                    "emotion": "anxiety", "confidence": 0.5, "_forced": True
                }
                memory.update(decision, market_state)
                print(f"    ⚪ {memory.agent_name}: hold [强制] | 内部流程约束")
                continue

            config = AGENT_CONFIGS.get(name_en, {})
            role = config.get("role", f"你是{name_en}")[:800]

            mem_context = memory.to_prompt_context(lookback=3)

            prompt = f"""{role}

{mem_context}

## 今日市场
- 恒指: {market_state['hsi_close']} ({change:+.1f}%)
- 情绪: {market_state['sentiment']}
- 事件: {event.get('description', '无')[:100]}
{dialogue_context}

请做出今天的交易决策。
输出JSON：{{"action": "buy/sell/hold/cover_short/add_short", "position_change_pct": 0-100, "reasoning": "...", "emotion": "calm/anxiety/fomo/greed/fear/panic", "confidence": 0-1}}
"""
            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    response_format={"type": "json_object"},
                    max_tokens=300
                )
                decision = json.loads(response.choices[0].message.content)
                decision["date"] = date
                decision["agent"] = memory.agent_name
            except Exception as e:
                decision = {
                    "date": date, "agent": memory.agent_name,
                    "action": "hold", "position_change_pct": 0,
                    "reasoning": f"错误: {str(e)[:30]}",
                    "emotion": "calm", "confidence": 0
                }

            memory.update(decision, market_state)

            emoji = {"buy": "🟢", "sell": "🔴", "hold": "⚪",
                     "cover_short": "🟡", "add_short": "🔵"}.get(decision["action"], "❓")
            forced_tag = " [强制]" if decision.get("_forced") else ""
            print(f"    {emoji} {memory.agent_name}: {decision['action']}{forced_tag} | {decision['reasoning'][:40]}...")

    # 保存结果
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    with open(output_path / "dialogue_triggers.json", "w", encoding="utf-8") as f:
        json.dump(dialogue_triggers, f, ensure_ascii=False, indent=2)

    # 保存记忆
    for name, mem in memories.items():
        mem.save(str(output_path / f"{name}_memory.json"))

    print(f"\n{'='*60}")
    print(f"✅ CrewAI完整版模拟完成！")
    print(f"📊 对话触发次数: {len(dialogue_triggers)}")
    print(f"💾 结果保存至: {output_dir}")
    print(f"{'='*60}")

    return dialogue_triggers

if __name__ == "__main__":
    import sys
    scenario = sys.argv[1] if len(sys.argv) > 1 else "events/924_stimulus.yaml"
    run_simulation(scenario)
