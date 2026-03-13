#!/usr/bin/env python3
"""
CrewAI MVP - 最小可行验证
目标：验证两个Agent对话是否会产生C方案没有的行为
场景：924第一天，对冲基金和南下资金对话
"""
import os
import json
from openai import OpenAI

# 配置
api_key = os.environ.get("LLM_API_KEY") or "sk-bf316c318b77410a91dc8f4bceca6b93"
base_url = os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com"

client = OpenAI(api_key=api_key, base_url=base_url)

# Agent系统提示
hedge_fund_prompt = """你是对冲基金经理。
- 使用3倍杠杆，核心恐惧是爆仓
- 你目前持有空头仓位（做空中国）
- 今天市场突然暴涨4%，你在考虑是否平仓

你要和南下资金（内地散户）对话，了解他们为什么买入。
输出你的问题和想法。"""

southbound_prompt = """你是南下资金（内地散户）。
- 你有强烈的"政策信仰"，相信国家队会救市
- 你今天看到政策利好消息，已经买入
- 你认为这是对岸（外资）不懂中国

对冲基金在问你为什么买入，你要回应他。
输出你的回答和想法。"""

def chat_round(hedge_msg: str, south_msg: str, round_num: int):
    """一轮对话"""
    print(f"\n=== 第{round_num}轮对话 ===")

    # 对冲基金发言
    hf_response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": hedge_fund_prompt},
            {"role": "user", "content": f"南下资金说：{south_msg}\n\n你要怎么回应？直接说出你的想法。"}
        ],
        temperature=0.7
    )
    hedge_reply = hf_response.choices[0].message.content
    print(f"\n🟡 对冲基金：{hedge_reply[:200]}...")

    # 南下资金回应
    sb_response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": southbound_prompt},
            {"role": "user", "content": f"对冲基金说：{hedge_reply}\n\n你要怎么回应？直接说出你的想法。"}
        ],
        temperature=0.7
    )
    south_reply = sb_response.choices[0].message.content
    print(f"\n🟢 南下资金：{south_reply[:200]}...")

    return hedge_reply, south_reply

def main():
    print("="*60)
    print("CrewAI MVP验证：对冲基金 vs 南下资金")
    print("场景：2024-09-24，政策刺激首日，恒指暴涨4%")
    print("="*60)

    # 初始消息
    hedge_first = "今天市场怎么突然涨这么多？你们内地资金是不是听到什么风声了？"
    south_first = "政策出大利好了！降准降息，国家队要出手了！你们外资就是太谨慎。"

    print(f"\n🟡 对冲基金：{hedge_first}")
    print(f"\n🟢 南下资金：{south_first}")

    # 对话3轮
    hedge_msg, south_msg = hedge_first, south_first
    for i in range(1, 4):
        hedge_msg, south_msg = chat_round(hedge_msg, south_msg, i)

    # 最终决策
    print("\n" + "="*60)
    print("最终决策")
    print("="*60)

    hedge_decision = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": hedge_fund_prompt + "\n\n基于以上对话，输出你的最终交易决策。JSON格式：{\"action\": \"cover_short/add_short/hold\", \"reasoning\": \"...\"}"},
            {"role": "user", "content": "对话结束，做出你的决策。"}
        ],
        temperature=0.7,
        response_format={"type": "json_object"}
    )
    print(f"\n🟡 对冲基金决策：{hedge_decision.choices[0].message.content}")

    south_decision = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": southbound_prompt + "\n\n基于以上对话，输出你的最终交易决策。JSON格式：{\"action\": \"buy/sell/hold\", \"reasoning\": \"...\"}"},
            {"role": "user", "content": "对话结束，做出你的决策。"}
        ],
        temperature=0.7,
        response_format={"type": "json_object"}
    )
    print(f"\n🟢 南下资金决策：{south_decision.choices[0].message.content}")

if __name__ == "__main__":
    main()
