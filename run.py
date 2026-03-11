#!/usr/bin/env python3
"""
港股沙盘模拟 - 主入口
用法: python run.py [--model MODEL] [--scenario SCENARIO]
"""
import argparse
import os
import sys
from pathlib import Path

from openai import OpenAI
from engine.scheduler import Scheduler


def main():
    parser = argparse.ArgumentParser(description="港股沙盘模拟")
    parser.add_argument("--model", default="deepseek-chat",
                        help="LLM模型名称 (默认: deepseek-chat)")
    parser.add_argument("--scenario", default="events/924_stimulus.yaml",
                        help="场景文件路径")
    parser.add_argument("--config-dir", default="config",
                        help="Agent配置目录")
    parser.add_argument("--output", default="output",
                        help="输出目录")
    parser.add_argument("--mode", default="backtest", choices=["backtest", "forecast"],
                        help="运行模式: backtest=回溯测试(读YAML真实数据), forecast=推演模式(Agent决策合成价格)")
    parser.add_argument("--api-key", default=None,
                        help="LLM API Key (也可用环境变量 LLM_API_KEY)")
    parser.add_argument("--base-url", default=None,
                        help="LLM API Base URL (也可用环境变量 LLM_BASE_URL)")

    args = parser.parse_args()

    # API配置
    api_key = args.api_key or os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = args.base_url or os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")

    if not api_key:
        print("❌ 需要设置 LLM_API_KEY 环境变量或通过 --api-key 传入")
        print("   支持 DeepSeek / OpenAI / 任何兼容 OpenAI SDK 的服务")
        print("")
        print("   示例 (DeepSeek):")
        print("   export LLM_API_KEY=sk-xxx")
        print("   export LLM_BASE_URL=https://api.deepseek.com")
        print("   python run.py --model deepseek-chat")
        print("")
        print("   示例 (OpenAI):")
        print("   export LLM_API_KEY=sk-xxx")
        print("   python run.py --model gpt-4o")
        sys.exit(1)

    # 初始化LLM客户端
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    llm_client = OpenAI(**client_kwargs)

    # 验证文件存在
    if not Path(args.scenario).exists():
        print(f"❌ 场景文件不存在: {args.scenario}")
        sys.exit(1)
    if not Path(args.config_dir).exists():
        print(f"❌ 配置目录不存在: {args.config_dir}")
        sys.exit(1)

    # 启动模拟
    scheduler = Scheduler(
        scenario_path=args.scenario,
        config_dir=args.config_dir,
        llm_client=llm_client,
        model=args.model,
        mode=args.mode
    )
    scheduler.run(output_dir=args.output)


if __name__ == "__main__":
    main()
