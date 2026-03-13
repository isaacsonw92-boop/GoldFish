#!/usr/bin/env python3
"""
CrewAI优化版 - 只在关键天调LLM，其他天用规则引擎
减少API调用次数，避免超时
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

def rule_based_decision(name_en, memory, market_state, event):
    """规则引擎：普通天用规则快速决策"""
    change = market_state.get("daily_change_pct", 0)
    sentiment = market_state.get("sentiment", "neutral")
    pos = memory.position

    # 对冲基金规则
    if name_en == "hedge_fund":
        if pos.direction == "short" and change > 2:
            return {"action": "cover_short", "position_change_pct": pos.size_pct,
                    "reasoning": "市场上涨，平空锁定利润", "emotion": "anxiety", "confidence": 0.7}
        if pos.direction == "flat" and change > 3:
            return {"action": "buy", "position_change_pct": 30,
                    "reasoning": "趋势向上，建立多头", "emotion": "fomo", "confidence": 0.6}
        if pos.direction == "long" and change < -3:
            return {"action": "sell", "position_change_pct": pos.size_pct,
                    "reasoning": "市场下跌，减仓避险", "emotion": "fear", "confidence": 0.6}
        return {"action": "hold", "position_change_pct": 0,
                "reasoning": "观望", "emotion": "calm", "confidence": 0.5}

    # 长线外资规则
    if name_en == "long_only":
        # 催化剂后3天强制hold在调用处处理
        if pos.direction == "flat" and change > 1:
            return {"action": "buy", "position_change_pct": 20,
                    "reasoning": "分批建仓", "emotion": "anxiety", "confidence": 0.6}
        return {"action": "hold", "position_change_pct": 0,
                "reasoning": "观望", "emotion": "calm", "confidence": 0.5}

    # 南下资金规则
    if name_en == "southbound":
        policy = event.get("policy_signal_strength", 0)
        geo = event.get("geopolitical_risk", 0)
        if policy > 0.5 and pos.direction != "long":
            return {"action": "buy", "position_change_pct": 40,
                    "reasoning": "政策利好，信仰买入", "emotion": "fomo", "confidence": 0.8}
        if geo > 0.7 and pos.direction == "long":
            return {"action": "sell", "position_change_pct": pos.size_pct,
                    "reasoning": "地缘风险，减仓", "emotion": "panic", "confidence": 0.6}
        return {"action": "hold", "position_change_pct": 0,
                "reasoning": "观望", "emotion": "calm", "confidence": 0.5}

    # 价值投资者规则
    if name_en == "value_investor":
        # 几乎不动
        return {"action": "hold", "position_change_pct": 0,
                "reasoning": "等待安全边际", "emotion": "calm", "confidence": 0.9}

    return {"action": "hold", "position_change_pct": 0,
            "reasoning": "默认", "emotion": "calm", "confidence": 0.5}

def llm_decision(name_en, config, memory, market_state, event, dialogue_ctx=""):
    """LLM决策：关键天调API"""
    role = config.get("role", "")[:500]
    mem_ctx = memory.to_prompt_context(lookback=2)

    # 限制action
    if name_en == "hedge_fund":
        actions = "buy/sell/hold/cover_short/add_short"
        note = "你是唯一可以做空的Agent。"
    else:
        actions = "buy/sell/hold"
        note = "你只能做多或持有，不能做空。"

    prompt = f"""{role}

{mem_ctx}

## 今日市场
- 恒指: {market_state['hsi_close']} ({market_state.get('daily_change_pct', 0):+.1f}%)
- 情绪: {market_state['sentiment']}
- 事件: {event.get('description', '无')[:80]}
{dialogue_ctx}

## 可用操作
{actions}
{note}

