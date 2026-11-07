import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("element-plus", () => ({ ElMessage: { error: vi.fn() } }));
import { api, APIError, setCSRF } from "./client";

afterEach(() => vi.unstubAllGlobals());
describe("session and command HTTP contract", () => {
  it("keeps command identity, cookie and decimal strings across an explicit retry", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        json: async () => ({ id: "submission" }),
      });
    vi.stubGlobal("fetch", fetchMock);
    setCSRF("csrf-test");
    const payload = { expected_revision: 4, amount: "88.01" };
    await api("/claims/x/submissions", "POST", payload, {
      key: "stable-command",
    });
    await api("/claims/x/submissions", "POST", payload, {
      key: "stable-command",
    });
    for (const [, options] of fetchMock.mock.calls) {
      expect(options.credentials).toBe("include");
      expect(options.headers["X-CSRF-Token"]).toBe("csrf-test");
      expect(options.headers["Idempotency-Key"]).toBe("stable-command");
      expect(JSON.parse(options.body).amount).toBe("88.01");
    }
  });
  it("exposes revision conflict details to the editor without replacing its values", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({
          ok: false,
          json: async () => ({
            error: {
              code: "REVISION_CONFLICT",
              message: "版本已变化",
              details: [{ current_revision: 8 }],
            },
          }),
        }),
    );
    await expect(
      api("/claims/x", "PATCH", { expected_revision: 7 }, { silent: true }),
    ).rejects.toMatchObject({
      code: "REVISION_CONFLICT",
      details: [{ current_revision: 8 }],
    });
  });
  it("does not turn a network interruption into a successful result", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(
      api("/claims", "GET", undefined, { silent: true }),
    ).rejects.toBeInstanceOf(APIError);
  });
});
