# WP-04 · 整单审核与人工修正

状态：已实施。依赖：WP-03。上位：[产品基线](../PRODUCT_BASELINE.md)、[业务基线](../BUSINESS_BASELINE.md)、[技术基线](../TECHNICAL_BASELINE.md)。

## 目的与范围

将结构化材料事实与当前申报组合，通过必检规则和受控模型补证生成审核报告。

## 实现入口

- rules.py、agent_service.py、agent_graph.py、api_agents.py
- AgentPanel.vue、ClaimEditor.vue

## 数据、接口与业务约束

- POST /claims/{id}/reviews与GET /review-reports/{id}
- Required checks由程序/图保证，不能仅让模型返回pass
- R-09核对独立正数总额/明细差额，其他规则分别核对付款/税票/抬头/审批/日期
- 修改相关输入使报告失效，无通用人工强制通过

## 验收依据

- 0.01边界、少报、退款/未付款、票据与抬头负例
- 差旅逐行/起止日/开票日/unknown及人工说明
- 人工100对明细88阻断，改88使旧报告失效，重审后可提交

详细命令和适用边界见[测试说明](../TESTING.md)及[模型评估](../MODEL_EVALUATION.md)。企业接口始终为本地Stub；未实际运行的环境和未取得的真实票面不计为通过。
