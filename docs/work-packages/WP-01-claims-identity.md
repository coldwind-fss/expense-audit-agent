# WP-01 · 身份、自动审批获取与人工申报

状态：已实施。依赖：WP-00。上位：[产品基线](../PRODUCT_BASELINE.md)、[业务基线](../BUSINESS_BASELINE.md)、[技术基线](../TECHNICAL_BASELINE.md)。

## 目的与范围

建立五入口、主体路由、独立人工总额、目录、明细、账户与服务端草稿。

## 实现入口

- api_claims.py、security.py、schemas.py、services.py
- ClaimEditor.vue、ClaimsPage.vue、ApprovalPicker.vue

## 数据、接口与业务约束

- 当前会话限定workspace与persona，不采信客户端角色
- GET /related-approvals按归属人自动读取；resolve区分业务号和实例ID
- total_amount由员工填写，total_auto只接受false；初始空、草稿可缺、提交必须正数
- 行复制不复制附件，账户返回掩码；修改携带expected_revision

## 验收依据

- 五入口、本人/代报/管理员、跨workspace与409
- 自动列表/关联恢复/单号补充/切归属/失败重试的浏览器流程
- 总额不被识别/分配/导入覆盖；新旧草稿兼容处理

详细命令和适用边界见[测试说明](../TESTING.md)及[模型评估](../MODEL_EVALUATION.md)。企业接口始终为本地Stub；未实际运行的环境和未取得的真实票面不计为通过。
