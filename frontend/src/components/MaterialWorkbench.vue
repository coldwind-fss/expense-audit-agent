<script setup lang="ts">
import { ref } from "vue";
import {
  UploadFilled,
  Document,
  View,
  Delete,
  EditPen,
  Refresh,
} from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, currency, label, type Claim, type Material } from "../api/client";
import { useSession } from "../stores/session";
const session = useSession();
const props = defineProps<{ claim: Claim; readonly: boolean }>(),
  emit = defineEmits<{ changed: [] }>();
const loading = ref(false),
  sampleDialog = ref(false),
  samples = ref<any[]>([]),
  preview = ref<Material>(),
  page = ref(1),
  fileInput = ref<HTMLInputElement>(),
  uploadKind = ref("payment");
const roles: Record<string, string> = {
  payment: "付款凭证",
  tax_invoice: "税务发票",
  title_exempt_transport_receipt: "交通客票",
  supporting_document: "仅作佐证",
  unknown: "需人工核对",
};
async function upload(files: FileList | File[] | null) {
  if (!files) return;
  loading.value = true;
  try {
    for (const file of Array.from(files)) {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", uploadKind.value);
      await api("/claims/" + props.claim.id + "/materials", "POST", form);
    }
    emit("changed");
    ElMessage.success("材料已上传，正在逐份识别");
  } finally {
    loading.value = false;
    if (fileInput.value) fileInput.value.value = "";
  }
}
async function showSamples() {
  samples.value = (await api("/sample-materials")).items;
  sampleDialog.value = true;
}
async function useSample(sample: any) {
  loading.value = true;
  try {
    const r = await fetch(sample.url, { credentials: "include" });
    const blob = await r.blob();
    const form = new FormData();
    form.append(
      "file",
      new File([blob], sample.name + ".png", { type: "image/png" }),
    );
    form.append("kind", sample.kind);
    await api("/claims/" + props.claim.id + "/materials", "POST", form);
    emit("changed");
    ElMessage.success("合成样本已加入材料工作台");
  } finally {
    loading.value = false;
  }
}
async function bind(material: Material, lineId: string | null, kind: string) {
  loading.value = true;
  try {
    const fresh = await api<Claim>("/claims/" + props.claim.id);
    await api("/claims/" + props.claim.id + "/bindings", "PUT", {
      expected_revision: fresh.revision,
      bindings: [{ material_id: material.id, line_id: lineId || null, kind }],
    });
    emit("changed");
  } finally {
    loading.value = false;
  }
}
async function remove(m: Material) {
  await ElMessageBox.confirm(
    "删除后，该材料将不再参与本次报销核验。",
    "删除材料",
    { type: "warning" },
  );
  const c = await api<Claim>("/claims/" + props.claim.id);
  await api(
    "/materials/" + m.id + "?expected_revision=" + c.revision,
    "DELETE",
  );
  emit("changed");
}
async function rename(m: Material) {
  const { value } = await ElMessageBox.prompt("新的材料名称", "重命名", {
    inputValue: m.name,
    inputValidator: (v) => !!v.trim() || "请输入名称",
  });
  await api("/materials/" + m.id, "PATCH", { name: value });
  emit("changed");
}
async function confirmAmount(m: Material) {
  const { value } = await ElMessageBox.prompt(
    "请查看原件，确认实际付款金额。此值不会修改发票事实。",
    "人工确认付款金额",
    {
      inputValue: m.manual_amount || "",
      inputPattern: /^\d+(\.\d{1,2})?$/,
      inputErrorMessage: "请输入最多两位小数的金额",
    },
  );
  const c = await api<Claim>("/claims/" + props.claim.id);
  await api("/materials/" + m.id + "/decisions", "POST", {
    expected_revision: c.revision,
    manual_amount: value,
  });
  emit("changed");
}
async function retry(m: Material) {
  const c = await api<Claim>("/claims/" + props.claim.id);
  await api(
    "/materials/" + m.id + (m.page_count ? "/extract" : "/prepare"),
    "POST",
    { expected_revision: c.revision },
  );
  emit("changed");
  ElMessage.success("已重新排入识别队列");
}
async function duplicate(m: Material, value: string) {
  const c = await api<Claim>("/claims/" + props.claim.id);
  await api("/materials/" + m.id + "/decisions", "POST", {
    expected_revision: c.revision,
    duplicate_decision: value,
  });
  emit("changed");
}
function showPreview(m: Material) {
  preview.value = m;
  page.value = 1;
}
</script>
<template>
  <div v-if="!readonly" class="materials-toolbar" style="margin-bottom: 15px">
    <el-select
      v-model="uploadKind"
      style="width: 135px"
      aria-label="上传材料类别"
      ><el-option label="付款截图" value="payment" /><el-option
        label="发票票据"
        value="invoice" /><el-option
        label="其他附件"
        value="other" /></el-select
    ><el-button :loading="loading" @click="showSamples">选择合成样本</el-button
    ><span class="field-help" style="margin: 0">{{
      session.me?.model_mode === "provider"
        ? "材料将由已配置模型读取，无法确定的内容保留人工确认"
        : "任意新图在未接模型时会明确提示未识别"
    }}</span>
  </div>
  <div
    v-if="!readonly"
    class="upload-zone"
    role="button"
    tabindex="0"
    @click="fileInput?.click()"
    @keydown.enter="fileInput?.click()"
    @dragover.prevent
    @drop.prevent="upload(Array.from($event.dataTransfer?.files || []))"
  >
    <el-icon><UploadFilled /></el-icon
    ><strong>{{ loading ? "正在上传材料…" : "点击或拖入报销材料" }}</strong>
    <p>PNG / JPG / WebP / PDF · 单份 50 MB 以内 · Office 仅作其他附件</p>
    <input
      ref="fileInput"
      type="file"
      multiple
      hidden
      accept="image/png,image/jpeg,image/webp,application/pdf,.docx,.xlsx"
      @change="upload(($event.target as HTMLInputElement).files)"
    />
  </div>
  <div class="notice" v-if="claim.materials.length">
    先识别，再由您将每份材料分配到实际费用。每份材料只归属一条明细；支持金额将随有效付款更新，人工填写的申报金额会保留。
  </div>
  <div class="material-grid">
    <article v-for="m in claim.materials" :key="m.id" class="material-card">
      <div class="material-preview" @click="showPreview(m)">
        <img
          v-if="m.page_count"
          :src="'/api/v1/materials/' + m.id + '/preview?page=1'"
          :alt="m.name"
        /><el-icon v-else style="font-size: 40px; color: #a4b3cc; margin: auto"
          ><Document /></el-icon
        ><span class="status-chip" :class="m.status">{{
          label(m.status)
        }}</span>
      </div>
      <div class="material-meta">
        <div class="material-name">
          <strong :title="m.name">{{ m.name }}</strong
          ><el-button
            v-if="!readonly"
            link
            :icon="EditPen"
            aria-label="重命名"
            @click="rename(m)"
          />
        </div>
        <div class="material-facts">
          <span class="money">{{
            m.status === "recognized"
              ? currency(m.manual_amount ?? m.facts.countable_amount)
              : "—"
          }}</span
          ><span>{{
            m.manual_amount
              ? "人工确认实付"
              : roles[m.facts.document_role || ""] || "等待识别"
          }}</span>
        </div>
        <p
          v-if="m.facts.business_date"
          class="field-help"
          style="margin-bottom: 10px"
        >
          {{ m.facts.date_type === "invoice_issue" ? "开票日期" : "材料日期" }}
          {{ m.facts.business_date
          }}<span v-if="m.facts.refund_amount">
            · 含退款 {{ currency(m.facts.refund_amount) }}</span
          >
        </p>
        <p v-if="m.error" class="material-warning">{{ m.error }}</p>
        <p v-if="m.facts.payment_status === 'unpaid'" class="material-warning">
          订单未付款，不能计入实付金额
        </p>
        <p v-if="m.duplicate_of" class="material-warning">
          {{
            m.duplicate_kind === "exact"
              ? "已确认同一凭证，重复部分不计入"
              : "疑似重复，请核对"
          }}
          <el-button
            v-if="!readonly && m.duplicate_kind !== 'exact'"
            link
            type="primary"
            @click="duplicate(m, 'same')"
            >同一份</el-button
          ><el-button
            v-if="!readonly && m.duplicate_kind !== 'exact'"
            link
            type="primary"
            @click="duplicate(m, 'different')"
            >不同凭证</el-button
          >
        </p>
        <div class="material-fields">
          <el-select
            :model-value="m.kind"
            :disabled="readonly || loading"
            size="small"
            aria-label="材料类别"
            @change="(v: string) => bind(m, m.line_id, v)"
            ><el-option label="付款" value="payment" /><el-option
              label="发票"
              value="invoice" /><el-option
              label="佐证"
              value="other" /></el-select
          ><el-select
            :model-value="m.line_id || ''"
            :disabled="readonly || loading"
            size="small"
            aria-label="分配到费用明细"
            @change="(v: string) => bind(m, v, m.kind)"
            ><el-option label="尚未分配" value="" /><el-option
              v-for="(line, index) in claim.lines"
              :key="line.id"
              :value="line.id"
              :label="
                '明细 ' + (index + 1) + ' · ' + (line.reason || '未填写事由')
              "
          /></el-select>
        </div>
        <div class="material-actions">
          <el-button link size="small" :icon="View" @click="showPreview(m)"
            >查看依据</el-button
          ><el-button
            v-if="
              !readonly &&
              m.kind === 'payment' &&
              ['payment', 'unknown'].includes(m.facts.document_role || '') &&
              m.facts.payment_status !== 'unpaid'
            "
            link
            size="small"
            type="primary"
            @click="confirmAmount(m)"
            >确认实付</el-button
          ><el-button
            v-if="
              !readonly &&
              (m.status === 'failed' ||
                (m.status === 'recognized' &&
                  m.facts.execution_mode !== session.me?.model_mode))
            "
            link
            size="small"
            :icon="Refresh"
            @click="retry(m)"
            >{{
              m.status === "recognized" ? "按当前模型重新识别" : "重试"
            }}</el-button
          ><el-button
            v-if="!readonly"
            link
            size="small"
            :icon="Delete"
            aria-label="删除材料"
            @click="remove(m)"
          />
        </div>
      </div>
    </article>
  </div>
  <div v-if="!claim.materials.length" class="empty">
    <p>上传发票、付款截图或业务佐证，识别结果将在这里逐份呈现。</p>
  </div>
  <el-dialog
    v-model="sampleDialog"
    title="选择合成业务材料"
    width="min(700px, 95vw)"
    ><div class="notice">
      这些材料全部为合成样本，可通过同一上传、识别、分配和审核链路体验。请选择与本次费用相关的材料。
    </div>
    <div class="sample-grid">
      <article v-for="s in samples" :key="s.key" class="sample-card">
        <img :src="s.url" :alt="s.name" /><strong>{{ s.name }}</strong>
        <p>{{ s.description }}</p>
        <el-button size="small" :loading="loading" @click="useSample(s)"
          >加入本次报销</el-button
        >
      </article>
    </div></el-dialog
  >
  <el-dialog
    :model-value="!!preview"
    :title="preview?.name || '材料预览'"
    width="min(800px, 95vw)"
    @close="preview = undefined"
    ><template v-if="preview"
      ><img
        v-if="preview.page_count"
        class="preview-image"
        :src="'/api/v1/materials/' + preview.id + '/preview?page=' + page"
        :alt="preview.name"
      /><el-pagination
        v-if="preview.page_count > 1"
        v-model:current-page="page"
        :page-size="1"
        :total="preview.page_count"
        layout="prev,pager,next"
      />
      <p v-if="!preview.page_count" class="preview-caption">
        Office 文件仅作附件保存，不进行自动识别。<a
          :href="'/api/v1/materials/' + preview.id + '/preview'"
          target="_blank"
          rel="noopener"
          >下载原件</a
        >
      </p>
      <p class="preview-caption">
        来源：{{
          preview.facts.execution_mode === "fixture"
            ? "登记合成样本"
            : preview.facts.execution_mode === "provider"
              ? "真实多模态模型"
              : "上传原件"
        }}
        · 事实版本 {{ preview.fact_version }} · {{ preview.page_count }} 页
      </p>
      <pre class="detail-code">{{
        JSON.stringify(preview.facts, null, 2)
      }}</pre>
    </template></el-dialog
  >
</template>
