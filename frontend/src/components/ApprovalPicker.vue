<script setup lang="ts">
import { ref, watch } from "vue";
import { Check, Refresh, Document } from "@element-plus/icons-vue";
import type { RelatedApproval } from "../api/client";

const props = defineProps<{
  items: RelatedApproval[];
  selected: string[];
  subjectId: string;
  subjectName: string;
  loading: boolean;
  error: string;
  readonly: boolean;
  busy: boolean;
  resolving: boolean;
  lookupError: string;
}>();
const emit = defineEmits<{
  change: [ids: string[]];
  refresh: [];
  resolve: [businessId: string];
}>();
const manualOpen = ref(false),
  businessNumber = ref("");
const kinds: Record<string, string> = {
  travel: "出差申请",
  outing: "外出申请",
  team: "部门活动",
};
const states: Record<string, string> = {
  approved: "已通过",
  pending: "审批中",
  rejected: "未通过",
  cancelled: "已撤销",
};
watch(
  () => props.subjectId,
  () => {
    manualOpen.value = false;
    businessNumber.value = "";
  },
);
function toggle(id: string) {
  emit(
    "change",
    props.selected.includes(id)
      ? props.selected.filter((value) => value !== id)
      : [...props.selected, id],
  );
}
</script>

<template>
  <section
    class="approval-picker"
    aria-label="自动获取关联审批"
    :aria-busy="loading"
  >
    <div class="approval-heading">
      <div>
        <strong>自动获取关联审批</strong>
        <span class="approval-source">模拟 OA 数据</span>
        <p v-if="loading" role="status">
          正在获取 {{ subjectName }} 的审批记录…
        </p>
        <p v-else-if="!error" role="status">
          已自动获取 {{ subjectName }} 的
          {{ items.length }} 条审批，选择与本次费用相关的记录。
        </p>
      </div>
      <el-button
        size="small"
        :icon="Refresh"
        :loading="loading"
        :disabled="busy || loading"
        @click="emit('refresh')"
        >刷新审批</el-button
      >
    </div>
    <div v-if="error" class="approval-message" role="alert">
      {{ error }}，可点击“刷新审批”重试。
    </div>
    <div v-else-if="!loading && !items.length" class="approval-message">
      暂未找到 {{ subjectName }} 的审批记录。可刷新重试，或按审批单号补充查找。
    </div>
    <div v-if="!loading && !error" class="approval-list">
      <button
        v-for="item in items"
        :key="item.id"
        type="button"
        class="approval-card"
        :class="{ selected: selected.includes(item.id) }"
        :aria-pressed="selected.includes(item.id)"
        :disabled="readonly || busy || resolving"
        @click="toggle(item.id)"
      >
        <span class="approval-card-top">
          <span class="approval-kind"
            ><el-icon><Document /></el-icon
            >{{ kinds[item.approval_type] || item.approval_type }}</span
          >
          <span class="approval-status">{{
            states[item.status] || item.status
          }}</span>
        </span>
        <strong>{{ item.title }}</strong>
        <span class="approval-dates"
          >{{ item.start_date }} — {{ item.end_date }}</span
        >
        <span class="approval-card-bottom"
          ><span>{{ item.business_id }}</span
          ><span class="approval-selection"
            ><el-icon v-if="selected.includes(item.id)"><Check /></el-icon
            >{{ selected.includes(item.id) ? "已关联" : "点击关联" }}</span
          ></span
        >
      </button>
    </div>
    <div class="approval-footer">
      <span>已关联 {{ selected.length }} 条审批 · 可选择多条</span>
      <el-button
        v-if="!readonly"
        link
        type="primary"
        :aria-expanded="manualOpen"
        @click="manualOpen = !manualOpen"
        >{{ manualOpen ? "收起单号查找" : "未找到审批？按单号查找" }}</el-button
      >
    </div>
    <div v-if="manualOpen && !readonly" class="approval-lookup">
      <div class="approval-lookup-fields">
        <el-input
          v-model="businessNumber"
          aria-label="审批单号"
          placeholder="输入审批单号"
          :disabled="resolving || busy"
          @keyup.enter="
            businessNumber.trim() &&
            !resolving &&
            !busy &&
            emit('resolve', businessNumber.trim())
          "
        />
        <el-button
          :disabled="!businessNumber.trim() || busy"
          :loading="resolving"
          @click="emit('resolve', businessNumber.trim())"
          >查找并关联</el-button
        >
      </div>
      <p v-if="lookupError" role="alert" class="lookup-error">
        {{ lookupError }}
      </p>
    </div>
    <p class="approval-help">
      按报销归属人获取。差旅费用仍需逐行确认对应出差审批；项目制不按关键词强制关联。
    </p>
  </section>
</template>

<style scoped>
.approval-picker {
  width: 100%;
  min-width: 0;
}
.approval-heading,
.approval-footer,
.approval-card-top,
.approval-card-bottom,
.approval-lookup-fields {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.approval-heading {
  align-items: flex-start;
  margin-bottom: 14px;
}
.approval-heading strong {
  color: #20283d;
}
.approval-heading p,
.approval-help {
  color: #7b8498;
  font-size: 12px;
  line-height: 1.7;
  margin-top: 6px;
}
.approval-source {
  display: inline-block;
  margin-left: 10px;
  padding: 0 7px;
  background: #f0f4fa;
  border-radius: 4px;
  color: #71809a;
  font-size: 11px;
}
.approval-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px;
}
.approval-card {
  min-width: 0;
  padding: 14px;
  border: 1px solid #dce1e9;
  border-radius: 6px;
  background: #fff;
  color: #20283d;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 10px;
  line-height: 1.6;
}
.approval-card:hover:not(:disabled),
.approval-card.selected {
  border-color: #3b82f6;
  background: #f5f9ff;
}
.approval-card:disabled {
  cursor: default;
}
.approval-card strong {
  font-size: 13px;
  overflow-wrap: anywhere;
}
.approval-card-top,
.approval-card-bottom {
  width: 100%;
  font-size: 11px;
}
.approval-kind,
.approval-selection {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.approval-kind {
  color: #65738b;
}
.approval-status {
  color: #65738b;
  white-space: nowrap;
}
.approval-dates {
  color: #71809a;
  font-size: 12px;
}
.approval-card-bottom {
  margin-top: auto;
  border-top: 1px solid #edf0f5;
  padding-top: 10px;
  color: #8993a6;
  gap: 8px;
}
.approval-card-bottom > span:first-child {
  overflow-wrap: anywhere;
}
.approval-selection {
  flex-shrink: 0;
}
.selected .approval-selection {
  color: #3b82f6;
}
.approval-footer {
  margin-top: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #71809a;
}
.approval-message {
  background: #f7f8fb;
  padding: 14px;
  color: #71809a;
  border-radius: 6px;
  font-size: 12px;
}
.approval-lookup {
  padding: 12px;
  margin-top: 10px;
  background: #f7f8fb;
  border-radius: 6px;
}
.lookup-error {
  color: #bd4a42;
  font-size: 12px;
  margin-top: 7px;
}
.approval-help {
  margin-top: 12px;
}
@media (max-width: 600px) {
  .approval-heading {
    flex-wrap: wrap;
  }
  .approval-list {
    grid-template-columns: minmax(0, 1fr);
  }
  .approval-lookup-fields {
    flex-wrap: wrap;
  }
  .approval-lookup-fields .el-input {
    width: 100%;
  }
}
</style>
