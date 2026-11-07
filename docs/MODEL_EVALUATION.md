# 模型能力与评估

## 模型链路

真实模式使用DeepSeek官方deepseek-flash，通过LangChain ChatDeepSeek调用，model/graph/prompt profile为reimbursement.v2.1。图像输入能力已由账户模型元数据与实际图像请求验证；供应商能力可能变化，应在配置新服务时重新核验。

请求前只从授权材料页装载图片，检查点保存引用和结构化事实，不保存Key或base64。JSON Action/Facts经Pydantic与图验证；超时、限流、空值、结构错误或预算不足明确失败，不自动退成fixture。

## 已有真实证据

| 评估 | 结果与适用范围 |
| --- | --- |
| 材料理解 | synthetic.v2的10份合成原件均生成provider事实，覆盖付款、税票、铁路票、退款、未付款、聊天、多笔扣款、优惠与佐证 |
| 字段差异 | 1项聊天转账角色：预期unknown，模型返回payment；付款状态仍unknown，金额不自动计入，进入人工确认 |
| 合成业务审核 | 规则reimbursement-v1-001下8例：五正常入口可提交，错抬头/未付款阻止，金额不明waiting_input；标签集误放行0、误拦截0、技术失败0 |
| 调用和耗时 | 上述集34次请求，输入106384、输出9424、总115808 token；当次69.29秒 |
| 当前总额规则专项 | reimbursement-v1-002下真实构建页面完成独立总额100/明细88拦截→人工改88→旧报告失效→重审→SIM创建；最终单次4次调用，含390px金额可见性检查 |
| 费用 | 服务响应未提供实际扣费金额，只记录真实token，不推算账单 |

以上为合成数据评估，不是原公司真实票据准确率。v1-001审核集不冒充当前v1-002完整重评；独立总额规则和当前真实流程单列。去除图像/业务运行ID后的[评估摘要](evaluation/summary.json)可随仓库阅读。

## 复现

真实评估需要本机backend/.env配置可用多模态服务，且显式使用--live；普通pytest/CI清空Key。原生PG已运行时，在独立评估终端首次创建专用库：

```powershell
$pgBin = Join-Path $env:LOCALAPPDATA 'reimbursement-v2-runtime/pgsql/bin'
# 仅在库尚不存在时执行createdb
& "$pgBin/createdb.exe" -h 127.0.0.1 -p 15432 -U reimbursement reimbursement_v2_eval
cd backend
$env:DATABASE_URL = 'postgresql+psycopg://reimbursement:development@127.0.0.1:15432/reimbursement_v2_eval'
$env:CHECKPOINT_URL = 'postgresql://reimbursement:development@127.0.0.1:15432/reimbursement_v2_eval?options=-csearch_path%3Dagent_runtime'
$env:FILE_ROOT = '../data/v2/eval-files'
uv run alembic upgrade head
uv run python -m reimbursement.bootstrap
uv run python scripts/evaluate_models.py --live --max-calls 60
```

当前脚本会记录运行时规则版本，使用独立评估库，输出在忽略的data目录；拒绝应用/测试库。结束后关闭该终端，不把评估库环境传入应用。

## 局限

模型仍可能误读或无法判断模糊照片、复杂聊天与特殊版式。人工总额提供独立交叉核验，不能替代凭证真实性保证。对未定义的审批/替票政策，模型不能新增豁免。

官方资料：[图像输入](https://api-docs.deepseek.com/guides/vision/)、[模型元数据](https://api-docs.deepseek.com/api/list-models/)、[JSON输出](https://api-docs.deepseek.com/guides/json_mode/)。
