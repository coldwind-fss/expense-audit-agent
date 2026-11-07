<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, nextTick, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import Decimal from "decimal.js";
import {
  ArrowLeft,
  Plus,
  CopyDocument,
  Delete,
  Check,
  Upload,
} from "@element-plus/icons-vue";
import {
  api,
  APIError,
  setActionReason,
  currency,
  label,
  type Claim,
  type Line,
  type Run,
  type RelatedApproval,
} from "../api/client";
import { useSession } from "../stores/session";
import MaterialWorkbench from "../components/MaterialWorkbench.vue";
import AgentPanel from "../components/AgentPanel.vue";
import ApprovalPicker from "../components/ApprovalPicker.vue";
const route = useRoute(),
  router = useRouter(),
  session = useSession(),
  claim = ref<Claim>(),
  step = ref(0),
  busy = ref(false),
  error = ref(""),
  runs = ref<Run[]>([]),
  approvals = ref<RelatedApproval[]>([]),
  accounts = ref<any[]>([]),
  people = ref<any[]>([]),
  accountDialog = ref(false),
  accountEdit = ref(""),
  accountForm = ref({ label: "", kind: "bank", value: "" }),
  panel = ref<InstanceType<typeof AgentPanel>>(),
  importInput = ref<HTMLInputElement>(),
  importJob = ref<any>(),
  timer = ref<ReturnType<typeof setInterval>>(),
  saveError = ref(false);
const approvalsLoading = ref(false),
  approvalsError = ref(""),
  resolvingApproval = ref(false),
  approvalLookupError = ref("");
async function loadApprovals() {
  const subjectId = claim.value!.subject_id;
  approvalsLoading.value = true;
  approvalsError.value = "";
  approvalLookupError.value = "";
  approvals.value = [];
  try {
    const result = await api<{ items: RelatedApproval[] }>(
      "/related-approvals?employee_id=" + subjectId,
      "GET",
      undefined,
      { silent: true },
    );
    if (claim.value?.subject_id === subjectId) approvals.value = result.items;
  } catch {
    if (claim.value?.subject_id === subjectId)
      approvalsError.value = "审批记录获取失败";
  } finally {
    if (claim.value?.subject_id === subjectId) approvalsLoading.value = false;
  }
}
async function resolveApproval(businessNumber: string) {
  resolvingApproval.value = true;
  approvalLookupError.value = "";
  try {
    const result = await api<RelatedApproval>(
      "/related-approvals/resolve?business_id=" +
        encodeURIComponent(businessNumber) +
        "&employee_id=" +
        claim.value!.subject_id,
      "GET",
      undefined,
      { silent: true },
    );
    await patch(
      "related_ids",
      Array.from(new Set([...claim.value!.related_ids, result.id])),
    );
    if (!approvals.value.some((a) => a.id === result.id))
      approvals.value.push(result);
    ElMessage.success("业务号已解析并加入关联");
  } catch (e) {
    approvalLookupError.value = (e as Error).message;
  } finally {
    resolvingApproval.value = false;
  }
}
const adminReason = ref("");
const declaredTotalInput = ref("");
watch(
  () => claim.value?.total_amount,
  (value) => {
    declaredTotalInput.value = value || "";
  },
);
const lineTotal = computed(() => {
  try {
    return (
      claim.value?.lines
        .reduce((sum, line) => sum.plus(line.amount || "0"), new Decimal(0))
        .toFixed(2) || "0.00"
    );
  } catch {
    return null;
  } // A partly typed decimal is not a saved monetary value.
});
const totalDifference = computed(() =>
  claim.value?.total_amount && lineTotal.value !== null
    ? new Decimal(claim.value.total_amount).minus(lineTotal.value).toFixed(2)
    : null,
);
const totalMatches = computed(
  () =>
    !!claim.value?.total_amount &&
    totalDifference.value !== null &&
    !claim.value.total_auto &&
    new Decimal(claim.value.total_amount).gt(0) &&
    new Decimal(totalDifference.value || "0").abs().lte("0.01"),
);
async function editTotal() {
  step.value = 0;
  await nextTick();
  document.getElementById("claim-declared-total")?.focus();
}
const needsReason = computed(
  () => !!claim.value && claim.value.actor_id !== session.me?.actor.id,
);
watch(adminReason, setActionReason);
const id = String(route.params.id),
  steps = ["基本信息", "费用明细", "上传与分配", "识别回填", "审核与提交"],
  readOnly = computed(
    () =>
      claim.value?.status !== "draft" ||
      (needsReason.value && adminReason.value.trim().length < 4),
  ),
  workflowLabel = computed(
    () =>
      session.catalog?.workflows.find(
        (w) => w.key === claim.value?.workflow_key,
      )?.label || claim.value?.workflow_key,
  );
