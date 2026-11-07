import { test, expect, type Page } from "@playwright/test";

async function seed(page: Page, mode: string) {
  await page.goto("/");
  await expect(page.locator(".entry-card").first()).toBeVisible();
  let me = await (await page.request.get("/api/v1/me")).json();
  async function post(path: string, data: unknown, method = "POST") {
    const response = await page.request.fetch("/api/v1" + path, {
      method,
      data,
      headers: {
        "X-CSRF-Token": me.csrf_token,
        "Idempotency-Key": crypto.randomUUID(),
      },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  }
  if (["supply_chain", "admin_originator"].includes(mode))
    me = await post("/experience/persona", { persona: "admin" });
  const people = (await (await page.request.get("/api/v1/employees")).json())
    .items;
  const subject = people.find((p: any) => p.name === "林悦");
  let claim: any, caseId: string | undefined;
  if (mode === "admin_originator") {
    const c = await post("/admin/cases/manual", {
      subject_id: subject.id,
      title: "管理员协助报销验收",
      reason: "协助员工整理真实费用",
    });
    caseId = c.id;
    claim = await (
      await page.request.get("/api/v1/claims/" + c.claim_id)
    ).json();
  } else
    claim = await post("/claims", {
      workflow_key: mode,
      title: mode + "业务验收",
      route_mode: mode === "no_invoice" ? "on_behalf" : "self",
      subject_id: mode === "no_invoice" ? subject.id : null,
    });
  const approvals = (
    await (
      await page.request.get(
        "/api/v1/related-approvals?employee_id=" + claim.subject_id,
      )
    ).json()
  ).items;
  claim = await post("/claims/" + claim.id + "/lines", {
    expected_revision: claim.revision,
    reason: mode === "project" ? "项目内出差活动费用" : "日常业务支出",
    project: "日常运营",
    expense_type: mode === "travel" ? "差旅" : "",
    invoice_type: mode === "no_invoice" ? "无" : "电子普票",
    related_id:
      mode === "travel"
        ? approvals.find((a: any) => a.approval_type === "travel").id
        : null,
  });
  const lineId = claim.lines[0].id;
  const keys =
    mode === "travel"
      ? ["payment_refund", "rail_ticket"]
      : mode === "supply_chain"
        ? ["invoice_meal"]
        : mode === "no_invoice"
          ? ["payment_meal"]
          : ["payment_meal", "invoice_meal"];
  for (const key of keys) {
    const content = await page.request.get("/api/v1/sample-materials/" + key);
    const response = await page.request.post(
      "/api/v1/claims/" + claim.id + "/materials",
      {
        headers: { "X-CSRF-Token": me.csrf_token },
        multipart: {
          kind:
            key.includes("invoice") || key === "rail_ticket"
              ? "invoice"
              : "payment",
          target_line_id: lineId,
          file: {
            name: key + ".png",
            mimeType: "image/png",
            buffer: await content.body(),
          },
        },
      },
    );
    expect(response.status()).toBe(201);
  }
  await expect
    .poll(async () => {
      claim = await (
        await page.request.get("/api/v1/claims/" + claim.id)
      ).json();
      return claim.materials.filter((m: any) => m.status === "recognized")
        .length;
    })
    .toBe(keys.length);
  claim = await post(
    "/claims/" + claim.id + "/lines/" + lineId,
    {
      expected_revision: claim.revision,
      business_date: claim.materials[0].facts.business_date,
      ...(mode === "travel" ? { amount: "141.00" } : {}),
    },
    "PATCH",
  );
  const account = await post("/recipient-accounts", {
    label: "合成收款账户",
    value: "SYNTHETIC-CASE-0001",
  });
  claim = await post(
    "/claims/" + claim.id,
    {
      expected_revision: claim.revision,
      account_id: account.id,
      total_amount: mode === "travel" ? "141.00" : "88.00",
    },
    "PATCH",
  );
  if (mode === "no_invoice") expect(claim.originator_id).toBe(me.actor.id);
  if (mode === "admin_originator") expect(claim.originator_id).toBe(subject.id);
  await page.goto("/claims/" + claim.id);
  return { claim, caseId, post };
}

test("人工总额独立保存，与明细不符时阻止，改正重审后提交", async ({ page }) => {
  const { claim } = await seed(page, "daily");
  const total = page.getByRole("textbox", {
    name: "本次申报总金额（元）",
    exact: true,
  });
  await total.fill("100.00");
  await total.blur();
  await expect(
    page.getByText("总额与明细不一致，需核对后才能提交。", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(total).toHaveValue("100.00");
  const saved = await (
    await page.request.get("/api/v1/claims/" + claim.id)
  ).json();
  expect(saved.total_amount).toBe("100.00");
  expect(saved.lines[0].amount).toBe("88.00");
  expect(saved.total_auto).toBe(false);
  await page.screenshot({
    path: "test-results/manual-total-form.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.locator(".amount-comparison").getByText("人工申报", { exact: true }),
  ).toBeVisible();
  await expect(
    page.locator(".amount-comparison").getByText("明细合计", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/manual-total-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator(".step-button").nth(4).click();
  await page.getByRole("button", { name: "开始整单审核" }).click();
  await expect(page.getByRole("heading", { name: /项需要处理/ })).toBeVisible();
  await expect(
    page.getByText("人工申报 100.00 元 / 明细合计 88.00 元 / 差额 12.00 元", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "确认提交", exact: true }),
  ).toBeDisabled();
  await page.screenshot({
    path: "test-results/manual-total-blocked.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "修改申报总金额", exact: true })
    .click();
  await expect(total).toBeFocused();
  await total.fill("88.00");
  await total.blur();
  await page.locator(".step-button").nth(4).click();
  await expect(
    page.getByText("申报已发生变化，本报告已失效。请重新审核后提交。"),
  ).toBeVisible();
  await page.getByRole("button", { name: "开始整单审核" }).click();
  await expect(
    page.getByRole("heading", { name: "已满足本次提交条件" }),
  ).toBeVisible();
  await expect(
    page.getByText("人工申报 88.00 元 / 明细合计 88.00 元 / 差额 0.00 元", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await page
    .getByRole("dialog", { name: "确认提交" })
    .getByRole("button", { name: "确认提交", exact: true })
    .click();
  await expect(page.getByText("模拟 OA 已创建", { exact: true })).toBeVisible();
});

test("错抬头阻止提交，修改公司使旧报告失效，重新审核后提交", async ({
  page,
}) => {
  const { claim, post } = await seed(page, "daily");
  const catalog = await (await page.request.get("/api/v1/catalogs")).json();
  const wrong = catalog.companies.find(
    (c: any) => c.name === "青禾供应链有限公司",
  );
  await post(
    "/claims/" + claim.id,
    {
      expected_revision: claim.revision,
      company_id: wrong.id,
    },
    "PATCH",
  );
  await page.reload();
  await page.locator(".step-button").nth(4).click();
  await page.getByRole("button", { name: "开始整单审核" }).click();
  await expect(page.getByRole("heading", { name: /项需要处理/ })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "确认提交", exact: true }),
  ).toBeDisabled();
  await page.locator(".step-button").nth(0).click();
  await page
    .getByRole("combobox", { name: "付款公司", exact: true })
    .press("Enter");
  await page
    .getByRole("option", { name: "青禾科技有限公司", exact: true })
    .click();
  await page.locator(".step-button").nth(4).click();
  await expect(
    page.getByText("申报已发生变化，本报告已失效。请重新审核后提交。"),
  ).toBeVisible();
  await page.getByRole("button", { name: "开始整单审核" }).click();
  await expect(
    page.getByRole("heading", { name: "已满足本次提交条件" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await page
    .getByRole("dialog", { name: "确认提交" })
    .getByRole("button", { name: "确认提交", exact: true })
    .click();
  await expect(page.getByText("模拟 OA 已创建", { exact: true })).toBeVisible();
});

for (const mode of [
  "no_invoice",
  "travel",
  "project",
  "supply_chain",
  "admin_originator",
]) {
  test(mode + " 在产品页面完成审核与提交", async ({ page }) => {
    const { claim, caseId } = await seed(page, mode);
    await expect(
      page.getByRole("heading", { name: claim.title, exact: true }),
    ).toBeVisible();
    if (mode === "travel") {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.locator(".step-button").nth(1).click();
      await expect(
        page.getByRole("combobox", { name: "本条费用对应出差审批" }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBeTruthy();
    }
    await page.locator(".step-button").nth(4).click();
    await page.getByRole("button", { name: "开始整单审核" }).click();
    await expect(
      page.getByRole("heading", { name: "已满足本次提交条件" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "确认提交", exact: true }).click();
    await page
      .getByRole("dialog", { name: "确认提交" })
      .getByRole("button", { name: "确认提交", exact: true })
      .click();
    if (mode === "admin_originator") {
      const dialog = page.getByRole("dialog", { name: "管理员提交原因" });
      await dialog.locator("input").fill("核验后协助员工正式提交");
      await dialog.locator(".el-message-box__btns button").last().click();
    }
    await expect(
      page.getByRole("heading", { name: "提交记录", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("模拟 OA 已创建", { exact: true }),
    ).toBeVisible();
    if (caseId) {
      const c = await (
        await page.request.get("/api/v1/admin/cases/" + caseId)
      ).json();
      expect(c.status).toBe("submitted");
      expect(
        c.actions.some((a: any) => a.action === "approval.submit"),
      ).toBeTruthy();
    }
  });
}

test("管理员生成邀请，员工答卷，后台查询反馈详情", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".persona-button")).toBeVisible();
  await page.locator(".persona-button").click();
  await page.getByRole("menuitem", { name: "王宁 · 管理员" }).click();
  await page.getByRole("link", { name: "系统管理", exact: true }).click();
  await page.getByRole("button", { name: "使用反馈", exact: true }).click();
  await page.getByRole("combobox", { name: "合成员工" }).press("Enter");
  await page.getByRole("option", { name: "陈晓", exact: true }).click();
  await page.getByRole("heading", { name: "使用反馈", exact: true }).click();
  await page.getByRole("button", { name: "生成模拟邀请" }).click();
  const url = await page
    .getByRole("link", { name: "陈晓 →" })
    .getAttribute("href");
  expect(url).toContain("#token=");
  const form = await page.context().newPage();
  await form.goto(url!);
  await expect(
    form.getByRole("heading", { name: "让报销体验更顺手" }),
  ).toBeVisible();
  await form.getByText("识别不准确", { exact: true }).click();
  await form.getByText("校验与问题处理", { exact: true }).click();
  await form
    .getByRole("textbox", { name: "其他建议（可选）" })
    .fill("希望问题提示更具体一些");
  await form.getByRole("button", { name: "提交反馈", exact: true }).click();
  await expect(
    form.getByRole("heading", { name: "感谢您的反馈" }),
  ).toBeVisible();
  await form.close();
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(
    page.getByText("希望问题提示更具体一些", { exact: true }),
  ).toBeVisible();
});
