# 测试与验证

## 验证层级

| 编号 | 层级/入口 | 证明范围 |
| --- | --- | --- |
| B01 | test_foundation.py | HTTP就绪、PG检查点断连重连及跨进程start/resume/replay |
| B02 | test_workflows.py / test_boundaries.py | 五入口、身份、账户、草稿修订、权限与管理员受控提交 |
| B03 | 材料/Excel用例 | 原件身份、分配/移除、格式、PDF分页、嵌图锚点及导入来源 |
| B04 | 图/队列边界用例 | 人工等待、预算、无进展、结构失败、租约更替、旧结果及重复发布 |
| B05 | 金额/票据/日期用例 | Decimal/0.01、独立人工总额、少报、退款、未付款、抬头、逐行日期及旧报告失效 |
| B06 | 提交/排期用例 | 冻结快照、幂等、月度/跨年/时段/三分钟guard、unknown查询和旁路恢复 |
| B07 | 管理/台账/反馈用例 | 受控修复、13列、audit/sync/冲突回滚、邀请/答卷/token轮换 |
| B08 | test_provider.py | 超时/限流/结构失败、授权图片、模式隔离；不产生真实调用 |
| U01 | client.test.ts | Cookie/CSRF、稳定命令键、金额字符串、409及断网不伪成功 |
| E01 | frontend/tests/e2e | 人工填报/分配/建议/审核/提交、独立总额、审批获取、五入口/管理/反馈与窄屏 |
| L01 | 显式真实评估/浏览器 | 实际provider、图像和业务流程；与fixture证据分开 |

本机有40项后端全量、3项前端单测、11项fixture浏览器通过记录；独立总额及Excel不生成总额有定向复测。真实模型专项也已通过，见[模型评估](MODEL_EVALUATION.md)。这些结果不代表真实企业接口或所有真实票面已验收。

## 后端离线检查

原生启动脚本会创建独立测试库，以下在独立终端运行：

```powershell
cd backend
uv sync --locked
$env:DATABASE_URL = 'postgresql+psycopg://reimbursement:development@127.0.0.1:15432/reimbursement_v2_test'
$env:CHECKPOINT_URL = 'postgresql://reimbursement:development@127.0.0.1:15432/reimbursement_v2_test?options=-csearch_path%3Dagent_runtime'
$env:FILE_ROOT = '../data/v2/test-files'
uv run alembic upgrade head
uv run python -m reimbursement.bootstrap
uv run ruff check src tests scripts
uv run mypy src/reimbursement
uv run alembic check
uv run pytest -q
uv run python scripts/export_openapi.py
```

conftest强制fixture和空模型Key，并拒绝非reimbursement_v2_test库。测试结束后关闭测试终端，避免启动应用时使用测试环境。

## 前端与契约

```powershell
cd frontend
npm ci
npm run types
npm run build
npm test
```

类型生成后，backend/openapi.json与frontend/src/api/generated.ts应保持一致。CI执行相同生成并核对差异。

## 浏览器

先启动fixture模式的API/Worker和构建页面，默认使用已安装的Microsoft Edge：

```powershell
cd frontend
$env:APP_URL = 'http://127.0.0.1:18880'
npm run test:e2e
```

三个spec文件共11项：完整员工填报、管理员页面、自动获取审批、独立总额负例/修正、错抬头修正、五种业务/主体路径及反馈闭环。部分扩展场景用API准备数据，主员工用例操作完整产品页面；不把所有API准备都称为纯手工端到端。

独立总额用例验证人工100/明细88无法提交，修改为88使旧报告失效，重审后创建SIM；还检查390px下金额字段可见且无全页横向溢出。

真实provider下运行浏览器会产生实际模型请求，只在明确需要时显式选择关键用例。pytest和云端CI不会自动产生付费调用。

## CI与局限

.github/workflows/ci.yml在GitHub使用真实PG服务运行后端、前端类型/构建/单测和契约一致性检查；它不接企业服务，也不把浏览器或真实模型结果伪装成云端检查。

规则和图测试不能证明真实视觉准确率；模型标签集不能证明财务上线；原生PG/NGINX运行不能证明Docker构建/卷重启。场景表保留未提供真实图片和待定义政策，而非按设计覆盖全标Passed。
