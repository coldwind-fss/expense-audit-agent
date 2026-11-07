# WP-00 · 基础工程与持久运行

状态：已实施。依赖：无。上位：[产品基线](../PRODUCT_BASELINE.md)、[业务基线](../BUSINESS_BASELINE.md)、[技术基线](../TECHNICAL_BASELINE.md)。

## 目的与范围

建立Vue/TS与FastAPI包、PostgreSQL迁移、图检查点、错误契约、锁依赖和启动配置。

## 实现入口

- backend/pyproject.toml、uv.lock、migrations、db.py、bootstrap.py
- frontend/package.json、锁文件、api/generated.ts
- infra启动/停止/静态服务、Compose、Dockerfile、CI

## 数据、接口与业务约束

- GET /health/live与/health/ready返回存活及数据库/schema/mode
- app业务与agent_runtime检查点分开；0001—0004迁移前置于应用
- 精确依赖安装及契约生成可复核

## 验收依据

- PG迁移/check与检查点跨连接、跨进程恢复
- 后端lint/类型与前端类型/构建/单测
- 原生启动/停止/保留数据；Docker配置未在本机实跑

详细命令和适用边界见[测试说明](../TESTING.md)及[模型评估](../MODEL_EVALUATION.md)。企业接口始终为本地Stub；未实际运行的环境和未取得的真实票面不计为通过。
