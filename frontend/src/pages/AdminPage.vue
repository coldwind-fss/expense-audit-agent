<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { Refresh, Plus } from "@element-plus/icons-vue";
import { api, dateTime, label, type Claim } from "../api/client";
import { useSession } from "../stores/session";
const session = useSession(),
  router = useRouter(),
  tab = ref("cases"),
  rows = ref<any[]>([]),
  entries = ref<any[]>([]),
  answers = ref<any[]>([]),
  people = ref<any[]>([]),
  columns = ref<string[]>([]),
  caseDialog = ref(false),
  caseForm = ref({
    subject_id: "",
    workflow_key: "daily",
    title: "管理员协助报销",
    reason: "",
  }),
  detail = ref<any>(),
  campaign = ref("体验反馈-2026"),
  recipients = ref<string[]>([]),
  invitationLinks = ref<any[]>([]),
  search = ref(""),
  repairDialog = ref(false),
  repairForm = ref({
    company_id: "",
    account_id: "",
    total_amount: "",
    remark: "",
    reason: "",
  });
const tabs = [
  { key: "cases", label: "协助案件" },
  { key: "jobs", label: "任务池" },
  { key: "events", label: "操作事件" },
  { key: "ledger", label: "发票台账" },
  { key: "feedback", label: "使用反馈" },
];
async function load() {
  if (tab.value === "ledger") {
    const r = await api("/ledger/events");
    rows.value = r.items;
    columns.value = r.columns;
    entries.value = (await api("/ledger/entries")).items;
  } else if (tab.value === "feedback") {
    rows.value = (await api("/feedback/invitations")).items;
    answers.value = (await api("/feedback/answers")).items;
  } else rows.value = (await api("/admin/" + tab.value)).items;
}
async function choose(key: string) {
  tab.value = key;
  search.value = "";
  await load();
}
async function createCase() {
  const c = await api("/admin/cases/manual", "POST", caseForm.value);
  caseDialog.value = false;
  await load();
  ElMessage.success("案件与草稿已保存，尚未提交");
  await router.push("/claims/" + c.claim_id);
}
async function showCase(row: any) {
  detail.value = await api("/admin/cases/" + row.id);
}
async function reason(title: string) {
  return (
    await ElMessageBox.prompt("请填写本次处理的业务原因（至少4字符）", title, {
      inputValidator: (v) => (v?.trim().length || 0) >= 4 || "请输入明确原因",
    })
  ).value;
}
async function action(job: any, name: string) {
  const why = await reason("确认管理操作");
  let scheduled: string | undefined;
  if (name === "reschedule") {
    const v = (
      await ElMessageBox.prompt(
        "请输入带时区的时间，如 2026-11-21T09:00:00+08:00",
        "调整计划时间",
      )
    ).value;
    scheduled = v;
  }
  const r = await api("/admin/jobs/" + job.id + "/actions", "POST", {
    action: name,
    expected_status: job.status,
    reason: why,
    scheduled_at: scheduled,
  });
  if (name === "query")
    ElMessage.info(
      r.submission?.status === "succeeded"
        ? "已查到现有模拟实例，未重复创建"
        : "仍缺少创建证据，维持待核对",
    );
  await load();
}
function openRepair() {
  repairForm.value = {
    company_id: detail.value.claim.company_id || "",
    account_id: detail.value.claim.account_id || "",
    total_amount: detail.value.claim.total_amount || "",
    remark: detail.value.claim.remark,
    reason: "",
  };
  repairDialog.value = true;
}
async function repair() {
  await api("/admin/cases/" + detail.value.id + "/repair", "POST", {
    reason: repairForm.value.reason,
    patch: {
      expected_revision: detail.value.claim.revision,
      company_id: repairForm.value.company_id || null,
      account_id: repairForm.value.account_id || null,
      total_amount: repairForm.value.total_amount || null,
      remark: repairForm.value.remark,
    },
  });
  repairDialog.value = false;
  await showCase(detail.value);
  ElMessage.success("修复已通过预校验并保存，需重新整单审核");
}
async function submitCase() {
  const why = await reason("确认管理员代发");
  const c = await api<Claim>("/claims/" + detail.value.claim_id);
  if (!c.latest_review_id) {
    ElMessage.warning("请先在共享编辑器完成整单审核");
    return;
  }
  await api("/admin/cases/" + detail.value.id + "/submit", "POST", {
    expected_revision: c.revision,
    review_id: c.latest_review_id,
    reason: why,
  });
  detail.value = undefined;
  await load();
  ElMessage.success("提交已接受");
}
async function sync(row: any) {
  await api("/ledger/events/" + row.id + "/sync", "POST", {
    reason: await reason("同步本地模拟台账"),
  });
  await load();
  ElMessage.success("已处理本地模拟投影，真实工作簿未变更");
}
async function rollback(row: any) {
  await api("/ledger/entries/" + row.id + "/rollback", "POST", {
    reason: await reason("回滚本地投影"),
  });
  await load();
}
async function simulateEvent(row: any, state: string) {
  const submission = await api("/submissions/" + row.submission_id);
  const result = await api(
    "/submissions/" + row.submission_id + "/simulated-event",
    "POST",
    {
      expected_state: submission.simulated_approval_state,
      state,
      reason: await reason("模拟审批事件与本地台账核对"),
    },
  );
  await load();
  ElMessage.info(
    result.conflicts.length
      ? "已记录模拟事件，部分投影存在冲突需人工核对"
      : "模拟事件已记录，符合条件的投影已回滚",
  );
}
async function invite() {
  const r = await api("/feedback/invitations", "POST", {
    campaign: campaign.value,
    employee_ids: recipients.value,
  });
  invitationLinks.value = r.items.filter((i: any) => i.url);
  await load();
  ElMessage.success("本地模拟邀请已生成，未发送真实通知");
}
async function retryInvite(row: any) {
  const r = await api("/feedback/invitations/" + row.id + "/retry", "POST", {
    reason: await reason("重试明确失败的邀请"),
  });
  invitationLinks.value = [r];
  await load();
}
onMounted(async () => {
  if (session.me?.actor.role !== "admin") {
    await router.replace("/");
    return;
  }
  await load();
  people.value = (await api("/employees")).items;
});
const filtered = (items: any[]) =>
  items.filter((i) =>
    JSON.stringify(i).toLowerCase().includes(search.value.toLowerCase()),
  );
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">OPERATIONS & AUDIT</div>
      <h1>系统管理</h1>
      <p>协助处理异常、核对任务与台账，让每次操作都可追溯。</p>
    </div>
    <el-button :icon="Refresh" @click="load">刷新</el-button>
  </div>
  <div class="admin-tabs">
    <button
      v-for="t in tabs"
      :key="t.key"
      :class="{ active: tab === t.key }"
      @click="choose(t.key)"
    >
      {{ t.label }}
    </button>
  </div>
  <section class="panel">
    <div class="panel-heading">
      <h2>{{ tabs.find((t) => t.key === tab)?.label }}</h2>
      <div class="toolbar">
        <el-input
          v-model="search"
          clearable
          placeholder="搜索当前记录"
          style="width: 200px"
        /><el-button
          v-if="tab === 'cases'"
          type="primary"
          :icon="Plus"
          @click="caseDialog = true"
          >新建协助案件</el-button
        >
      </div>
    </div>
    <template v-if="tab === 'cases'"
      ><el-table :data="filtered(rows)"
        ><el-table-column label="案件说明" min-width="260"
          ><template #default="{ row }"
            ><strong>{{ row.reason }}</strong>
            <p class="field-help">
              归属：{{ people.find((p) => p.id === row.subject_id)?.name }} ·
              版本 {{ row.revision }}
            </p></template
          ></el-table-column
        ><el-table-column label="状态" width="130"
          ><template #default="{ row }"
            ><span class="status-chip" :class="row.status">{{
              label(row.status)
            }}</span></template
          ></el-table-column
        ><el-table-column label="操作" width="190"
          ><template #default="{ row }"
            ><el-button link type="primary" @click="showCase(row)"
              >案件详情</el-button
            ><el-button link @click="router.push('/claims/' + row.claim_id)"
              >打开报销</el-button
            ></template
          ></el-table-column
        ></el-table
      ></template
    >
    <template v-if="tab === 'jobs'"
      ><el-table :data="filtered(rows)"
        ><el-table-column
          prop="kind"
          label="任务类型"
          width="100"
        /><el-table-column label="任务 / 状态" min-width="240"
          ><template #default="{ row }"
            ><span class="status-chip" :class="row.status">{{
              label(row.status)
            }}</span>
            <p class="field-help">{{ row.id }}</p>
            <p v-if="row.error" class="material-warning">
              {{ row.error }}
            </p></template
          ></el-table-column
        ><el-table-column label="计划时间" min-width="180"
          ><template #default="{ row }">{{
            dateTime(row.available_at)
          }}</template></el-table-column
        ><el-table-column
          prop="attempts"
          label="尝试"
          width="65"
        /><el-table-column label="受控操作" min-width="200"
          ><template #default="{ row }"
            ><el-button
              v-if="row.status === 'queued'"
              link
              type="primary"
              @click="action(row, 'pause')"
              >暂停</el-button
            ><el-button
              v-if="row.status === 'paused'"
              link
              type="primary"
              @click="action(row, 'resume')"
              >恢复</el-button
            ><el-button
              v-if="['paused', 'queued'].includes(row.status)"
              link
              @click="action(row, 'reschedule')"
              >调时</el-button
            ><el-button
              v-if="row.kind === 'dispatch' && row.status === 'unknown'"
              link
              type="primary"
              @click="action(row, 'query')"
              >核对创建结果</el-button
            ><el-button
              v-if="
                ['ledger', 'import'].includes(row.kind) &&
                row.status === 'failed'
              "
              link
              type="primary"
              @click="action(row, 'retry')"
              >重试旁路</el-button
            ><span v-if="row.status === 'running'" class="muted"
              >执行中</span
            ></template
          ></el-table-column
        ></el-table
      ></template
    >
    <div v-if="tab === 'events'" class="admin-content event-list">
      <div v-for="e in filtered(rows)" :key="e.id" class="event-item">
        <div style="display: flex; justify-content: space-between; gap: 15px">
          <strong>{{ e.action }}</strong
          ><span class="muted">{{ dateTime(e.at) }}</span>
        </div>
        <p>
          操作人 {{ people.find((p) => p.id === e.actor_id)?.name || "系统" }}
          <el-button
            v-if="e.claim_id"
            link
            size="small"
            type="primary"
            @click="router.push('/claims/' + e.claim_id)"
            >查看报销</el-button
          >
        </p>
        <p>{{ JSON.stringify(e.detail) }}</p>
      </div>
      <div v-if="!rows.length" class="empty">暂无操作事件</div>
    </div>
    <div v-if="tab === 'ledger'" class="admin-content">
      <div class="notice">
        默认 audit
        只保存候选与异常；“模拟同步”仅写本地13列投影。台账失败独立处理，不会重新创建
        OA。
      </div>
      <el-table :data="filtered(rows)"
        ><el-table-column
          prop="month"
          label="月份"
          width="100"
        /><el-table-column
          prop="mode"
          label="模式"
          width="80"
        /><el-table-column label="状态 / 字段异常" min-width="220"
          ><template #default="{ row }"
            ><span class="status-chip" :class="row.status">{{
              label(row.status)
            }}</span>
            <p
              v-for="(issue, index) in row.issues"
              :key="index"
              class="material-warning"
            >
              {{ issue.code }} {{ issue.fields?.join("、") }}
            </p></template
          ></el-table-column
        ><el-table-column label="票据候选" width="100"
          ><template #default="{ row }"
            >{{ row.candidates.length }} 张</template
          ></el-table-column
        ><el-table-column label="操作" width="210"
          ><template #default="{ row }"
            ><el-button link type="primary" @click="sync(row)"
              >模拟同步</el-button
            ><el-button
              link
              size="small"
              @click="simulateEvent(row, 'rejected')"
              >模拟退回</el-button
            ><el-button
              link
              size="small"
              @click="simulateEvent(row, 'cancelled')"
              >模拟撤销</el-button
            ></template
          ></el-table-column
        ></el-table
      >
      <h3 style="margin: 25px 0 15px">本地模拟投影</h3>
      <div style="overflow: auto">
        <el-table :data="entries" min-width="1700"
          ><el-table-column
            v-for="(col, index) in columns"
            :key="col"
            :label="col"
            :min-width="index === 0 ? 65 : 150"
            ><template #default="{ row }">{{
              row.values[index] || "—"
            }}</template></el-table-column
          ><el-table-column label="状态 / 操作" width="175" fixed="right"
            ><template #default="{ row }"
              ><span class="status-chip">{{ label(row.status) }}</span
              ><el-button
                v-if="row.status !== 'rolled_back'"
                link
                type="primary"
                @click="rollback(row)"
                >回滚</el-button
              ></template
            ></el-table-column
          ></el-table
        >
      </div>
    </div>
    <div v-if="tab === 'feedback'" class="admin-content">
      <div class="notice">
        邀请仅关联当前合成空间员工，生成本地 Stub
        记录，不发送真实通知。链接打开、答卷提交与强实名是不同概念；完整链接只在生成时显示。
      </div>
      <el-form label-position="top" class="two-col"
        ><el-form-item label="反馈批次"
          ><el-input v-model="campaign" maxlength="100" /></el-form-item
        ><el-form-item label="合成员工"
          ><el-select v-model="recipients" multiple
            ><el-option
              v-for="p in people"
              :key="p.id"
              :value="p.id"
              :label="p.name" /></el-select></el-form-item
      ></el-form>
      <div class="toolbar" style="margin-bottom: 22px">
        <el-button
          type="primary"
          :disabled="!campaign || !recipients.length"
          @click="invite"
          >生成模拟邀请</el-button
        ><a href="/api/v1/feedback/export" target="_blank" rel="noopener"
          ><el-button>导出答卷 CSV</el-button></a
        >
      </div>
      <div v-if="invitationLinks.length" class="notice">
        <p>本次新生成链接，请保存：</p>
        <p v-for="i in invitationLinks" :key="i.id">
          <a :href="i.url" target="_blank" rel="noopener" style="color: #3b82f6"
            >{{ i.name || "查看反馈问卷" }} →</a
          >
        </p>
      </div>
      <el-table :data="filtered(rows)"
        ><el-table-column
          prop="name"
          label="邀请归属"
          min-width="100"
        /><el-table-column
          prop="campaign"
          label="批次"
          min-width="140"
        /><el-table-column label="状态" min-width="160"
          ><template #default="{ row }"
            ><span class="status-chip">{{ label(row.status) }}</span>
            <p class="field-help">
              {{ row.opened_at ? "链接曾打开" : "尚无打开记录" }}
            </p></template
          ></el-table-column
        ><el-table-column label="操作" width="100"
          ><template #default="{ row }"
            ><el-button
              v-if="row.status === 'failed'"
              link
              type="primary"
              @click="retryInvite(row)"
              >重试</el-button
            ></template
          ></el-table-column
        ></el-table
      >
      <h3 style="margin: 25px 0 15px">答卷详情</h3>
      <el-table :data="answers"
        ><el-table-column
          prop="difficulty"
          label="遇到的困难"
          min-width="130" /><el-table-column
          prop="priority"
          label="优先改进"
          min-width="130" /><el-table-column
          prop="suggestion"
          label="建议"
          min-width="280"
      /></el-table>
    </div>
  </section>
  <el-dialog v-model="caseDialog" title="新建协助案件" width="min(540px, 94vw)"
    ><div class="notice">
      新建只保存草稿，不会自动发起。管理员在后续审核通过后明确提交，OA
      发起人由服务端确定为所选员工。
    </div>
    <el-form label-position="top"
      ><el-form-item label="报销归属人"
        ><el-select v-model="caseForm.subject_id"
          ><el-option
            v-for="p in people"
            :key="p.id"
            :label="p.name"
            :value="p.id" /></el-select></el-form-item
      ><el-form-item label="报销入口"
        ><el-select v-model="caseForm.workflow_key"
          ><el-option
            v-for="w in session.catalog?.workflows"
            :key="w.key"
            :label="w.label"
            :value="w.key" /></el-select></el-form-item
      ><el-form-item label="标题"
        ><el-input v-model="caseForm.title" /></el-form-item
      ><el-form-item label="协助原因"
        ><el-input
          v-model="caseForm.reason"
          type="textarea"
          :rows="3"
          maxlength="1000" /></el-form-item></el-form
    ><template #footer
      ><el-button @click="caseDialog = false">取消</el-button
      ><el-button
        type="primary"
        :disabled="!caseForm.subject_id || caseForm.reason.length < 4"
        @click="createCase"
        >保存并打开草稿</el-button
      ></template
    ></el-dialog
  >
  <el-dialog
    :model-value="!!detail"
    title="协助案件详情"
    width="min(700px, 94vw)"
    @close="detail = undefined"
    ><template v-if="detail"
      ><h3>{{ detail.claim.title }}</h3>
      <p class="field-help">
        操作人 {{ detail.claim.actor_name }} / 归属
        {{ detail.claim.subject_name }} / OA 发起
        {{ detail.claim.originator_name }}
      </p>
      <p style="margin: 15px 0; font-size: 12px">{{ detail.reason }}</p>
      <div class="toolbar">
        <el-button
          type="primary"
          @click="router.push('/claims/' + detail.claim_id)"
          >打开共享编辑器</el-button
        ><el-button v-if="detail.claim.status === 'draft'" @click="openRepair"
          >受控修复</el-button
        ><el-button v-if="detail.claim.status === 'draft'" @click="submitCase"
          >审核后代发</el-button
        >
      </div>
      <h3 style="margin: 25px 0 14px">草稿版本</h3>
      <p class="field-help">
        {{ detail.revisions.map((r: any) => "v" + r.revision).join(" → ") }}
      </p>
      <h3 style="margin: 25px 0 14px">管理操作留痕</h3>
      <div class="event-list">
        <div
          v-for="(a, index) in detail.actions"
          :key="index"
          class="event-item"
        >
          <strong>{{ a.action }}</strong>
          <p>{{ a.reason }}</p>
        </div>
      </div></template
    ></el-dialog
  >
  <el-dialog
    v-model="repairDialog"
    title="受控修复与完整预校验"
    width="min(520px, 94vw)"
    ><el-form label-position="top"
      ><el-form-item label="付款公司"
        ><el-select v-model="repairForm.company_id"
          ><el-option
            v-for="c in session.catalog?.companies"
            :key="c.id"
            :value="c.id"
            :label="c.name" /></el-select></el-form-item
      ><el-form-item label="收款账户 ID（现有合法引用）"
        ><el-input v-model="repairForm.account_id" /></el-form-item
      ><el-form-item label="本次申报总金额（元）" required>
        <el-input
          v-model="repairForm.total_amount"
          inputmode="decimal"
          placeholder="按实际申报独立填写"
        /> </el-form-item
      ><el-form-item label="申报备注"
        ><el-input v-model="repairForm.remark" type="textarea" /></el-form-item
      ><el-form-item label="处理原因"
        ><el-input v-model="repairForm.reason" type="textarea" /></el-form-item
    ></el-form>
    <p class="field-help">
      费用与材料请在共享编辑器处理。修复保存仍需完整预校验，并使旧审核失效。
    </p>
    <template #footer
      ><el-button @click="repairDialog = false">取消</el-button
      ><el-button
        type="primary"
        :disabled="repairForm.reason.length < 4"
        @click="repair"
        >校验并保存修复</el-button
      ></template
    ></el-dialog
  >
</template>
