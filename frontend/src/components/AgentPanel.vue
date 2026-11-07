<script setup lang="ts">
import { ref, computed } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  MagicStick,
  Refresh,
  Check,
  ArrowRight,
} from "@element-plus/icons-vue";
import { useSession } from "../stores/session";
import {
  api,
  label,
  type Claim,
  type Run,
  type Report,
  type Batch,
} from "../api/client";
const session = useSession();
const props = defineProps<{
    claim: Claim;
    kind: "suggestions" | "reviews";
    readonly: boolean;
    runs: Run[];
  }>(),
  emit = defineEmits<{ changed: []; submitted: [string] }>();
const busy = ref(false),
  batch = ref<Batch>(),
  report = ref<Report>(),
  selected = ref<number[]>([]),
  filter = ref("issues"),
  activeRun = ref<Run>(),
  manualAmount = ref(""),
  taskDetails = ref<Run>();
const fields: Record<string, string> = {
  amount: "申报金额",
  business_date: "费用日期",
  invoice_type: "发票类型",
  expense_type: "费用类型",
};
const current = computed(() =>
  props.runs.find(
    (r) =>
      r.task_kind ===
      (props.kind === "reviews" ? "claim_review" : "line_suggest"),
  ),
);
const checks = computed(
  () =>
    report.value?.checks.filter(
      (c) =>
        filter.value === "all" ||
        (c.scope === "claim" && c.rule_id === "R-09") ||
        c.blocks_submission ||
        c.severity === "warning" ||
        c.status === "unknown",
    ) || [],
);
async function start() {
  busy.value = true;
  try {
    const c = await api<Claim>("/claims/" + props.claim.id);
    const r = await api(
      "/claims/" + props.claim.id + "/" + props.kind,
      "POST",
      { expected_revision: c.revision },
    );
    activeRun.value = await api<Run>("/agent-runs/" + r.run_id);
    batch.value = undefined;
    report.value = undefined;
    emit("changed");
  } finally {
    busy.value = false;
  }
}
async function refresh() {
  const r = current.value;
  if (!r) return;
  activeRun.value = r;
  if (r.output.batch_id) {
    batch.value = await api<Batch>("/suggestion-batches/" + r.output.batch_id);
    selected.value = batch.value.items
      .map((_, i) => i)
      .filter((i) => !batch.value!.items[i]!.protected);
  }
  if (r.output.report_id)
    report.value = await api<Report>("/review-reports/" + r.output.report_id);
}
async function apply() {
  if (!batch.value) return;
  const protectedValues = selected.value.some(
    (i) => batch.value!.items[i]!.protected,
  );
  if (protectedValues)
    await ElMessageBox.confirm(
      "选中的建议将替换您的人工填写值，是否确认？",
      "确认替换",
      { type: "warning" },
    );
  busy.value = true;
  try {
    await api("/suggestion-batches/" + batch.value.id + "/apply", "POST", {
      expected_revision: props.claim.revision,
      selected_indices: selected.value,
      replace_manual: protectedValues,
    });
    emit("changed");
    await refresh();
    ElMessage.success("已应用所选建议");
  } finally {
    busy.value = false;
  }
}
async function undo() {
  if (!batch.value) return;
  await api("/suggestion-batches/" + batch.value.id + "/undo", "POST", {
    expected_revision: props.claim.revision,
  });
  emit("changed");
  await refresh();
}
async function respond() {
  if (!current.value) return;
  const r = await api(
    "/agent-runs/" + current.value.id + "/responses",
    "POST",
    {
      expected_revision: props.claim.revision,
      question_id: current.value.question.question_id,
      manual_amount: manualAmount.value,
    },
  );
  manualAmount.value = "";
  activeRun.value = await api<Run>("/agent-runs/" + r.run_id);
  emit("changed");
}
async function cancel() {
  await api("/agent-runs/" + current.value!.id + "/cancel", "POST");
  emit("changed");
}
async function submit() {
  if (!report.value) return;
  await ElMessageBox.confirm(
    "提交后本次申报与材料将被锁定，系统只创建本地模拟 OA，不会通知真实员工。",
    "确认提交",
    { confirmButtonText: "确认提交", type: "info" },
  );
  let reason = "";
  if (
    props.claim.route_mode === "admin_originator" ||
    props.claim.actor_id !== session.me?.actor.id
  )
    reason = (
      await ElMessageBox.prompt(
        "请填写本次管理员提交的处理原因（至少4字符）",
        "管理员提交原因",
        {
          inputValidator: (v) =>
            (v?.trim().length || 0) >= 4 || "请填写明确原因",
        },
      )
    ).value;
  busy.value = true;
  try {
    const c = await api<Claim>("/claims/" + props.claim.id);
    const s = await api("/claims/" + props.claim.id + "/submissions", "POST", {
      expected_revision: c.revision,
      review_id: report.value.id,
      reason,
    });
    emit("submitted", s.id);
    ElMessage.success("提交已接受，等待模拟发起");
  } finally {
    busy.value = false;
  }
}
async function detail() {
  taskDetails.value = await api<Run>("/agent-runs/" + current.value!.id);
}
function openEvidence(id: string) {
  window.open(
    "/api/v1/materials/" + id + "/preview?page=1",
    "_blank",
    "noopener",
  );
}
defineExpose({ refresh });
</script>
<template>
  <div class="notice">
    {{
      kind === "suggestions"
        ? "建议只来自已分配材料。金额、日期和票种可选择回填；您的事由、项目和材料归属保持人工确认。"
        : "整单审核将核对当前申报、材料事实和业务规则。明确金额、身份和公司约束由程序执行，缺少证据时会提出具体问题。"
    }}
  </div>
  <div v-if="current" class="task-row">
    <div>
      <span class="status-chip" :class="current.status">{{
        label(current.status)
      }}</span
      ><span class="muted" style="font-size: 11px; margin-left: 10px"
        >版本 {{ current.input_revision }} ·
        {{
          current.execution_mode === "provider"
            ? "真实模型执行"
            : "合成样本执行"
        }}</span
      >
    </div>
    <div>
      <el-button link size="small" @click="detail">处理记录</el-button
      ><el-button
        v-if="
          !readonly &&
          ['queued', 'running', 'waiting_input'].includes(current.status)
        "
        link
        size="small"
        @click="cancel"
        >停止处理</el-button
      >
    </div>
  </div>
  <el-alert
    v-if="current?.error"
    :title="current.error"
    type="warning"
    :closable="false"
  />
  <div v-if="current?.status === 'waiting_input'" class="human-question">
    <strong>需要您核对材料</strong>
    <p>{{ current.question.text }}</p>
    <p v-if="current.question.candidates?.length" class="muted">
      候选金额：{{ current.question.candidates.join(" / ") }} 元
    </p>
    <el-input v-model="manualAmount" placeholder="实际付款金额" /><el-button
      type="primary"
      @click="respond"
      >确认并重新核验</el-button
    >
  </div>
  <div class="toolbar" style="margin: 18px 0">
    <el-button
      v-if="!readonly"
      type="primary"
      :icon="kind === 'suggestions' ? MagicStick : Refresh"
      :loading="
        busy || current?.status === 'running' || current?.status === 'queued'
      "
      @click="start"
      >{{ kind === "suggestions" ? "生成回填建议" : "开始整单审核" }}</el-button
    ><span v-if="!current" class="field-help" style="margin: 0">{{
      kind === "suggestions"
        ? "先上传并分配材料，再生成建议"
        : "请先填写独立申报总金额，并确认费用、材料、公司与收款账户"
    }}</span>
  </div>
  <template v-if="kind === 'suggestions' && batch"
    ><div v-if="batch.outdated" class="readonly-note">
      申报已变化，请重新生成建议。
    </div>
    <div v-if="!batch.items.length" class="empty">
      <el-icon style="font-size: 28px"><Check /></el-icon>
      <p>已填字段与材料一致，当前没有新的回填建议。</p>
    </div>
    <el-checkbox-group v-model="selected" class="stack"
      ><div
        v-for="(item, index) in batch.items"
        :key="index"
        class="suggestion-item"
      >
        <el-checkbox
          :value="index"
          :disabled="batch.status !== 'proposed' || batch.outdated || readonly"
          :aria-label="'选择建议 ' + (index + 1)"
        />
        <div>
          <strong
            >明细
            {{ claim.lines.findIndex((l) => l.id === item.line_id) + 1 }} ·
            {{ fields[item.field] }}</strong
          ><span v-if="item.protected" class="source-tag">人工值保护</span>
          <div class="value-change">
            <span>{{ item.previous_value || "尚未填写" }}</span
            ><el-icon><ArrowRight /></el-icon><b>{{ item.value }}</b>
          </div>
          <p>
            {{ item.source_description }} ·
            {{ item.evidence_refs.length }} 份依据
          </p>
        </div>
      </div></el-checkbox-group
    >
    <div class="toolbar" style="margin-top: 20px">
      <el-button
        v-if="batch.status === 'proposed' && !readonly"
        type="primary"
        :disabled="!selected.length || batch.outdated"
        :loading="busy"
        @click="apply"
        >应用所选建议（{{ selected.length }}）</el-button
      ><el-button v-if="batch.status === 'applied' && !readonly" @click="undo"
        >撤回本批回填</el-button
      ><span class="field-help">{{ label(batch.status) }}</span>
    </div></template
  >
  <template v-if="kind === 'reviews' && report"
    ><div v-if="!report.valid" class="readonly-note">
      申报已发生变化，本报告已失效。请重新审核后提交。
    </div>
    <div class="review-summary" :class="{ blocked: !report.can_submit }">
      <div>
        <el-icon style="font-size: 24px"><Check /></el-icon>
      </div>
      <div>
        <h3>
          {{
            report.can_submit
              ? "已满足本次提交条件"
              : "还有 " + report.summary.blocking + " 项需要处理"
          }}
        </h3>
        <p>
          完成 {{ report.summary.checked }} 项核验 ·
          {{ report.summary.warnings }} 条提示 ·
          {{
            report.execution_mode === "provider"
              ? "真实模型审核"
              : "合成样本审核"
          }}
        </p>
      </div>
    </div>
    <div class="report-filters">
      <el-radio-group v-model="filter" size="small"
        ><el-radio-button value="issues">待处理与提示</el-radio-button
        ><el-radio-button value="all">全部检查</el-radio-button></el-radio-group
      >
    </div>
    <div v-for="c in checks" :key="c.check_id" class="review-check">
      <span class="check-dot" :class="c.status">{{
        c.status === "fail" ? "!" : c.status === "unknown" ? "?" : "✓"
      }}</span>
      <div>
        <h3>
          {{ c.label
          }}<span class="muted" style="font-size: 9px">{{ c.rule_id }}</span>
        </h3>
        <p>{{ c.message }}</p>
        <span v-if="c.blocks_submission" class="next-action"
          >下一步：{{ c.next_action }}</span
        >
        <div class="review-refs">
          <el-button
            v-for="id in c.evidence_refs"
            :key="id"
            link
            type="primary"
            size="small"
            @click="openEvidence(id)"
            >{{
              claim.materials.find((m) => m.id === id)?.name || "材料依据"
            }}</el-button
          >
        </div>
      </div>
    </div>
    <div v-if="!checks.length" class="empty" style="padding: 25px">
      <p>暂无需要处理的问题，可切换查看全部检查。</p>
    </div>
    <div class="form-actions">
      <p class="field-help">
        {{
          claim.workflow_key === "no_invoice"
            ? "无票报销保留后续人工审批去向。"
            : "通过前置核验后，进入模拟 OA 创建流程。"
        }}
      </p>
      <el-button
        v-if="!readonly"
        type="primary"
        :disabled="!report.valid || !report.can_submit"
        :loading="busy"
        @click="submit"
        >确认提交</el-button
      >
    </div></template
  >
  <el-dialog
    :model-value="!!taskDetails"
    title="Agent 处理记录"
    width="min(650px, 94vw)"
    @close="taskDetails = undefined"
    ><template v-if="taskDetails"
      ><div class="notice">
        展示任务、工具调用与停止原因，不展示模型隐藏思维链。模型
        {{ taskDetails.model_calls }} 次 / 工具
        {{ taskDetails.tool_calls }} 次。
      </div>
      <div class="event-list">
        <div
          v-for="(s, index) in taskDetails.steps"
          :key="index"
          class="event-item"
        >
          <strong>{{ s.node }}</strong>
          <p>{{ JSON.stringify(s.detail) }}</p>
        </div>
      </div>
      <p class="field-help">
        停止原因：{{ taskDetails.stop_reason || "处理中" }}
      </p></template
    ></el-dialog
  >
</template>
