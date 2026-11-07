# API 与工程约定

## 公共协议

基础路径`/api/v1`，JSON为UTF-8/snake_case。UUID只作为资源标识，不代表权限。金额使用两位小数字符串，业务日期为YYYY-MM-DD，时间戳带时区。单资源直接返回资源，列表含items，分页列表另有next_cursor/has_more。

修改请求使用会话Cookie、X-CSRF-Token；Origin受配置约束。服务端生成X-Request-ID，错误包含error.code、message、request_id、retryable、details，不返回Key或账户全文。409表示修订/状态冲突，422表示输入或业务条件不满足，401/403区分认证与授权。

数据库/命令完整schema以[OpenAPI](../backend/openapi.json)为准，前端类型由其生成。下表只作导航，不维护另一套端点含义。

## 路由导航

| 资源 | 主要端点 |
| --- | --- |
| 体验身份 | POST /experience/sessions、POST /experience/persona、GET /me、/capabilities |
| 目录 | GET /catalogs、/employees、/related-approvals、/related-approvals/resolve |
| 草稿 | POST/GET /claims、GET/PATCH /claims/{id} |
| 明细 | POST /claims/{id}/lines、PATCH/DELETE .../lines/{line_id}、POST .../copy |
| 账户 | GET/POST /recipient-accounts、PATCH/DELETE /recipient-accounts/{id} |
| 材料 | POST /claims/{id}/materials、GET/PATCH/DELETE /materials/{id}、POST .../prepare、GET .../preview |
| 合成样本 | GET /sample-materials、/sample-materials/{key}、/sample-material-manifest |
| 分配/更正 | PUT /claims/{id}/bindings、POST /materials/{id}/decisions |
| 导入 | POST /claims/{id}/imports、GET /import-jobs/{id} |
| Agent | POST /materials/{id}/extract、/claims/{id}/suggestions、/claims/{id}/reviews |
| 执行 | GET /claims/{id}/runs、GET /agent-runs/{id}（含steps）、POST .../responses、.../cancel |
| 建议 | GET /suggestion-batches/{id}、POST .../apply、.../undo |
| 报告 | GET /review-reports/{id} |
| 提交 | POST /claims/{id}/submissions、GET /submissions、GET /submissions/{id}、POST .../cancel-and-copy |
| 管理 | /admin/cases、.../manual、.../{id}/repair、.../{id}/submit、/admin/jobs、.../{id}/actions、/admin/events |
| 台账 | /ledger/events、/ledger/entries、POST .../events/{id}/sync、.../entries/{id}/rollback |
| 模拟审批事件 | POST /submissions/{id}/simulated-event |
| 反馈 | /feedback/invitations、.../{id}/retry、/feedback/resolve、/feedback/answers、/feedback/export |
| 健康 | GET /health/live、/health/ready |

## 修订和命令幂等

草稿、行、分配和相关命令携带expected_revision。命令Idempotency-Key由客户端生成并在明确重试时保持；服务端保存操作/请求指纹与结果，相同键不同内容不视为同一命令。

Agent任务另按输入签名复用合法结果。最终提交同时受单报销提交唯一约束保护，不能换键重复创建。普通客户端不能指定workspace、角色或真实OA发起人覆盖服务端上下文。

管理员编辑他人申报使用URL编码的X-Action-Reason；受控修复/代发另有原因DTO，所有动作走服务端权限和业务校验。

## 独立人工总额

PATCH /claims/{id}的total_amount是人工声明，草稿可暂空，最终必须正数且与明细和相差不超过0.01。total_auto只保留历史读兼容，写入仅允许false，true返回422；识别/导入/建议不写total_amount。

报告summary.declared_amount是人工总额，line_total是明细合计。无论之前报告是否通过，修改金额后旧报告失效，最终提交再校验。

## 典型请求

```http
PATCH /api/v1/claims/<claim_id>
X-CSRF-Token: <session csrf>
Content-Type: application/json

{"expected_revision": 3, "total_amount": "88.00"}
```

```http
POST /api/v1/claims/<claim_id>/reviews
X-CSRF-Token: <session csrf>
Idempotency-Key: <stable command key>
Content-Type: application/json

{"expected_revision": 4}
```

202返回run_id、task_kind、status、input_revision、execution_mode、poll_after_ms。通过GET /agent-runs/{id}查询输出引用，再读取/review-reports/{id}的valid、checks、summary、can_submit。

建议采纳使用selected_indices、replace_manual与expected_revision；受保护字段未确认替换则409。撤回只修改仍属于该批次的字段。

人工响应使用question_id、expected_revision和受限的manual_amount/explanation；领域变更返回新run_id，纯阅读提示可恢复同run。不能上传任意工具、提示或endpoint。

提交使用expected_revision、review_id和Idempotency-Key，202表示持久命令被接受。轮询结果中adapter_mode=stub、external_instance_id=null、simulated_reference=SIM-…，只代表模拟创建。

## 文件与秘密

上传采用multipart与服务端格式/容量校验；预览经过workspace和申报权限。前端不取得存储目录、模型Key或账户完整值；邀请凭证放在URL fragment，解析后从浏览器地址清除。

接口变更同步Pydantic、OpenAPI、生成TS和相关测试；普通测试使用隔离库与fixture，不连接真实企业。
