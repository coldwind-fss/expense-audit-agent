<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import {
  Plus,
  Document,
  FolderOpened,
  Position,
  Box,
  ArrowRight,
  Search,
} from "@element-plus/icons-vue";
import { api, currency, dateTime, label } from "../api/client";
import { useSession } from "../stores/session";
const session = useSession(),
  router = useRouter(),
  rows = ref<any[]>([]),
  search = ref(""),
  busy = ref(false),
  selected = ref("daily"),
  dialog = ref(false),
  title = ref(""),
  routeMode = ref("self"),
  subject = ref(""),
  people = ref<any[]>([]),
  cursor = ref<number | null>(null);
const filtered = computed(() =>
  rows.value.filter((c) => c.title.includes(search.value)),
);
const icons = [Document, Document, Position, FolderOpened, Box];
async function load(more = false) {
  const result = await api("/claims?cursor=" + (more ? cursor.value : 0));
  rows.value = more ? [...rows.value, ...result.items] : result.items;
  cursor.value = result.next_cursor;
}
function choose(key: string) {
  selected.value = key;
  title.value = "";
  dialog.value = true;
}
async function create() {
  busy.value = true;
  try {
    const c = await api("/claims", "POST", {
      workflow_key: selected.value,
      title:
        title.value ||
        session.catalog!.workflows.find((w) => w.key === selected.value)!.label,
      route_mode: routeMode.value,
      subject_id: subject.value || null,
    });
    await router.push("/claims/" + c.id);
  } finally {
    busy.value = false;
  }
}
onMounted(async () => {
  await load();
  people.value = (await api("/employees")).items;
});
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">REIMBURSEMENT WORKSPACE</div>
      <h1>报销工作台</h1>
      <p>从真实费用出发，填写、识别、核验，一步步完成报销。</p>
    </div>
    <el-button type="primary" :icon="Plus" @click="choose('daily')"
      >新建报销</el-button
    >
  </div>
  <div class="section-heading">
    <h2>选择报销入口</h2>
    <span>按费用性质分别填报</span>
  </div>
  <div class="entry-grid">
    <button
      v-for="(w, index) in session.catalog?.workflows"
      :key="w.key"
      class="entry-card"
      @click="choose(w.key)"
    >
      <span class="entry-icon" :class="'entry-' + index"
        ><el-icon><component :is="icons[index]" /></el-icon></span
      ><strong>{{ w.label }}</strong>
      <p>{{ w.description }}</p>
      <span class="entry-action"
        >开始填报 <el-icon><ArrowRight /></el-icon
      ></span>
    </button>
  </div>
  <section class="panel draft-panel">
    <div class="panel-heading">
      <div>
        <h2>我的报销</h2>
        <p>草稿自动保存，可随时继续填写</p>
      </div>
      <el-input
        v-model="search"
        :prefix-icon="Search"
        placeholder="搜索报销标题"
        class="search-input"
        clearable
      />
    </div>
    <el-table
      :data="filtered"
      @row-click="(row: any) => router.push('/claims/' + row.id)"
      class="clickable-table"
      ><el-table-column label="报销事项" min-width="230"
        ><template #default="{ row }"
          ><div class="table-title">
            <span class="file-icon"
              ><el-icon><Document /></el-icon
            ></span>
            <div>
              <strong>{{ row.title }}</strong
              ><small>{{
                session.catalog?.workflows.find(
                  (w) => w.key === row.workflow_key,
                )?.label
              }}</small>
            </div>
          </div></template
        ></el-table-column
      ><el-table-column label="申报金额" min-width="140"
        ><template #default="{ row }"
          ><span class="money">{{ currency(row.total_amount) }}</span></template
        ></el-table-column
      ><el-table-column label="状态" width="130"
        ><template #default="{ row }"
          ><span class="status-chip" :class="row.status">{{
            label(row.status)
          }}</span></template
        ></el-table-column
      ><el-table-column label="最后更新" min-width="190"
        ><template #default="{ row }"
          ><span class="muted">{{ dateTime(row.updated_at) }}</span></template
        ></el-table-column
      ><el-table-column width="90"
        ><template #default="{ row }"
          ><el-button link type="primary"
            >{{ row.status === "draft" ? "继续填写" : "查看"
            }}<el-icon
              ><ArrowRight /></el-icon></el-button></template></el-table-column
      ><template #empty
        ><div class="empty">
          <div class="empty-icon">
            <el-icon><FolderOpened /></el-icon>
          </div>
          <h3>还没有报销记录</h3>
          <p>选择上方入口，开始填写第一笔报销。</p>
          <el-button type="primary" :icon="Plus" @click.stop="choose('daily')"
            >新建报销</el-button
          >
        </div></template
      ></el-table
    >
    <div v-if="cursor" class="load-more">
      <el-button @click="load(true)">加载更多</el-button>
    </div>
  </section>
  <div class="workflow-note">
    <span class="mini-number">1</span>填写费用 <span>—</span
    ><span class="mini-number">2</span>上传与分配材料 <span>—</span
    ><span class="mini-number">3</span>确认建议与审核 <span>—</span
    ><span class="mini-number">4</span>提交并跟踪
  </div>
  <el-dialog v-model="dialog" title="新建报销" width="min(540px, 94vw)"
    ><el-form label-position="top"
      ><el-form-item label="报销入口"
        ><el-select v-model="selected"
          ><el-option
            v-for="w in session.catalog?.workflows"
            :key="w.key"
            :label="w.label"
            :value="w.key" /></el-select></el-form-item
      ><el-form-item label="报销标题"
        ><el-input
          v-model="title"
          placeholder="例如：十一月办公用品采购"
          maxlength="200" /></el-form-item
      ><el-form-item label="填报身份"
        ><el-radio-group v-model="routeMode"
          ><el-radio value="self">本人报销</el-radio
          ><el-radio v-if="session.me?.actor.can_on_behalf" value="on_behalf"
            >代他人填报</el-radio
          ></el-radio-group
        ></el-form-item
      ><el-form-item v-if="routeMode !== 'self'" label="报销归属人"
        ><el-select v-model="subject"
          ><el-option
            v-for="p in people"
            :key="p.id"
            :label="p.name"
            :value="p.id"
        /></el-select>
        <p class="field-help">
          普通代报由当前操作人发起 OA，费用归属所选员工。
        </p></el-form-item
      ></el-form
    ><template #footer
      ><el-button @click="dialog = false">取消</el-button
      ><el-button type="primary" :loading="busy" @click="create"
        >创建并填写</el-button
      ></template
    ></el-dialog
  >
</template>
