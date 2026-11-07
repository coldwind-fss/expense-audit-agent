# 源码导读

## 从产品到代码

先读[产品基线](PRODUCT_BASELINE.md)与[业务基线](BUSINESS_BASELINE.md)，再按一条报销链路阅读：

1. `frontend/src/pages/ClaimsPage.vue`选择入口并创建草稿。
2. `ClaimEditor.vue`维护五步表单、独立人工总额、主体与版本；`ApprovalPicker.vue`展示自动读取的关联审批。
3. `api_claims.py`推导身份与目录范围，保存草稿/行/账户；`services.py`管理修订、审计和命令幂等。
4. `MaterialWorkbench.vue`上传和人工归行；`api_materials.py`保存原件并建立prepare任务。
5. `preparation.py`准备页，`worker.py`认领执行；`agent_service.py`冻结任务输入。
6. `task_handlers.py`给出三任务工具/预算；`agent_graph.py`驱动图，`model_gateway.py`适配模型。
7. `rules.py`将材料事实转为有效支持并执行确定校验；`api_agents.py`处理报告、人工响应和建议批次。
8. `AgentPanel.vue`展示问题及金额对照，用户修正后重审，再调用提交接口。
9. `submission_service.py`冻结并复核，Worker负责排期与本地幂等模拟创建。
10. `api_operations.py`和`ledger.py`处理管理、台账和反馈；`HistoryPage.vue`呈现明确结果。

## 建议先看的实现点

| 关注点 | 入口 |
| --- | --- |
| 独立总额为什么不会被识别覆盖 | models.Claim / schemas.ClaimPatch / services.bump_claim / rules.evaluate |
| 模型为什么不能直接放行 | agent_graph.finish / rules.evaluate / submission_service.create_submission |
| 如何拒绝旧结果 | agent_service.publish / Worker lease_token / review_signature |
| 如何持久恢复 | agent_graph.execute / AsyncPostgresSaver / checkpoint_process_probe.py |
| 如何保护人工值 | rules.sync_line_amounts / suggestion-batches apply / undo |
| 多材料如何分配 | api_materials.bindings及工作台，稳定material_id/line_id |
| 真实服务与fixture如何隔离 | model_gateway / input_signature / execution_mode |
| unknown为什么不能重发 | submission_service.dispatch / 管理query动作 / GatewayResult |
| Excel如何关联图片 | imports.py的行/图片锚点与prepare子任务 |
| 金额和日期特殊场景在哪里测 | test_boundaries.py / test_workflows.py |

## 目录

```text
backend/
  src/reimbursement/   API、应用服务、领域规则、Agent、队列、企业边界
  migrations/          0001—0004数据库迁移
  scripts/             OpenAPI导出、显式真实模型评估
  tests/               PG/API、规则、图、provider契约与跨进程恢复
  openapi.json         生成HTTP契约
  pyproject.toml       Python包及质量工具
  uv.lock              精确依赖
frontend/
  src/pages/           工作台、编辑、历史、管理、反馈
  src/components/      审批、材料、Agent面板
  src/api/             HTTP客户端、生成类型与契约单测
  tests/e2e/           实际浏览器流程
infra/                 原生启动/停止、静态服务、Compose
.github/workflows/     离线工程CI
docs/                  最终产品、业务、架构、运行与验证文档
```

源代码与锁文件是实现依据；文档用于解释意图和关系，不把文件存在、字符串或截图当成功能通过的证明。
