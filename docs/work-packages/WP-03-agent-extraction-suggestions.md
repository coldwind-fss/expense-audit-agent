# WP-03 · 共享Agent、识别与字段建议

状态：已实施。依赖：WP-02。上位：[产品基线](../PRODUCT_BASELINE.md)、[业务基线](../BUSINESS_BASELINE.md)、[技术基线](../TECHNICAL_BASELINE.md)。

## 目的与范围

在同一个执行器中实现逐份识别与已归属事实的字段建议，保护人工值。

## 实现入口

- agent_service.py、agent_graph.py、task_handlers.py、model_gateway.py
- api_agents.py、AgentPanel.vue

## 数据、接口与业务约束

- POST /materials/{id}/extract与/claims/{id}/suggestions返回202任务
- TaskHandler固定工具、提示与预算，结构化Action/Facts校验
- 建议批次apply使用selected_indices/replace_manual，undo核对字段所有权
- 材料事实与模式版本分开；不建行/分配/写事由或人工总额

## 验收依据

- 来源、字段保护、采纳/撤回及过期批次
- 人工等待/重复响应、预算/无进展/结构失败/未知图
- 跨进程恢复、工具范围与旧attempt拒绝发布

详细命令和适用边界见[测试说明](../TESTING.md)及[模型评估](../MODEL_EVALUATION.md)。企业接口始终为本地Stub；未实际运行的环境和未取得的真实票面不计为通过。
