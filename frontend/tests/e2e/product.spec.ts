import { test, expect } from "@playwright/test";

test("员工完整填报、材料识别分配、回填审核与模拟提交", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "报销工作台", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/workspace-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "新建报销", exact: true })
    .first()
    .click();
  await page
    .getByPlaceholder("例如：十一月办公用品采购")
    .fill("十一月工作餐报销");
  await page.getByRole("button", { name: "创建并填写" }).click();
  await expect(
    page.getByRole("heading", { name: "十一月工作餐报销" }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "本次申报总金额（元）", exact: true })
    .fill("88.00");
  await page
    .getByRole("textbox", { name: "本次申报总金额（元）", exact: true })
    .blur();
  await page.getByRole("button", { name: "＋ 管理收款账户" }).click();
  await page.getByPlaceholder("例如：我的工资卡（合成）").fill("合成工资卡");
  await page
    .getByPlaceholder("请输入至少4字符的合成账户")
    .fill("SYNTHETIC-0001");
  await page.getByRole("button", { name: "添加账户", exact: true }).click();
  await page.getByText("请选择收款账户", { exact: true }).click();
  await page.getByRole("option", { name: "合成工资卡 · •••• 0001" }).click();
  await page.getByRole("button", { name: "下一步：费用明细" }).click();
  await page.getByRole("button", { name: "添加明细", exact: true }).click();
  await page
    .getByPlaceholder("例如：客户会议工作餐，请填写真实业务用途")
    .fill("客户会议工作餐");
  await page
    .getByPlaceholder("例如：客户会议工作餐，请填写真实业务用途")
    .blur();
  await page.getByRole("combobox", { name: "所属项目", exact: true }).click();
  await page.getByRole("option", { name: "日常运营" }).click();
  await page.getByRole("button", { name: "下一步：上传与分配" }).click();
  await page.getByRole("button", { name: "选择合成样本" }).click();
  const meal = page
    .locator(".sample-card")
    .filter({ hasText: "餐饮付款 · 88元" });
  await meal.getByRole("button", { name: "加入本次报销" }).click();
  await page
    .locator(".sample-card")
    .filter({ hasText: "餐饮发票 · 88元" })
    .getByRole("button", { name: "加入本次报销" })
    .click();
  await page
    .getByRole("dialog", { name: "选择合成业务材料" })
    .getByRole("button", { name: "Close this dialog" })
    .click();
  await expect(
    page.locator(".material-card .status-chip").filter({ hasText: "已识别" }),
  ).toHaveCount(2);
  for (const card of await page.locator(".material-card").all()) {
    await expect(
      card.getByRole("combobox", { name: "分配到费用明细" }),
    ).toBeEnabled();
    await card.locator(".material-fields .el-select").nth(1).click();
    const listId = await card
      .getByRole("combobox", { name: "分配到费用明细" })
      .getAttribute("aria-controls");
    await page
      .locator("#" + listId)
      .getByRole("option", { name: "明细 1 · 客户会议工作餐" })
      .click();
  }
  await page.screenshot({
    path: "test-results/materials-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "下一步：识别回填" }).click();
  await page.getByRole("button", { name: "生成回填建议" }).click();
  await expect(
    page.getByRole("button", { name: /应用所选建议/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: /应用所选建议/ }).click();
  await page.getByRole("button", { name: "前往整单审核" }).click();
  await page.getByRole("button", { name: "开始整单审核" }).click();
  await expect(
    page.getByRole("heading", { name: "已满足本次提交条件" }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/review-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "确认提交", exact: true }).click();
  await page
    .getByRole("dialog", { name: "确认提交" })
    .getByRole("button", { name: "确认提交", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "提交记录", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("模拟 OA 已创建", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "新建报销", exact: true }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/workspace-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
});

test("管理员管理页与专属入口可访问，窄屏表格局部滚动", async ({ page }) => {
  await page.goto("/");
  await page.locator(".persona-button").click();
  await page.getByRole("menuitem", { name: "王宁 · 管理员" }).click();
  await expect(page.getByRole("button", { name: /采购供应链/ })).toBeVisible();
  await page.getByRole("link", { name: "系统管理", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "系统管理", exact: true }),
  ).toBeVisible();
  for (const name of ["任务池", "操作事件", "发票台账", "使用反馈"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(
      page.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "发票台账", exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/admin-mobile.png",
    fullPage: true,
  });
});
