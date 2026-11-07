# WP-06 · 管理、台账与反馈

状态：已实施。依赖：WP-05。上位：[产品基线](../PRODUCT_BASELINE.md)、[业务基线](../BUSINESS_BASELINE.md)、[技术基线](../TECHNICAL_BASELINE.md)。

## 目的与范围

提供完整辅助业务模块，同时保持受控权限和本地模拟边界。

## 实现入口

- api_operations.py、ledger.py
- AdminPage.vue、FeedbackPage.vue

## 数据、接口与业务约束

- 管理员案件保存不提交，repair完整预校验并记录原因，submit复用最终规则
- 台账默认audit，仅显式sync写本地13列投影；未改且未入账才回滚
- 反馈批次/收件人去重、token摘要、失败轮换、唯一答卷与CSV
- 模拟审批退回/撤销与创建状态分开，不触发重复发起

## 验收依据

- 受控管理员修复/提交、原值保护与回滚冲突
- 13列、缺字段/勾稽错、audit/sync和幂等
- 反馈邀请→匿名专属答卷→后台查询，旧token失效

详细命令和适用边界见[测试说明](../TESTING.md)及[模型评估](../MODEL_EVALUATION.md)。企业接口始终为本地Stub；未实际运行的环境和未取得的真实票面不计为通过。
