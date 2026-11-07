# WP-05 · 冻结提交、排期与模拟OA

状态：已实施。依赖：WP-04。上位：[产品基线](../PRODUCT_BASELINE.md)、[业务基线](../BUSINESS_BASELINE.md)、[技术基线](../TECHNICAL_BASELINE.md)。

## 目的与范围

在用户确认后复核并冻结申报，持久排期，处理幂等、未知与旁路恢复。

## 实现入口

- submission_service.py、api_submissions.py、worker.py
- HistoryPage.vue

## 数据、接口与业务约束

- POST /claims/{id}/submissions复核revision/review/signature/规则，返回202持久命令
- 单报销提交唯一，Stub命令唯一；SIM不是真实external_instance_id
- 启用排期时按上海月度窗口、时段、FIFO和三分钟guard
- unknown先query；允许状态cancel-and-copy，不改旧快照

## 验收依据

- 重复命令/换键、冻结快照及不可修改锁定单
- 月度、跨年、时段与并发guard
- 创建后超时unknown查询、旁路失败单独恢复、撤销复制

详细命令和适用边界见[测试说明](../TESTING.md)及[模型评估](../MODEL_EVALUATION.md)。企业接口始终为本地Stub；未实际运行的环境和未取得的真实票面不计为通过。