let retrySave: (() => Promise<void>) | undefined;
async function refresh() {
  const result = await api<Claim>("/claims/" + id);
  claim.value = result;
  runs.value = (await api("/claims/" + id + "/runs")).items;
  await nextTick();
  await panel.value?.refresh();
}
async function loadCatalogs() {
  await loadApprovals();
  accounts.value = (await api("/recipient-accounts")).items;
  people.value = (await api("/employees")).items;
}
async function mutate(operation: () => Promise<Claim>) {
  busy.value = true;
  error.value = "";
  try {
    claim.value = await operation();
    saveError.value = false;
    retrySave = undefined;
  } catch (e) {
    saveError.value = true;
    error.value = (e as Error).message;
    if (e instanceof APIError && e.code === "REVISION_CONFLICT")
      retrySave = async () => {
        const latest = await api<Claim>("/claims/" + id);
        claim.value!.revision = latest.revision;
        await mutate(operation);
      };
    throw e;
  } finally {
    busy.value = false;
  }
}
async function patch(field: string, value: unknown) {
  await mutate(() =>
    api<Claim>("/claims/" + id, "PATCH", {
      expected_revision: claim.value!.revision,
      [field]: value,
    }),
  );
  if (["subject_id", "route_mode"].includes(field)) await loadCatalogs();
}
async function patchLine(line: Line, field: string, value: unknown) {
  await mutate(() =>
    api<Claim>("/claims/" + id + "/lines/" + line.id, "PATCH", {
      expected_revision: claim.value!.revision,
      [field]: value || null,
    }),
  );
}
async function addLine() {
  await mutate(() =>
    api<Claim>("/claims/" + id + "/lines", "POST", {
      expected_revision: claim.value!.revision,
    }),
  );
}
async function copyLine(line: Line) {
  await mutate(() =>
    api<Claim>("/claims/" + id + "/lines/" + line.id + "/copy", "POST", {
      expected_revision: claim.value!.revision,
    }),
  );
}
async function deleteLine(line: Line) {
  await ElMessageBox.confirm(
    "删除此明细后，其附件将回到未分配状态。",
    "删除费用明细",
    { type: "warning" },
  );
  await mutate(() =>
    api<Claim>(
      "/claims/" +
        id +
        "/lines/" +
        line.id +
        "?expected_revision=" +
        claim.value!.revision,
      "DELETE",
    ),
  );
}
async function nextStep() {
  if (saveError.value) {
    ElMessage.warning("请先处理未保存的更改");
    return;
  }
  step.value = Math.min(4, step.value + 1);
  await refresh();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
async function saveAccount() {
  const path =
    "/recipient-accounts" + (accountEdit.value ? "/" + accountEdit.value : "");
  await api(path, accountEdit.value ? "PATCH" : "POST", accountForm.value);
  await loadCatalogs();
  accountDialog.value = false;
  ElMessage.success("账户已保存");
}
function openAccount(account?: any) {
  accountEdit.value = account?.id || "";
  accountForm.value = {
    label: account?.label || "",
    kind: account?.kind || "bank",
    value: "",
  };
  accountDialog.value = true;
}
async function removeAccount(account: any) {
  await ElMessageBox.confirm(
    "确认删除此账户？被报销引用的账户需先更换。",
    "删除账户",
  );
  await api("/recipient-accounts/" + account.id, "DELETE");
  await loadCatalogs();
}
async function importFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  busy.value = true;
  try {
    const form = new FormData();
    form.append("file", file);
    form.append("expected_revision", String(claim.value!.revision));
    const result = await api("/claims/" + id + "/imports", "POST", form);
    importJob.value = { id: result.job_id, status: result.status };
    await refresh();
    ElMessage.success("导入任务已加入队列");
  } finally {
    busy.value = false;
    (event.target as HTMLInputElement).value = "";
  }
}
async function poll() {
  if (
    busy.value ||
    saveError.value ||
    ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName || "") ||
    document.querySelector('.el-select__popper:not([style*="display: none"])')
  )
    return;
  try {
    if (importJob.value) {
      importJob.value = await api("/import-jobs/" + importJob.value.id);
      if (
        importJob.value.status === "done" ||
        importJob.value.status === "failed"
      )
        await refresh();
    }
    const latestRuns: Run[] = (
      await api("/claims/" + id + "/runs", "GET", undefined, { silent: true })
    ).items;
    const changed =
      JSON.stringify(latestRuns.map((r) => [r.id, r.status])) !==
      JSON.stringify(runs.value.map((r) => [r.id, r.status]));
    runs.value = latestRuns;
    if (changed) await refresh();
  } catch {
    /* A transient poll does not erase the current form. Manual actions surface errors. */
  }
}
onMounted(async () => {
  try {
    await refresh();
    await loadCatalogs();
    timer.value = setInterval(poll, 1800);
  } catch (e) {
    error.value = (e as Error).message;
  }
});
onUnmounted(() => {
  clearInterval(timer.value);
  setActionReason("");
});
function submitted() {
  router.push("/history");
}
function source(line: Line, field: string) {
  const kind = line.sources[field]?.kind;
  return (
    (
      {
        agent: "AI 建议",
        system: "材料同步",
        manual: "人工填写",
        import: "导入值",
      } as Record<string, string>
    )[kind] || ""
  );
}
</script>
<template>
  <RouterLink to="/" class="back-link"
    ><el-icon><ArrowLeft /></el-icon>返回工作台</RouterLink
  >
  <div v-if="error" class="readonly-note">
    {{ error
    }}<el-button v-if="retrySave" link type="primary" @click="retrySave"
      >保留本次输入并重试保存</el-button
    ><el-button v-else link type="primary" @click="refresh">刷新</el-button>
  </div>
  <template v-if="claim">
    <div class="page-heading">
      <div>
        <div class="eyebrow">{{ workflowLabel }}</div>
        <h1>{{ claim.title }}</h1>
        <p>
          由 {{ claim.actor_name }} 填写 · 报销归属 {{ claim.subject_name }} ·
          OA 发起 {{ claim.originator_name }}
        </p>
      </div>
      <span class="save-state"
        ><span class="status-dot"></span
        >{{
          busy
            ? "保存中…"
            : saveError
              ? "有未保存更改"
              : readOnly
                ? label(claim.status)
                : "已保存 · 版本 " + claim.revision
        }}</span
      >
    </div>
    <div v-if="needsReason" class="notice">
      管理员协助修改其他操作人的申报，请先填写处理原因。<el-input
        v-model="adminReason"
        placeholder="至少4字符的明确处理原因"
        maxlength="1000"
        style="margin-top: 10px"
      />
    </div>
    <div v-if="claim.status !== 'draft'" class="readonly-note">
      本次申报已锁定，以下为保存内容。<RouterLink
        to="/history"
        style="color: #3b82f6; margin-left: 10px"
        >查看提交与模拟 OA 记录 →</RouterLink
      >
    </div>
    <div class="steps">
      <button
        v-for="(s, index) in steps"
        :key="s"
        class="step-button"
        :class="{ current: step === index }"
        :disabled="busy || saveError"
        @click="
          step = index;
          nextTick(() => panel?.refresh());
        "
      >
        <span class="number"
          ><el-icon v-if="index < step"><Check /></el-icon
          ><template v-else>{{ index + 1 }}</template></span
        >{{ s }}
      </button>
    </div>
    <div class="editor-grid">
      <div class="editor-main">
        <section class="panel">
          <div class="panel-heading">
            <div>
              <h2>
                {{ String(step + 1).padStart(2, "0") }}
                <span style="color: #d6deea; margin: 0 9px">/</span
                >{{ steps[step] }}
              </h2>
              <p>
                {{
                  [
                    "确认身份、前置业务审批和收款信息",
                    "真实用途由您填写，费用结构由您决定",
                    "逐份识别材料，再手动确认每份材料的归属",
                    "根据已分配材料，选择需要应用的字段建议",
                    "核对审核依据，处理具体问题后确认提交",
                  ][step]
                }}
              </p>
            </div>
            <div v-if="step === 1 && !readOnly" class="toolbar">
              <el-button
                size="small"
                :icon="Upload"
                :disabled="busy"
                @click="importInput?.click()"
                >Excel 导入</el-button
              ><el-button
                size="small"
                :icon="Plus"
                :disabled="busy"
                @click="addLine"
                >添加明细</el-button
              ><input
                ref="importInput"
                hidden
                type="file"
                accept=".xlsx"
                @change="importFile"
              />
            </div>
          </div>
          <div class="panel-body">
            <el-form
              v-if="step === 0"
              label-position="top"
              :disabled="readOnly || busy"
              class="two-col"
              ><el-form-item label="报销标题" class="full-width"
                ><el-input
                  v-model="claim.title"
                  maxlength="200"
                  @change="(v: string) => patch('title', v)" /></el-form-item
              ><el-form-item
                label="本次申报总金额（元）"
                required
                class="full-width"
              >
                <el-input
                  id="claim-declared-total"
                  aria-label="本次申报总金额（元）"
                  v-model="declaredTotalInput"
                  inputmode="decimal"
                  placeholder="请独立填写本次实际要报销的总金额"
                  style="max-width: 360px"
                  @change="(v: string) => patch('total_amount', v)"
                />
                <p class="field-help">
                  请按您实际要报销的金额独立填写。识别结果和明细合计不会自动填入或覆盖此项；提交前将进行核对。
                </p>
              </el-form-item>
              <el-form-item label="报销入口"
                ><el-select
                  v-model="claim.workflow_key"
                  @change="(v: string) => patch('workflow_key', v)"
                  ><el-option
                    v-for="w in session.catalog?.workflows"
                    :key="w.key"
                    :label="w.label"
                    :value="w.key" /></el-select></el-form-item
              ><el-form-item label="填报身份"
                ><el-select
                  v-model="claim.route_mode"
                  @change="(v: string) => patch('route_mode', v)"
                  ><el-option label="本人报销" value="self" /><el-option
                    v-if="session.me?.actor.can_on_behalf"
                    label="代他人填报"
                    value="on_behalf" /><el-option
                    v-if="claim.route_mode === 'admin_originator'"
                    label="管理员协助代发"
                    value="admin_originator" /></el-select></el-form-item
              ><el-form-item
                v-if="claim.route_mode !== 'self'"
                label="报销归属人"
                ><el-select
                  v-model="claim.subject_id"
                  @change="(v: string) => patch('subject_id', v)"
                  ><el-option
                    v-for="p in people"
                    :key="p.id"
                    :label="p.name"
                    :value="p.id" /></el-select></el-form-item
              ><el-form-item label="归属部门"
                ><el-select :model-value="claim.department_id" disabled
                  ><el-option
                    v-for="d in session.catalog?.departments"
                    :key="d.id"
                    :label="d.name"
                    :value="d.id" /></el-select
              ></el-form-item>
              <div class="form-divider full-width"></div>
              <el-form-item class="full-width">
                <ApprovalPicker
                  :items="approvals"
                  :selected="claim.related_ids"
                  :subject-id="claim.subject_id"
                  :subject-name="claim.subject_name"
                  :loading="approvalsLoading"
                  :error="approvalsError"
                  :readonly="readOnly"
                  :busy="busy"
                  :resolving="resolvingApproval"
                  :lookup-error="approvalLookupError"
                  @refresh="loadApprovals"
                  @resolve="resolveApproval"
                  @change="(v: string[]) => patch('related_ids', v)"
                />
              </el-form-item>
              <div class="form-divider full-width"></div>
              <el-form-item label="付款公司"
                ><el-select
                  v-model="claim.company_id"
                  @change="(v: string) => patch('company_id', v)"
                  ><el-option
                    v-for="c in session.catalog?.companies"
                    :key="c.id"
                    :label="c.name"
                    :value="c.id"
                /></el-select>
                <p class="field-help">
                  社保主体仅作为默认建议，每张税务发票均按所选公司核验抬头。
                </p></el-form-item
              ><el-form-item label="收款账户"
                ><el-select
                  v-model="claim.account_id"
                  placeholder="请选择收款账户"
                  @change="(v: string) => patch('account_id', v)"
                  ><el-option
                    v-for="a in accounts"
                    :key="a.id"
                    :label="a.label + ' · ' + a.masked"
                    :value="a.id" /></el-select
                ><el-button
                  v-if="!readOnly"
                  link
                  type="primary"
                  size="small"
                  @click="openAccount()"
                  >＋ 管理收款账户</el-button
                ></el-form-item
              ><el-form-item label="补充说明（可选）" class="full-width"
                ><el-input
                  v-model="claim.remark"
                  type="textarea"
                  :rows="3"
                  maxlength="2000"
                  placeholder="说明与本次报销相关的实际情况"
                  @change="(v: string) => patch('remark', v)" /></el-form-item
            ></el-form>
            <template v-if="step === 1"
              ><div v-if="importJob" class="notice">
                Excel 导入：{{ label(importJob.status)
                }}<span v-if="importJob.error"> · {{ importJob.error }}</span>
                <div v-if="importJob.result">
                  已导入 {{ importJob.result.imported }} 行；<span
                    v-for="item in importJob.result.items.filter(
                      (i: any) => i.status === 'skipped',
                    )"
                    :key="item.row"
                    >第 {{ item.row }} 行：{{ item.reason }}；</span
                  >
                </div>
              </div>
              <div class="notice">
                导入模板列：申请事由、金额、付款截图、发票；可含费用日期、所属项目。图片需嵌入相应单元格；缺材料的行会单独列出。
              </div>
              <article
                v-for="(line, index) in claim.lines"
                :key="line.id"
                class="line-card"
              >
                <header class="line-card-header">
                  <strong>费用明细 {{ index + 1 }}</strong>
                  <div v-if="!readOnly" class="inline-buttons">
                    <el-button
                      link
                      :icon="CopyDocument"
                      :disabled="busy"
                      @click="copyLine(line)"
                      >复制字段</el-button
                    ><el-button
                      link
                      :icon="Delete"
                      :disabled="busy"
                      aria-label="删除明细"
                      @click="deleteLine(line)"
                    />
                  </div>
                </header>
                <el-form
                  class="two-col"
                  label-position="top"
                  :disabled="readOnly || busy"
                  ><el-form-item class="full-width"
                    ><template #label
                      >申请事由 / 真实用途
                      <span class="muted">*</span></template
                    ><el-input
                      v-model="line.reason"
                      placeholder="例如：客户会议工作餐，请填写真实业务用途"
                      maxlength="1000"
                      @change="
                        (v: string) => patchLine(line, 'reason', v)
                      " /></el-form-item
                  ><el-form-item
                    ><template #label
                      >费用日期
                      <span
                        v-if="source(line, 'business_date')"
                        class="source-tag"
                        >{{ source(line, "business_date") }}</span
                      ></template
                    ><el-date-picker
                      v-model="line.business_date"
                      type="date"
                      value-format="YYYY-MM-DD"
                      placeholder="实际费用日期"
                      style="width: 100%"
                      @change="
                        (v: string) => patchLine(line, 'business_date', v)
                      " /></el-form-item
                  ><el-form-item
                    ><template #label
                      >申报金额（元）
                      <span v-if="source(line, 'amount')" class="source-tag">{{
                        source(line, "amount")
                      }}</span></template
                    ><el-input
                      v-model="line.amount"
                      inputmode="decimal"
                      placeholder="可待材料识别后填入"
                      @change="
                        (v: string) => patchLine(line, 'amount', v)
                      " /></el-form-item
                  ><el-form-item
                    v-if="claim.workflow_key !== 'travel'"
                    label="所属项目"
                    ><el-select
                      v-model="line.project"
                      filterable
                      allow-create
                      default-first-option
                      placeholder="选择或填写项目"
                      @change="(v: string) => patchLine(line, 'project', v)"
                      ><el-option
                        v-for="p in session.catalog?.projects"
                        :key="p"
                        :value="p"
                        :label="p" /></el-select></el-form-item
                  ><el-form-item v-else label="费用类型"
                    ><el-select
                      v-model="line.expense_type"
                      placeholder="交通 / 住宿等"
                      @change="
                        (v: string) => patchLine(line, 'expense_type', v)
                      "
                      ><el-option
                        v-for="t in session.catalog?.expense_types"
                        :key="t"
                        :value="t"
                        :label="t" /></el-select></el-form-item
                  ><el-form-item label="发票类型"
                    ><el-select
                      v-model="line.invoice_type"
                      :disabled="claim.workflow_key === 'no_invoice'"
                      placeholder="可根据材料建议回填"
                      @change="
                        (v: string) => patchLine(line, 'invoice_type', v)
                      "
                      ><el-option
                        v-for="t in session.catalog?.invoice_types"
                        :key="t"
                        :value="t"
                        :label="t" /></el-select></el-form-item
                  ><el-form-item
                    v-if="claim.workflow_key === 'travel'"
                    label="本条费用对应出差审批"
                    class="full-width"
                    ><el-select
                      v-model="line.related_id"
                      placeholder="从已获取的出差审批中选择"
                      :loading="approvalsLoading"
                      clearable
                      @change="(v: string) => patchLine(line, 'related_id', v)"
                      ><el-option
                        v-for="a in approvals.filter(
                          (a) => a.approval_type === 'travel',
                        )"
                        :key="a.id"
                        :label="
                          a.title + ' · ' + a.start_date + ' — ' + a.end_date
                        "
                        :value="a.id" /></el-select></el-form-item
                  ><el-form-item class="full-width" label="明细备注（可选）"
                    ><el-input
                      v-model="line.remark"
                      placeholder="可补充付款、票据或费用范围说明"
                      @change="
                        (v: string) => patchLine(line, 'remark', v)
                      " /></el-form-item
                ></el-form>
              </article>
              <div v-if="!claim.lines.length" class="empty">
                <p>先建立费用明细，再上传并分配对应材料。</p>
                <el-button
                  v-if="!readOnly"
                  type="primary"
                  :icon="Plus"
                  @click="addLine"
                  >添加第一条费用</el-button
                >
              </div>
              <el-button
                v-else-if="!readOnly"
                :icon="Plus"
                style="width: 100%; border-style: dashed"
                :disabled="busy"
                @click="addLine"
                >添加费用明细</el-button
              ><el-form
                v-if="claim.workflow_key === 'travel'"
                label-position="top"
                style="margin-top: 24px"
                :disabled="readOnly || busy"
                ><el-form-item label="差旅日期冲突说明（有冲突时必填）"
                  ><el-input
                    v-model="claim.travel_date_remark"
                    type="textarea"
                    :rows="3"
                    maxlength="500"
                    show-word-limit
                    placeholder="如费用日期与实际乘车/住宿或出差审批不一致，请填写4—500字符真实说明"
                    @change="
                      (v: string) => patch('travel_date_remark', v)
                    " /></el-form-item></el-form
            ></template>
            <MaterialWorkbench
              v-if="step === 2"
              :claim="claim"
              :readonly="readOnly"
              @changed="refresh"
            />
            <AgentPanel
              v-if="step === 3 || step === 4"
              :key="step"
              ref="panel"
              :claim="claim"
              :kind="step === 3 ? 'suggestions' : 'reviews'"
              :readonly="readOnly"
              :runs="runs"
              @changed="refresh"
              @submitted="submitted"
            />
          </div>
        </section>
        <div class="form-actions" v-if="step < 4">
          <el-button :disabled="step === 0 || busy || saveError" @click="step--"
            >上一步</el-button
          ><el-button
            type="primary"
            :disabled="busy || saveError"
            @click="nextStep"
            >{{
              step === 3 ? "前往整单审核" : "下一步：" + steps[step + 1]
            }}</el-button
          >
        </div>
      </div>
      <aside class="summary-card">
        <section class="panel">
          <div class="panel-body">
            <div>
              <div class="summary-label">员工申报总金额</div>
              <div class="summary-amount">
                {{
                  claim.total_amount ? currency(claim.total_amount) : "待填写"
                }}
              </div>
            </div>
            <div class="summary-list">
              <div>
                <span>费用明细</span
                ><strong>{{ claim.lines.length }} 条</strong>
              </div>
              <div>
                <span>已上传材料</span
                ><strong>{{ claim.materials.length }} 份</strong>
              </div>
              <div>
                <span>待分配材料</span
                ><strong
                  >{{
                    claim.materials.filter(
                      (m) => m.kind !== "other" && !m.line_id,
                    ).length
                  }}
                  份</strong
                >
              </div>
              <div>
                <span>已完成识别</span
                ><strong
                  >{{
                    claim.materials.filter((m) => m.status === "recognized")
                      .length
                  }}
                  份</strong
                >
              </div>
            </div>
            <div class="summary-note">
              填写真实用途，确认材料归属。系统协助识别与核验，无法确认的内容会交由您处理。
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-body">
            <h3 style="font-size: 12px; margin-bottom: 14px">申报与明细核对</h3>
            <div class="summary-list amount-comparison">
              <div>
                <span>人工申报</span
                ><strong>{{
                  claim.total_amount ? currency(claim.total_amount) : "待填写"
                }}</strong>
              </div>
              <div>
                <span>明细合计</span
                ><strong>{{
                  lineTotal === null ? "待核对" : currency(lineTotal)
                }}</strong>
              </div>
              <div>
                <span>申报 − 明细</span
                ><strong>{{
                  totalDifference === null
                    ? "待核对"
                    : currency(totalDifference)
                }}</strong>
              </div>
            </div>
            <p class="field-help" role="status">
              {{
                totalMatches
                  ? "总额与明细一致，付款及票据支持仍需审核。"
                  : claim.total_amount
                    ? "总额与明细不一致，需核对后才能提交。"
                    : "请先独立填写本次申报总金额。"
              }}
            </p>
            <el-button
              v-if="!readOnly"
              link
              type="primary"
              :disabled="busy"
              @click="editTotal"
              >{{
                claim.total_amount ? "修改申报总金额" : "填写申报总金额"
              }}</el-button
            >
            <p class="field-help">
              比较容差为0.01元。明细可以参考识别结果填写；申报总金额始终由您独立填写。
            </p>
          </div>
        </section>
      </aside>
    </div> </template
  ><el-skeleton v-else-if="!error" :rows="10" animated />
  <el-dialog v-model="accountDialog" title="收款账户" width="min(520px, 95vw)"
    ><div class="notice">
      仅显示脱敏账户，修改时请重新输入完整值。体验请使用合成账号。
    </div>
    <div v-if="accounts.length" class="stack" style="margin-bottom: 24px">
      <div v-for="a in accounts" :key="a.id" class="task-row">
        <span>{{ a.label }} · {{ a.masked }}</span>
        <div>
          <el-button link size="small" @click="openAccount(a)">编辑</el-button
          ><el-button link size="small" @click="removeAccount(a)"
            >删除</el-button
          >
        </div>
      </div>
    </div>
    <el-form label-position="top"
      ><el-form-item label="账户名称"
        ><el-input
          v-model="accountForm.label"
          placeholder="例如：我的工资卡（合成）" /></el-form-item
      ><el-form-item label="账户类型"
        ><el-select v-model="accountForm.kind"
          ><el-option label="银行卡" value="bank" /><el-option
            label="对公账户"
            value="corporate" /><el-option
            label="支付宝"
            value="alipay" /><el-option
            label="钉钉账户"
            value="dingtalk" /></el-select></el-form-item
      ><el-form-item label="完整账户值"
        ><el-input
          v-model="accountForm.value"
          placeholder="请输入至少4字符的合成账户"
          show-password /></el-form-item></el-form
    ><template #footer
      ><el-button @click="accountDialog = false">关闭</el-button
      ><el-button
        type="primary"
        :disabled="!accountForm.label || accountForm.value.length < 4"
        @click="saveAccount"
        >{{ accountEdit ? "更新账户" : "添加账户" }}</el-button
      ></template
    ></el-dialog
  >
</template>
<style scoped>
.amount-comparison {
  display: grid;
}
</style>
