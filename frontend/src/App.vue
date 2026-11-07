<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  Document,
  Clock,
  Setting,
  ArrowRight,
  Grid,
  Switch,
  ChatLineRound,
} from "@element-plus/icons-vue";
import { useSession } from "./stores/session";
const session = useSession(),
  route = useRoute(),
  router = useRouter(),
  error = ref("");
async function load() {
  error.value = "";
  try {
    await session.init();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
async function changePersona(key: string) {
  await session.persona(key);
  await router.push("/");
  router.go(0);
}
onMounted(load);
</script>
<template>
  <div v-if="route.path === '/feedback'" class="feedback-shell">
    <RouterView />
  </div>
  <div v-else class="app-shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/"
        ><span class="brand-mark">循</span
        ><span
          >循证<span class="brand-sub">智能报销工作台</span></span
        ></RouterLink
      >
      <div class="nav-caption">工作空间</div>
      <nav>
        <RouterLink
          to="/"
          :class="{
            active: route.path === '/' || route.path.startsWith('/claims/'),
          }"
          ><el-icon><Grid /></el-icon>报销工作台<el-icon class="nav-arrow"
            ><ArrowRight /></el-icon
        ></RouterLink>
        <RouterLink to="/history"
          ><el-icon><Clock /></el-icon>提交记录</RouterLink
        >
        <RouterLink v-if="session.me?.actor.role === 'admin'" to="/admin"
          ><el-icon><Setting /></el-icon>系统管理</RouterLink
        >
      </nav>
      <div class="sidebar-note">
        <el-icon><Document /></el-icon><strong>每一笔，都有依据</strong>
        <p>材料识别 · 字段建议 · 整单审核<br />真实用途与材料归属由您确认</p>
      </div>
      <div class="sidebar-bottom">
        <span class="status-dot"></span>独立体验空间<span>v0.1</span>
      </div>
    </aside>
    <section class="main-shell">
      <header class="topbar">
        <div class="breadcrumb">
          工作空间 <span>/</span>
          {{
            route.path === "/admin"
              ? "系统管理"
              : route.path === "/history"
                ? "提交记录"
                : "报销工作台"
          }}
        </div>
        <div class="top-actions">
          <span class="mode-pill"
            ><span class="status-dot"></span
            >{{
              session.me?.model_mode === "provider"
                ? "真实模型识别"
                : session.me?.model_mode === "disabled"
                  ? "模型未启用"
                  : "合成样本模式"
            }}</span
          ><el-dropdown v-if="session.me" @command="changePersona"
            ><button class="persona-button">
              <span class="avatar">{{ session.me.actor.name[0] }}</span
              >{{ session.me.actor.name }}<el-icon><Switch /></el-icon></button
            ><template #dropdown
              ><el-dropdown-menu
                ><el-dropdown-item
                  v-for="p in session.me.personas"
                  :key="p.key"
                  :command="p.key"
                  >{{ p.name }} ·
                  {{ p.role === "admin" ? "管理员" : "员工" }}</el-dropdown-item
                ></el-dropdown-menu
              ></template
            ></el-dropdown
          >
        </div>
      </header>
      <div class="mode-banner">
        <el-icon><ChatLineRound /></el-icon
        ><span>{{
          session.me?.model_mode === "provider"
            ? "当前由 " +
              (session.me.model_profile?.model || "多模态模型") +
              " 识别材料并辅助审核；OA仍为本地模拟，不连接原公司。"
            : session.me?.model_mode === "disabled"
              ? "当前模型未启用，新材料不会自动识别。"
              : "当前使用登记合成样本识别与本地模拟 OA，可完整操作报销流程。任意新材料需接入真实模型后识别。"
        }}</span>
      </div>
      <main class="page-body">
        <div v-if="error" class="panel empty">
          <h2>暂时无法连接服务</h2>
          <p>{{ error }}</p>
          <el-button type="primary" @click="load">重新连接</el-button>
        </div>
        <RouterView v-else-if="session.ready" :key="route.path" /><el-skeleton
          v-else
          :rows="8"
          animated
        />
      </main>
      <footer class="site-footer">
        循证 · 让报销审核有据可循 <span>独立空间 · 企业服务未连接</span>
      </footer>
    </section>
  </div>
</template>
