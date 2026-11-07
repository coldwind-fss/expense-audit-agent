<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api/client";
const token = ref(""),
  data = ref<any>(),
  error = ref(""),
  difficulty = ref(""),
  priority = ref(""),
  suggestion = ref(""),
  done = ref(false),
  busy = ref(false);
const names: Record<string, string> = {
  rules: "规则难理解",
  steps: "步骤较多",
  hints: "提示不清楚",
  recognition: "识别不准确",
  smooth: "整体顺畅",
  other: "其他",
  uploads: "上传和附件分配",
  details: "费用填写",
  company_account: "公司与账户",
  approvals: "关联审批",
  validation: "校验与问题处理",
  none: "暂不需要改进",
};
onMounted(async () => {
  token.value = new URLSearchParams(location.hash.slice(1)).get("token") || "";
  history.replaceState(null, "", location.pathname);
  try {
    data.value = await api(
      "/feedback/resolve",
      "POST",
      { token: token.value },
      { silent: true },
    );
    done.value = data.value.submitted;
  } catch (e) {
    error.value = (e as Error).message;
  }
});
async function submit() {
  busy.value = true;
  try {
    await api("/feedback/answers", "POST", {
      token: token.value,
      difficulty: difficulty.value,
      priority: priority.value,
      suggestion: suggestion.value,
    });
    done.value = true;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <section class="feedback-card">
    <div class="eyebrow">循证 · 使用反馈</div>
    <h1>{{ done ? "感谢您的反馈" : "让报销体验更顺手" }}</h1>
    <p v-if="error">{{ error }}</p>
    <template v-else-if="done"
      ><p>本次反馈已记录，同一邀请只保存一份答卷。</p>
      <div class="notice">这是本地合成体验，不涉及真实员工通知。</div></template
    ><template v-else-if="data"
      ><p>{{ data.name }}，请用一分钟分享您的使用感受。</p>
      <el-form label-position="top"
        ><el-form-item label="1. 使用过程中，您主要遇到什么困难？" required
          ><el-radio-group v-model="difficulty"
            ><el-radio
              v-for="item in data.difficulties"
              :key="item"
              :value="item"
              >{{ names[item] || item }}</el-radio
            ></el-radio-group
          ></el-form-item
        ><el-form-item label="2. 您最希望优先改进哪一部分？" required
          ><el-radio-group v-model="priority"
            ><el-radio
              v-for="item in data.priorities"
              :key="item"
              :value="item"
              >{{ names[item] || item }}</el-radio
            ></el-radio-group
          ></el-form-item
        ><el-form-item label="其他建议（可选）"
          ><el-input
            v-model="suggestion"
            type="textarea"
            :rows="4"
            maxlength="500"
            show-word-limit /></el-form-item></el-form
      ><el-button
        type="primary"
        style="width: 100%"
        :disabled="!difficulty || !priority"
        :loading="busy"
        @click="submit"
        >提交反馈</el-button
      >
      <p class="field-help" style="margin-top: 16px">
        {{ data.identity_note }} · 合成体验
      </p></template
    ><el-skeleton v-else-if="!error" :rows="5" animated />
  </section>
</template>
