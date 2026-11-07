import { defineStore } from "pinia";
import { ref } from "vue";
import { api, setCSRF, type Session, type Catalog } from "../api/client";

export const useSession = defineStore("session", () => {
  const me = ref<Session>();
  const catalog = ref<Catalog>();
  const ready = ref(false);
  async function init() {
    me.value = await api<Session>("/experience/sessions", "POST");
    setCSRF(me.value.csrf_token);
    catalog.value = await api<Catalog>("/catalogs");
    ready.value = true;
  }
  async function persona(key: string) {
    me.value = await api<Session>("/experience/persona", "POST", {
      persona: key,
    });
    setCSRF(me.value.csrf_token);
    catalog.value = await api<Catalog>("/catalogs");
  }
  return { me, catalog, ready, init, persona };
});
