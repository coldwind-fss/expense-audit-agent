import { ElMessage } from "element-plus";
import Decimal from "decimal.js";
import type { components } from "./generated";

export type Claim = Omit<
  components["schemas"]["ClaimView"],
  "lines" | "materials"
> & { lines: Line[]; materials: Material[] };
export type Line = Omit<components["schemas"]["LineView"], "sources"> & {
  sources: Record<
    string,
    { kind: string; batch_id?: string; evidence?: string[] }
  >;
};
export interface Facts {
  document_role?: string;
  countable_amount?: string;
  business_date?: string;
  date_type?: string;
  refund_amount?: string;
  payment_status?: string;
  execution_mode?: string;
  [key: string]: unknown;
}
export type Material = Omit<components["schemas"]["MaterialView"], "facts"> & {
  facts: Facts;
};
export interface Actor {
  id: string;
  name: string;
  role: string;
  persona: string;
  can_on_behalf: boolean;
  invoice_only: boolean;
  social_company_id: string;
}
export interface Session {
  model_profile?: { provider: string; model: string; mode: string };
  provider_configured?: boolean;
  csrf_token: string;
  actor: Actor;
  personas: { key: string; name: string; role: string }[];
  model_mode: string;
  enterprise_mode: string;
  workspace_id: string;
}
export interface Catalog {
  workflows: { key: string; label: string; description: string }[];
  companies: { id: string; name: string }[];
  departments: { id: string; name: string }[];
  projects: string[];
  expense_types: string[];
  invoice_types: string[];
}
export interface RelatedApproval {
  id: string;
  business_id: string;
  title: string;
  approval_type: string;
  employee_id: string;
  start_date: string;
  end_date: string;
  status: string;
  adapter_mode: string;
}
export interface Check {
  check_id: string;
  rule_id: string;
  scope: string;
  label: string;
  status: string;
  severity: string;
  message: string;
  evidence_refs: string[];
  next_action: string;
  blocks_submission: boolean;
}
export interface Report {
  id: string;
  input_revision: number;
  valid: boolean;
  can_submit: boolean;
  checks: Check[];
  summary: {
    blocking: number;
    warnings: number;
    checked: number;
    declared_amount: string;
  };
  execution_mode: string;
}
export interface Run {
  execution_mode: string;
  id: string;
  run_id: string;
  task_kind: string;
  status: string;
  error: string;
  stop_reason: string;
  input_revision: number;
  output: { batch_id?: string; report_id?: string };
  question: {
    kind?: string;
    question_id?: string;
    text?: string;
    candidates?: string[];
  };
  model_calls: number;
  tool_calls: number;
  steps?: { node: string; detail: Record<string, unknown>; at: string }[];
}
export interface Batch {
  id: string;
  input_revision: number;
  status: string;
  outdated: boolean;
  items: {
    line_id: string;
    field: string;
    value: string;
    previous_value: string | null;
    protected: boolean;
    evidence_refs: string[];
    source_description: string;
  }[];
}
export interface Submission {
  simulated_approval_state?: string;
  id: string;
  claim_id: string;
  title: string;
  status: string;
  workflow_key: string;
  total_amount: string;
  created_at: string;
  scheduled_at: string;
  dispatched_at: string | null;
  simulated_reference: string | null;
  failure: string;
  adapter_mode: string;
  snapshot?: { claim: Claim };
}
let csrf = "";
let actionReason = "";
export function setActionReason(value: string) {
  actionReason = value;
}
export function setCSRF(value: string) {
  csrf = value;
}
export class APIError extends Error {
  constructor(
    public code: string,
    message: string,
    public details: unknown[] = [],
  ) {
    super(message);
  }
}
export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
  options: { silent?: boolean; key?: string } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") {
    headers["X-CSRF-Token"] = csrf;
    headers["Idempotency-Key"] = options.key || crypto.randomUUID();
    if (actionReason)
      headers["X-Action-Reason"] = encodeURIComponent(actionReason);
  }
  if (body && !(body instanceof FormData))
    headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch("/api/v1" + path, {
      method,
      headers,
      credentials: "include",
      body:
        body instanceof FormData
          ? body
          : body === undefined
            ? undefined
            : JSON.stringify(body),
    });
  } catch {
    if (!options.silent) ElMessage.error("连接中断，请检查服务后重试");
    throw new APIError("NETWORK_ERROR", "服务暂时不可用");
  }
  const data = await response.json();
  if (!response.ok) {
    const e = data.error || {};
    if (!options.silent) ElMessage.error(e.message || "操作未完成");
    throw new APIError(e.code || "ERROR", e.message || "操作未完成", e.details);
  }
  return data;
}
export const statusLabel: Record<string, string> = {
  draft: "草稿",
  submitted: "已提交",
  scheduled: "等待发起",
  dispatching: "正在发起",
  retry: "等待重试",
  unknown: "结果待核对",
  manual: "待人工处理",
  succeeded: "模拟 OA 已创建",
  cancelled: "已撤销",
  queued: "排队中",
  running: "处理中",
  waiting_input: "等待您确认",
  completed: "已完成",
  failed: "处理失败",
  outdated: "结果已过期",
  done: "已完成",
  paused: "已暂停",
  recognized: "已识别",
  ready_for_extraction: "等待识别",
  stored: "已保存",
  proposed: "待确认",
  applied: "已回填",
  undone: "已撤回",
  audited: "已审计",
  needs_attention: "待核对",
  simulated_synced: "已模拟同步",
  simulated_sent: "模拟邀请已生成",
  rolled_back: "已回滚",
};
export function label(status: string) {
  return statusLabel[status] || status;
}
export function currency(value: unknown) {
  const [whole, fraction] = new Decimal(String(value || "0"))
    .toFixed(2)
    .split(".");
  return "¥ " + whole!.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "." + fraction;
}
export function dateTime(value: string | null) {
  return value
    ? new Date(value).toLocaleString("zh-CN", { hour12: false })
    : "—";
}