输出JSON：{{"action": "...", "position_change_pct": 0-100, "reasoning": "...", "emotion": "...", "confidence": 0-1}}
"""
    try:
        r = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            response_format={"type": "json_object"},
            max_tokens=350
        )
        return json.loads(r.choices[0].message.content)
    except Exception as e:
        return {"action": "hold", "position_change_pct": 0,
                "reasoning": f"错误:{str(e)[:20]}", "emotion": "calm", "confidence": 0}

def run_optimized(scenario_path: str):
    """优化版运行"""
    load_configs()

    with open(scenario_path) as f:
        scenario = yaml.safe_load(f)

    market = Market(scenario["initial_market"], mode="backtest")
    events = scenario.get("events") or scenario.get("timeline", [])

    memories = {
        "hedge_fund": AgentMemory("对冲基金", "hedge_fund"),
        "long_only": AgentMemory("长线外资", "long_only"),
        "southbound": AgentMemory("南下资金", "southbound"),
        "value_investor": AgentMemory("价值投资者", "value_investor"),
    }

    # 初始给对冲基金空头
    memories["hedge_fund"].position.direction = "short"
    memories["hedge_fund"].position.size_pct = 20
    memories["hedge_fund"].position.avg_entry_price = 26000

    catalyst_day = None
    llm_calls = 0
    rule_calls = 0

    print(f"\n{'='*60}")
    print(f"🎮 CrewAI优化版（关键天LLM+普通天规则）")
    print(f"📋 场景: {scenario['scenario']['name']}")
    print(f"{'='*60}\n")

    for day_idx, event in enumerate(events):
        date = event["date"]
        market.update_from_event(event)
        ms = market.get_state()
        change = ms.get("daily_change_pct", 0)

        # 催化剂检测
        if catalyst_day is None and event.get("policy_signal_strength", 0) > 0.7:
            catalyst_day = day_idx
            print(f"⚡ 催化剂触发 @ {date}")

        days_since = day_idx - catalyst_day if catalyst_day is not None else -1

        # 判断是否为关键天
        is_key_day = abs(change) > 3 or event.get("policy_signal_strength", 0) > 0.5 or event.get("geopolitical_risk", 0) > 0.7

        print(f"\n--- {date} | {ms['hsi_close']} ({change:+.1f}%) {'[关键天-LLM]' if is_key_day else '[普通天-规则]' } ---")

        for name_en, memory in memories.items():
            # 硬约束
            if name_en == "long_only" and days_since >= 0 and days_since < 3:
                dec = {"action": "hold", "position_change_pct": 0,
                       "reasoning": f"[强制]第{days_since+1}天", "emotion": "anxiety", "confidence": 0.5, "_forced": True}
            elif is_key_day:
                config = AGENT_CONFIGS.get(name_en, {})
                dec = llm_decision(name_en, config, memory, ms, event)
                llm_calls += 1
            else:
                dec = rule_based_decision(name_en, memory, ms, event)
                rule_calls += 1

            dec["date"] = date
            dec["agent"] = memory.agent_name
            memory.update(dec, ms)

            emoji = {"buy": "🟢", "sell": "🔴", "hold": "⚪",
                     "cover_short": "🟡", "add_short": "🔵"}.get(dec["action"], "❓")
            forced = " [强制]" if dec.get("_forced") else ""
            src = "LLM" if is_key_day and not dec.get("_forced") else "规则"
            print(f"  {emoji} {memory.agent_name}: {dec['action']}{forced} ({src}) | {dec.get('reasoning', '')[:30]}")

    print(f"\n{'='*60}")
    print(f"✅ 完成！LLM调用: {llm_calls}, 规则调用: {rule_calls}")
    print(f"{'='*60}")

    print("\n=== 终态 ===")
    for name, mem in memories.items():
        can_short = "可做空" if name == "hedge_fund" else "只能做多"
        print(f"{mem.agent_name}({can_short}): {mem.position.direction} {mem.position.size_pct:.0f}% | 已实现{mem.position.realized_pnl_pct:+.1f}%")

if __name__ == "__main__":
    import sys
    scenario = sys.argv[1] if len(sys.argv) > 1 else "events/924_stimulus.yaml"
    run_optimized(scenario)
