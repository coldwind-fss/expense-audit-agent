# 运行指南

## 1. 运行模式

- fixture：默认，无Key。只对登记合成原件返回已标记事实，未知新图明确未识别；执行真实图、工具和业务事务。
- provider：服务端真实多模态模型，图片来自当前授权材料页；来源和缓存与fixture隔离。
- disabled：需要模型的任务明确不可用，其他页面和已保存业务仍可读取。

企业接口均为本地Stub，不需要钉钉或原公司的凭据。

## 2. Windows 原生

环境：PowerShell7、Git、Node24和uv。已验证组合为Node24.18、Python3.13、PG18.6，具体Python/前端依赖以锁文件为准。首次运行需联网获取依赖及官方便携PostgreSQL/NGINX。

```powershell
git clone https://github.com/coldwind-fss/expense-audit-agent.git
cd expense-audit-agent
./infra/start-local.ps1 -InstallPostgres
./infra/start-static.ps1
```

| 服务 | 本机地址 |
| --- | --- |
| NGINX构建页面 | http://127.0.0.1:18880/ |
| Vite开发页面 | http://127.0.0.1:5173/ |
| API文档 | http://127.0.0.1:18881/docs |
| API就绪 | http://127.0.0.1:18881/api/v1/health/ready |
| PostgreSQL | 127.0.0.1:15432 |

脚本安装锁依赖、准备独立PG集群、创建应用/测试库、迁移0001—0004、初始化图检查点，再启动API/Worker/Vite。静态脚本构建前端并启动NGINX。

运行数据位于data/v2、工具位于.tools，均不进Git。Windows使用ASCII junction规避PG中文路径问题；链接归属会核对，不覆盖其他工作区。端口已被其他程序占用会停止启动并说明原因，不关闭无关服务。

```powershell
# 已有依赖时再次启动
./infra/start-local.ps1
./infra/start-static.ps1
# 只停止本项目记录的应用和静态服务，PG/数据保留
./infra/stop-local.ps1
```

同机已有另一份原生实例时，先确认工作区和端口；脚本不会接管另一工作区的运行链接。无需重置数据或删除数据库来正常启动。

## 3. 一条可操作的业务

1. 新建日常有票报销，在基本信息独立填写88.00元。
2. 查看自动获取的审批；本例非条件审批费用，可不关联。选公司A与一个合成收款账户。
3. 人工建立工作餐费用行，填写真实用途和“日常运营”项目。
4. 在材料步骤加入88元餐饮付款和88元餐饮发票合成样本，等待识别。
5. 人工把两份材料归入同一费用行，生成并确认日期/票种等建议。
6. 审核显示人工总额88、明细88、差额0，符合其他规则后人工提交。
7. 历史显示SIM模拟创建。无票入口仍保留后续人工审批去向。

差旅例：先独立申报141元，材料使用原支付154减完成退款10.50的付款凭证和141元铁路票；人工行金额141，逐行关联出差审批。系统允许少报并提示，而非强制所有金额相同。

## 4. 真实模型配置

```powershell
Copy-Item backend/.env.example backend/.env
```

在本机.env设置MODEL_MODE=provider、MODEL_PROVIDER=deepseek、MODEL_NAME=deepseek-flash、MODEL_BASE_URL=https://api.deepseek.com和MODEL_API_KEY。密钥不要写进源码、截图或聊天。服务端还可设置超时、输出长度和图像预算，浏览器不能上传任意模型endpoint/Key。

停止并重新运行API/Worker，顶部应显示真实模型模式。已有fixture事实不能当真实识别结果，需要相应材料重新识别。无Key时保持fixture即可完整体验合成流程。

## 5. Docker Compose

```powershell
docker compose -f infra/compose.yaml up --build
```

默认fixture，启动PG18、一次性migrate、API、Worker、Web，入口18880。PG不映射公网端口，业务文件在共享卷。常规停止保留卷：

```powershell
docker compose -f infra/compose.yaml down
```

需要真实模型时，使用本机backend/.env提供模型配置，并添加示例override：

```powershell
docker compose --env-file backend/.env -f infra/compose.yaml -f infra/compose.provider.example.yaml up --build
```

override只补API/Worker的模型环境，继承基础数据库与文件配置；不要将真实Key写进YAML。当前本机验收未安装Docker，容器配置未实跑，不能把原生检查当容器通过。

## 6. 测试与模型评估

离线测试、浏览器服务和模型评估使用不同环境/库。先按[测试说明](TESTING.md)初始化reimbursement_v2_test；真实评估另用reimbursement_v2_eval。不要将测试终端环境传入应用启动终端。

## 7. 状态和数据

- /health/ready核对schema、模型模式与数据库/检查点可用性，不代表真实OA连接。
- data/v2/local-processes.json只记录本工作区启动进程；api/worker/web日志在相同忽略目录。
- 邀请和账户均为合成体验数据；应用重启不清库，避免通过重复提交或清理数据诊断unknown任务。
- total_auto仅保留历史读兼容；自动总额旧草稿经迁移后需要独立填写，新提交不使用自动总额。
