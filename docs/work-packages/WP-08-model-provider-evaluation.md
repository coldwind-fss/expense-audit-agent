# WP-08 · 真实模型适配与评估

状态：已实施。依赖：WP-03—WP-04。上位：[产品基线](../PRODUCT_BASELINE.md)、[业务基线](../BUSINESS_BASELINE.md)、[技术基线](../TECHNICAL_BASELINE.md)。

## 目的与范围

接入真实多模态模型，验证授权图像、JSON结构、工具与任务闭环并记录评估范围。

## 实现入口

- model_gateway.py、agent_graph.py、test_provider.py
- scripts/evaluate_models.py、docs/evaluation/summary.json

## 数据、接口与业务约束

- 服务端配置provider/model/HTTPS endpoint/SecretStr，不从浏览器取得任意Key/URL
- SDK自动重试关闭；失败有界且不降级fixture，记录实际usage
- --live使用独立_eval库，普通pytest/CI清空Key
- 固定数据/模型/图/规则版本，分列材料理解与业务错误

## 验收依据

- 10份合成材料、角色差异与8审核案例有真实调用记录
- 当前独立总额provider浏览器负例→修正→提交通过
- 价格响应缺实际账单只记录token；不宣称真实票据全覆盖

详细命令和适用边界见[测试说明](../TESTING.md)及[模型评估](../MODEL_EVALUATION.md)。企业接口始终为本地Stub；未实际运行的环境和未取得的真实票面不计为通过。
