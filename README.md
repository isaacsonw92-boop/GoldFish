# 港股沙盘模拟 (HK Sandbox)

## 这是什么

基于多Agent + LLM的港股市场参与者行为模拟器。

通过模拟四类核心参与者（对冲基金、长线外资、南下资金、价值投资者）的决策行为和相互影响，推演港股在特定事件冲击下的反应序列。

**核心理念：股价不由公司价值决定，由参与者的激励结构决定。**

## 四类Agent

| Agent | 核心激励 | 反应速度 | 核心恐惧 |
|-------|---------|---------|---------|
| 对冲基金 | 绝对收益+alpha | T+0（小时级） | 爆仓 |
| 长线外资 | 跑赢MSCI基准 | T+3~7（天级） | 跑输同行 |
| 南下资金 | 规模+排名/赚钱 | T+0~1 | 错过行情 |
| 价值投资者 | 长期复利 | 周/月级 | 看错基本面 |

## 快速开始

```bash
# 安装依赖
pip install openai pyyaml

# 配置API（以DeepSeek为例）
export LLM_API_KEY=sk-your-key
export LLM_BASE_URL=https://api.deepseek.com

# 运行924回溯测试
cd hk-sandbox
python run.py --model deepseek-chat

# 用Claude跑（角色扮演更强）
export LLM_API_KEY=sk-your-anthropic-key
export LLM_BASE_URL=https://api.anthropic.com/v1
python run.py --model claude-sonnet-4-20250514
```

## 项目结构

```
hk-sandbox/
├── config/                    # Agent参数配置
│   ├── hedge_fund.yaml        # 对冲基金
│   ├── long_only.yaml         # 长线外资
│   ├── southbound.yaml        # 南下资金
│   └── value_investor.yaml    # 价值投资者
├── events/                    # 事件场景
│   └── 924_stimulus.yaml      # 2024.9.24回溯测试
├── engine/                    # 核心引擎
│   ├── agent.py               # Agent基类（LLM决策）
│   ├── market.py              # 市场状态管理
│   └── scheduler.py           # 调度器
├── output/                    # 模拟输出
│   ├── logs/                  # 每日决策日志(JSON)
│   └── reports/               # 总结报告(Markdown)
└── run.py                     # 主入口
```

## 验证标准

924回溯测试的标准答案：
1. **反应顺序**：对冲基金空头回补 → 南下资金涌入 → 长线外资回补 → 价值投资者不动
2. **反转触发**：10月8日发改委发布会缺乏细节
3. **退出顺序**：对冲基金先跑 → 南下散户恐慌跟跑 → 长线外资暂停 → 价值投资者考虑加仓
