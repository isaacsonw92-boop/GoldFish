# 测试运行计划（防死循环版）

## 目标
执行 `run.py` 脚本以验证 `forecast` 模式下的场景推演功能，确保之前的修改（对冲基金决策优化、真实数据对比）正常工作。如遇死循环，立即汇报并终止。

## 步骤
1.  **准备环境**: 确保 API Key 环境变量已设置。
2.  **执行模拟**: 运行 `924_stimulus.yaml` 场景，**限时 120 秒**，超时即视为死循环。
3.  **验证结果**:
    -   检查运行日志是否有报错或超时。
    -   检查 `output/reports/simulation_report.md` 中的对冲基金行为（是否出现 `buy` 操作）。
    -   检查报告中的 MAPE 对比数据。
    -   检查 `output/reports/dashboard.png` 是否生成。

## 命令
```powershell
$env:LLM_API_KEY = "sk-bf316c318b77410a91dc8f4bceca6b93"
$env:LLM_BASE_URL = "https://api.deepseek.com"
python run.py --mode forecast --scenario events/924_stimulus.yaml --model deepseek-chat
```

## 死循环判定
- 若终端持续输出相同内容超过 30 秒，或总运行时间超过 120 秒，即视为死循环。
- 出现死循环时，立即终止进程并汇报用户。
