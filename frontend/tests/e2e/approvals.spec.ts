import { test, expect } from "@playwright/test";

test("自动获取归属人审批、选择恢复、单号补充及读取失败重试", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator(".entry-card").first()).toBeVisible();
  const me = await (await page.request.get("/api/v1/me")).json();
  const created = await page.request.post("/api/v1/claims", {
    headers: {
      "X-CSRF-Token": me.csrf_token,
      "Idempotency-Key": crypto.randomUUID(),
    },
    data: {
      workflow_key: "daily",
      title: "审批自动获取验收",
      route_mode: "self",
    },
  });
  expect(created.status()).toBe(201);
  const claim = await created.json();
  await page.goto("/claims/" + claim.id);
  const picker = page.getByRole("region", { name: "自动获取关联审批" });
  await expect(picker.getByText(/已自动获取 陈晓 的 3 条审批/)).toBeVisible();
  await expect(picker.locator(".approval-card")).toHaveCount(3);
  await expect(
    page.getByRole("textbox", { name: "审批单号", exact: true }),
  ).not.toBeVisible();
  const first = picker.locator(".approval-card").first();
  await first.click();
  await expect(first).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(picker.locator(".approval-card").first()).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await picker.getByRole("button", { name: "未找到审批？按单号查找" }).click();
  await page
    .getByRole("textbox", { name: "审批单号", exact: true })
    .fill("SYN-OUTING-employee");
  await picker.getByRole("button", { name: "查找并关联", exact: true }).click();
  await expect(picker.getByText("已关联 2 条审批 · 可选择多条")).toBeVisible();
  await page
    .getByRole("combobox", { name: "填报身份", exact: true })
    .press("Enter");
  await page.getByRole("option", { name: "代他人填报", exact: true }).click();
  await expect(
    page.getByRole("combobox", { name: "报销归属人", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("combobox", { name: "报销归属人", exact: true })
    .press("Enter");
  await page.getByRole("option", { name: "林悦", exact: true }).click();
  await expect(picker.getByText(/已自动获取 林悦 的 3 条审批/)).toBeVisible();
  await expect(
    picker.getByText("SYN-TRAVEL-colleague", { exact: true }),
  ).toBeVisible();
  await expect(
    picker.getByText("SYN-TRAVEL-employee", { exact: true }),
  ).not.toBeVisible();
  await expect(picker.getByText("已关联 0 条审批 · 可选择多条")).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "审批单号", exact: true }),
  ).not.toBeVisible();

  const pattern = "**/api/v1/related-approvals?**";
  await page.route(pattern, (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ error: { message: "不可用" } }),
    }),
  );
  await picker.getByRole("button", { name: "刷新审批" }).click();
  await expect(picker.getByRole("alert")).toContainText("审批记录获取失败");
  await page.unroute(pattern);
  await picker.getByRole("button", { name: "刷新审批" }).click();
  await expect(picker.getByText(/已自动获取 林悦 的 3 条审批/)).toBeVisible();
  await expect(picker.locator(".approval-card")).toHaveCount(3);
  await page.screenshot({
    path: "test-results/approvals-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/approvals-mobile.png",
    fullPage: true,
  });
});
