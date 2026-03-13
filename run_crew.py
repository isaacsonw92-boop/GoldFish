#!/usr/bin/env python3
"""
CrewAI版本港股沙盘模拟 - 运行入口
"""
import argparse
import os
import sys
from pathlib import Path

from openai import OpenAI
from engine.crew_scheduler import CrewScheduler


def main():
    parser = argparse.ArgumentParser(description="CrewAI港股沙盘模拟")
    parser.add_argument("--model", default="deepseek-chat",
                        help="LLM模型名称 (默认: deepseek-chat)")
    parser.add_argument("--scenario", default="events/924_stimulus.yaml",
                        help="场景文件路径")
    parser.add_argument("--config-dir", default="config",
                        help="Agent配置目录")
    parser.add_argument("--output", default="output_crew",
                        help="输出目录")
    parser.add_argument("--api-key", default=None,
                        help="LLM API Key")
    parser.add_argument("--base-url", default=None,
                        help="LLM API Base URL")

    args = parser.parse_args()

    # API配置
    api_key = args.api_key or os.environ.get("LLM_API_KEY")
    base_url = args.base_url or os.environ.get("LLM_BASE_URL")

    if not api_key:
        print("❌ 需要设置 LLM_API_KEY")
        sys.exit(1)

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    llm_client = OpenAI(**client_kwargs)

    # 验证文件
    if not Path(args.scenario).exists():
        print(f"❌ 场景文件不存在: {args.scenario}")
        sys.exit(1)

    # 启动模拟
    scheduler = CrewScheduler(
        scenario_path=args.scenario,
        config_dir=args.config_dir,
        llm_client=llm_client,
        model=args.model
    )
    scheduler.run(output_dir=args.output)


if __name__ == "__main__":
    main()
