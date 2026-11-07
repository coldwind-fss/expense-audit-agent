# 项目入口

这是循证智能报销审核系统的当前完整源码。业务、运行与架构说明统一从以下文档进入：

1. [README](README.md)：定位、功能、流程与快速运行。
2. [产品基线](docs/PRODUCT_BASELINE.md)、[业务基线](docs/BUSINESS_BASELINE.md)：角色、入口、金额/票据/审批/日期规则。
3. [业务场景](docs/BUSINESS_SCENARIOS.md)：场景与边界。
4. [技术基线](docs/TECHNICAL_BASELINE.md)、[Agent技术设计](docs/AGENT_TECHNICAL_DESIGN.md)：模块、数据、循环、工具与恢复。
5. [运行](docs/RUNNING.md)、[测试](docs/TESTING.md)、[源码导读](docs/CODE_GUIDE.md)。

## 固定约束

- Vue 3/TypeScript、Python3.13/FastAPI、PostgreSQL、LangChain/LangGraph。
- 一套Agent执行基础、三任务；人工建行/归属/真实用途/最终确认。
- 按报销归属人自动获取审批；单号查找补充，差旅逐行确认。
- 总额独立人工填写，识别/回填/导入不覆盖；Decimal容差0.01；修改后旧报告失效。
- 本人、普通代报、管理员代发主体分别推导；社保仅默认，税票逐张抬头核验。
- 模型provider/fixture来源分离，企业接口当前本地Stub。
- 模型Key、会话、账户Key、数据库和原件只在忽略目录；普通测试不产生付费或真实企业写入。

当前数据库版本0004，规则reimbursement-v1-002，Agent profile reimbursement.v2.1。外部真实审批/付款/通知/台账与公开托管不因本仓库源码存在而视为已接入。
