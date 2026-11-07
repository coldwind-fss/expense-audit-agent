<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessageBox } from "element-plus";
import { Refresh, Document } from "@element-plus/icons-vue";
import {
  api,
  currency,
  dateTime,
  label,
  type Submission,
  type Claim,
} from "../api/client";
const simulatedLabels: Record<string, string> = {
  created: "已创建，后续审批未接",
  rejected: "模拟退回",
  cancelled: "模拟撤销",
};
const rows = ref<Submission[]>([]),
  detail = ref<Submission>(),
  router = useRouter(),
  cursor = ref<number | null>(null);
let timer: ReturnType<typeof setInterval>;
async function load(more = false) {
  const r = await api("/submissions?cursor=" + (more ? cursor.value : 0));
  rows.value = more ? [...rows.value, ...r.items] : r.items;
  cursor.value = r.next_cursor;
}
async function show(row: Submission) {
  detail.value = await api<Submission>("/submissions/" + row.id);
}
async function copy(row: Submission) {
  await ElMessageBox.confirm(
    "原记录保留并标记撤销，费用与合法附件引用复制到新草稿。",
    "撤销并复制",
  );
  const claim = await api<Claim>("/claims/" + row.claim_id);
  const c = await api<Claim>(
    "/submissions/" + row.id + "/cancel-and-copy",
    "POST",
    { expected_revision: claim.revision, expected_status: row.status },
  );
  await router.push("/claims/" + c.id);
}
onMounted(async () => {
  await load();
  timer = setInterval(() => {
    if (
      rows.value.some((s) =>
        ["scheduled", "dispatching", "retry"].includes(s.status),
      )
    )
      load();
  }, 2500);
});
onUnmounted(() => clearInterval(timer));
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">SUBMISSION HISTORY</div>
      <h1>提交记录</h1>
      <p>追踪已接受的申报、模拟 OA 创建与待处理结果。</p>
    </div>
    <el-button :icon="Refresh" @click="load()">刷新记录</el-button>
  </div>
  <div class="notice">
    “模拟 OA 已创建”表示本地 Stub 创建得到确认，不代表真实 OA
    已审批或财务已付款。结果待核对时，管理员先查询已有创建证据。
  </div>
  <section class="panel">
    <el-table :data="rows"
      ><el-table-column label="报销事项" min-width="230"
        ><template #default="{ row }"
          ><div class="table-title">
            <span class="file-icon"
              ><el-icon><Document /></el-icon></span
            ><strong>{{ row.title }}</strong>
          </div></template
        ></el-table-column
      ><el-table-column label="申报金额" min-width="140"
        ><template #default="{ row }">{{
          currency(row.total_amount)
        }}</template></el-table-column
      ><el-table-column label="提交状态" min-width="155"
        ><template #default="{ row }"
          ><span class="status-chip" :class="row.status">{{
            label(row.status)
          }}</span></template
        ></el-table-column
      ><el-table-column label="提交时间" min-width="190"
        ><template #default="{ row }">{{
          dateTime(row.created_at)
        }}</template></el-table-column
      ><el-table-column label="操作" width="150"
        ><template #default="{ row }"
          ><el-button link type="primary" @click="show(row)">详情</el-button
          ><el-button
            v-if="['scheduled', 'retry', 'manual'].includes(row.status)"
            link
            @click="copy(row)"
            >撤销复制</el-button
          ></template
        ></el-table-column
      ><template #empty
        ><div class="empty">
          <h3>还没有提交记录</h3>
          <p>完成整单审核并确认提交后，记录将在这里呈现。</p>
          <el-button type="primary" @click="router.push('/')"
            >前往报销工作台</el-button
          >
        </div></template
      ></el-table
    >
    <div class="load-more" v-if="cursor">
      <el-button @click="load(true)">加载更多</el-button>
    </div>
  </section>
  <el-dialog
    :model-value="!!detail"
    title="提交详情"
    width="min(650px, 94vw)"
    @close="detail = undefined"
    ><template v-if="detail"
      ><div class="readonly-note">本地模拟接口 · 没有创建真实 OA</div>
      <el-descriptions :column="1" border
        ><el-descriptions-item label="报销标题">{{
          detail.title
        }}</el-descriptions-item
        ><el-descriptions-item label="当前状态">{{
          label(detail.status)
        }}</el-descriptions-item
        ><el-descriptions-item label="申报金额">{{
          currency(detail.total_amount)
        }}</el-descriptions-item
        ><el-descriptions-item label="申请时间">{{
          dateTime(detail.created_at)
        }}</el-descriptions-item
        ><el-descriptions-item label="计划发起">{{
          dateTime(detail.scheduled_at)
        }}</el-descriptions-item
        ><el-descriptions-item label="模拟创建时间">{{
          dateTime(detail.dispatched_at)
        }}</el-descriptions-item
        ><el-descriptions-item label="模拟引用">{{
          detail.simulated_reference || "—"
        }}</el-descriptions-item
        ><el-descriptions-item label="模拟审批状态">{{
          simulatedLabels[detail.simulated_approval_state || ""] || "尚未创建"
        }}</el-descriptions-item
        ><el-descriptions-item label="异常说明">{{
          detail.failure || "无"
        }}</el-descriptions-item></el-descriptions
      ><el-button
        style="margin-top: 20px"
        @click="router.push('/claims/' + detail!.claim_id)"
        >查看申报内容</el-button
      ><el-collapse style="margin-top: 20px"
        ><el-collapse-item title="冻结的提交快照">
          <pre class="detail-code">{{
            JSON.stringify(detail.snapshot, null, 2)
          }}</pre>
        </el-collapse-item></el-collapse
      ></template
    ></el-dialog
  >
</template>
