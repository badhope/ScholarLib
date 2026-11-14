import { test, expect } from "@playwright/test";
import { ADMIN, loginViaUi } from "./helpers";

// P1-8/9/10 + P2-14：编辑侧新入口必须真实渲染，而不是只在菜单里挂链接。
test.describe("editor review tools", () => {
  test("editor sees role Today and can open triage + calibration", async ({
    page,
  }) => {
    await loginViaUi(page, ADMIN);

    await expect(page.getByTestId("editor-today")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("author-today")).toBeVisible({
      timeout: 10_000,
    });

    await page.goto("/editor/triage");
    await expect(page.getByRole("heading", { name: "初筛队列" })).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("初筛口径：")).toBeVisible();

    await page.goto("/editor/calibration");
    await expect(
      page.getByRole("heading", { name: "审稿人季度校准" }),
    ).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByLabel("年份")).toBeVisible();
  });
});
