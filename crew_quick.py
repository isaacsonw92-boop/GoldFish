#!/usr/bin/env python3
"""
CrewAI快速验证 - 只跑关键3天（9/24-9/26）
验证硬约束和对话触发是否正常工作
"""
import os
import json
import yaml
from pathlib import Path
from openai import OpenAI
from engine.memory import AgentMemory
from engine.market import Market

api_key = os.environ.get("LLM_API_KEY") or "sk-bf316c318b77410a91dc8f4bceca6b93"
base_url = os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com"
client = OpenAI(api_key=api_key, base_url=base_url)

AGENT_CONFIGS = {}

def load_configs(config_dir="config"):
    for f in Path(config_dir).glob("*.yaml"):
        with open(f) as fp:
            AGENT_CONFIGS[f.stem] = yaml.safe_load(fp)

def quick_decision(name_en, config, memory, market_state, event, days_since_catalyst, dialogue_context):
    """快速决策"""
    # 硬约束
    if name_en == "long_only" and days_since_catalyst >= 0 and days_since_catalyst < 3:
        return {
            "action": "hold", "position_change_pct": 0,
            "reasoning": f"[强制] 内部流程第{days_since_catalyst+1}天",
            "emotion": "anxiety", "confidence": 0.5, "_forced": True
        }

    role = config.get("role", f"你是{name_en}")[:600]
    mem_context = memory.to_prompt_context(lookback=2)

    prompt = f"""{role}

{mem_context}

## 今日市场
- 恒指: {market_state['hsi_close']} ({market_state.get('daily_change_pct', 0):+.1f}%)
- 情绪: {market_state['sentiment']}
- 事件: {event.get('description', '无')[:80]}
{dialogue_context}

输出JSON决策：{{"action": "buy/sell/hold/cover_short/add_short", "position_change_pct": 0-100, "reasoning": "...", "emotion": "...", "confidence": 0-1}}
"""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            response_format={"type": "json_object"},
            max_tokens=250
        )
        decision = json.loads(response.choices[0].message.content)
        decision["_forced"] = False
        return decision
    except Exception as e:
        return {"action": "hold", "position_change_pct": 0, "reasoning": f"错误:{str(e)[:20]}", "emotion": "calm", "confidence": 0}

def run_quick_test():
    load_configs()

    with open("events/924_stimulus.yaml") as f:
        scenario = yaml.safe_load(f)

    market = Market(scenario["initial_market"], mode="backtest")
    events = scenario.get("events") or scenario.get("timeline", [])

    memories = {
        "hedge_fund": AgentMemory("对冲基金", "hedge_fund"),
        "long_only": AgentMemory("长线外资", "long_only"),
        "southbound": AgentMemory("南下资金", "southbound"),
        "value_investor": AgentMemory("价值投资者", "value_investor"),
    }

    catalyst_day = None

    print("="*60)
    print("CrewAI快速验证（9/24-9/26关键3天）")
    print("="*60)

    for day_idx, event in enumerate(events[:6]):  # 只跑前6天
        date = event["date"]
        print(f"\n--- {date} ---")

        market.update_from_event(event)
        ms = market.get_state()
        change = ms.get("daily_change_pct", 0)
        print(f"恒指: {ms['hsi_close']} ({change:+.1f}%)")

        # 催化剂检测
        if catalyst_day is None and event.get("policy_signal_strength", 0) > 0.7:
            catalyst_day = day_idx
            print("⚡ 催化剂触发，长线外资进入冷静期")

        days_since = day_idx - catalyst_day if catalyst_day is not None else -1

        # 对话触发（>3%）
        dialogue_ctx = ""
        if abs(change) > 3:
            print(f"🗣️ 群聊触发：波动{change:.1f}%")
            dialogue_ctx = "\n群聊：大家在讨论今天的剧烈波动。"

        # 决策
        for name_en, memory in memories.items():
            config = AGENT_CONFIGS.get(name_en, {})
            dec = quick_decision(name_en, config, memory, ms, event, days_since, dialogue_ctx)
            dec["date"] = date
            dec["agent"] = memory.agent_name
            memory.update(dec, ms)

            emoji = {"buy": "🟢", "sell": "🔴", "hold": "⚪", "cover_short": "🟡", "add_short": "🔵"}.get(dec["action"], "❓")
            forced = " [强制]" if dec.get("_forced") else ""
            print(f"  {emoji} {memory.agent_name}: {dec['action']}{forced}")

    # 总结
    print("\n" + "="*60)
    print("验证结果")
    print("="*60)
    for name, mem in memories.items():
        pos = mem.position
        print(f"{mem.agent_name}: {pos.direction} {pos.size_pct:.0f}% | 已实现{pos.realized_pnl_pct:+.1f}% | 交易{mem.trade_count}次")

if __name__ == "__main__":
    run_quick_test()
