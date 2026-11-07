# WP-07 · 集成验证与运行交付

状态：已实施。依赖：WP-01—WP-06。上位：[产品基线](../PRODUCT_BASELINE.md)、[业务基线](../BUSINESS_BASELINE.md)、[技术基线](../TECHNICAL_BASELINE.md)。

## 目的与范围

以真实业务链路、故障和静态边界核对系统，提供源码、契约、锁依赖和运行文档。

## 实现入口

- backend/tests、frontend/tests/e2e、client.test.ts
- infra、.github/workflows/ci.yml、docs

## 数据、接口与业务约束

- 验证层级分开：规则、PG/API、图/模式、浏览器、真实模型、外部集成
- 场景逐项说明实现/模拟/待决/真实票面未覆盖，不用截图或源码字串充当功能测试
- 部署核对服务、Worker、schema和构建资源；不包含自动清库步骤

## 验收依据

- 本机后端40、前端3、fixture浏览器11有通过证据
- 窄屏、自动审批获取、独立总额修正、五入口/代报/管理/反馈
- 原生运行已测，Docker配置未实跑；真实企业保持未接

详细命令和适用边界见[测试说明](../TESTING.md)及[模型评估](../MODEL_EVALUATION.md)。企业接口始终为本地Stub；未实际运行的环境和未取得的真实票面不计为通过。
