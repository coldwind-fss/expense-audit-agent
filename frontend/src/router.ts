import { createRouter, createWebHistory } from "vue-router";
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: () => import("./pages/ClaimsPage.vue") },
    { path: "/claims/:id", component: () => import("./pages/ClaimEditor.vue") },
    { path: "/history", component: () => import("./pages/HistoryPage.vue") },
    { path: "/admin", component: () => import("./pages/AdminPage.vue") },
    { path: "/feedback", component: () => import("./pages/FeedbackPage.vue") },
  ],
});
