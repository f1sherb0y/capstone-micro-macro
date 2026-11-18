import { test, expect } from "@playwright/test";

const native = {
  schema_version: "1.0", mode: "gba_native", scope: "full_procurement",
  adapter_profile_id: null, failure_policy: "pause"
};
const micro = { ...native, mode: "codedemo_micro", adapter_profile_id: "codedemo-local" };
const capabilities = [
  { ...native, available: true, label: "GBA native", reason: "Uses the existing GBA procurement lifecycle." },
  { ...micro, available: false, label: "codedemo micro", reason: "Full micro procurement is not integrated yet." }
];
const receipt = {
  simulation_id: "SIM-locked", effective_mode: "gba_native", scope: "full_procurement",
  locked: true, effective_configuration: native, configuration_hash: "a".repeat(64)
};

async function mockApi(page, { draft = native, capabilityError = false, runError = false } = {}) {
  const state = {
    workflow: {
      workflow_id: "WF001", name: "Procurement test", selected_cluster_id: "",
      selected_agent_ids: [], horizon_years: 5, time_step: "monthly",
      trigger_mode: "scheduled", output_mode: "summary",
      phases: [], interventions: [], events: [], execution_logic: {},
      configuration: { procurement_execution: draft, agent_source: "default" }
    },
    saved: null, runPayload: null, capabilityError, procurementReads: 0, runtimeTicks: []
  };
  state.saved = structuredClone(state.workflow);
  // All application APIs are fixtures: these tests never create real simulations or call models.
  await page.route("**/*", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== "http://127.0.0.1:5196") return route.abort();
    const path = url.pathname;
    if (!/^\/(api|simulation|health|agents|projects|policy|results)(\/|$)/.test(path)) return route.continue();
    const reply = (data, status = 200) => route.fulfill({
      status, contentType: "application/json",
      body: JSON.stringify(status === 200 ? { success: true, data, message: "ok", error: null } : { detail: data })
    });
    if (path === "/health") return reply({ status: "ok" });
    if (path === "/api/procurement-engines") return state.capabilityError
      ? reply({ message: "Engine availability check failed." }, 503) : reply(capabilities);
    if (path.endsWith("/procurement")) {
      state.procurementReads += 1;
      return reply(receipt);
    }
    if (path === "/api/workflows") return reply([state.workflow]);
    if (path.endsWith("/save-template")) {
      state.saved = structuredClone(state.workflow);
      return reply({ template_saved: true });
    }
    if (path.endsWith("/load-template")) return reply(state.saved);
    if (path === "/api/workflows/WF001" && request.method() === "PUT") {
      state.workflow = { ...state.workflow, ...request.postDataJSON() };
      return reply(state.workflow);
    }
    if (path === "/api/workflows/WF001/run") {
      state.runPayload = request.postDataJSON();
      if (runError) return reply({ message: "Requested procurement engine is unavailable.", error_code: "PROCUREMENT_ENGINE_UNAVAILABLE" }, 503);
      return reply({ simulation_id: "SIM-locked", status: "created", current_tick: 0, agent_count: 8, procurement: receipt });
    }
    if (path.endsWith("/runtime-state")) {
      state.runtimeTicks.push(url.searchParams.get("tick"));
      return reply({ simulation_id: "SIM-locked", current_tick: 0, total_ticks: 60, status: "created",
        map: { projects: [], enterprises: [], collaboration_links: [], resource_flows: [] }, kpis: {} });
    }
    if (path.endsWith("/timeline")) return reply({ ticks: [] });
    if (path.endsWith("/network")) return reply({ nodes: [], edges: [] });
    if (["/api/clusters", "/api/policies", "/api/agents"].includes(path)) return reply({ items: [], total: 0 });
    if (/^\/api\/(agents|clusters|policies)\//.test(path)) return reply({ message: "No fixture selected." }, 404);
    return reply({});
  });
  return state;
}

test("native selection, disabled micro option and desktop layout", async ({ page }, testInfo) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await mockApi(page);
  await page.goto("/?view=workflow");
  await expect(page.getByRole("radio", { name: /GBA native/ })).toBeChecked();
  await expect(page.getByRole("radio", { name: /codedemo micro/ })).toBeDisabled();
  await expect(page.getByText("Not available yet")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run Simulation", exact: true })).toBeEnabled();
  await page.locator(".workflow-run-card").screenshot({ path: testInfo.outputPath("procurement-card.png") });
  expect(errors).toEqual([]);
});

test("unavailable saved mode blocks creation; choosing native and saving round-trips", async ({ page }) => {
  const state = await mockApi(page, { draft: micro });
  await page.goto("/?view=workflow");
  await expect(page.getByRole("radio", { name: /codedemo micro/ })).toBeChecked();
  const run = page.getByRole("button", { name: "Run Simulation", exact: true });
  await expect(run).toBeDisabled();
  const nativeRadio = page.getByRole("radio", { name: /GBA native/ });
  await nativeRadio.focus();
  await page.keyboard.press("Space");
  await expect(run).toBeEnabled();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/Template saved, including procurement mode/)).toBeVisible();
  expect(state.saved.configuration.procurement_execution).toEqual(native);
  await page.getByRole("button", { name: "Load", exact: true }).click();
  await expect(page.getByText(/Saved template loaded/)).toBeVisible();
  await expect(nativeRadio).toBeChecked();
});

test("backend rejection is shown with the submitted execution configuration", async ({ page }) => {
  const state = await mockApi(page, { runError: true });
  await page.goto("/?view=workflow");
  const run = page.getByRole("button", { name: "Run Simulation", exact: true });
  await expect(run).toBeEnabled();
  await run.click();
  await expect(page.getByText("Requested procurement engine is unavailable.")).toBeVisible();
  expect(state.runPayload.procurement_execution).toEqual(native);
  expect(state.runPayload.workflow_configuration.configuration.procurement_execution).toEqual(native);
});

test("refresh uses the server lock receipt independently of the next-run draft", async ({ page }) => {
  const state = await mockApi(page, { draft: micro });
  await page.goto("/?view=workflow&simulation_id=SIM-locked");
  await expect(page.getByText("GBA native · Locked from creation")).toBeVisible();
  await expect(page.getByRole("radio", { name: /codedemo micro/ })).toBeChecked();
  await page.reload();
  await expect(page.getByText("GBA native · Locked from creation")).toBeVisible();
  expect(state.procurementReads).toBeGreaterThanOrEqual(2);
  expect(state.runtimeTicks.every(tick => tick === null)).toBe(true);
});

test("failed capability lookup blocks Run and supports retry", async ({ page }) => {
  const state = await mockApi(page, { capabilityError: true });
  await page.goto("/?view=workflow");
  await expect(page.getByText("Engine availability check failed.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run Simulation", exact: true })).toBeDisabled();
  state.capabilityError = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("button", { name: "Run Simulation", exact: true })).toBeEnabled();
});

test("successful creation displays the lock and does not request a future tick", async ({ page }) => {
  const state = await mockApi(page);
  await page.goto("/?view=workflow");
  const run = page.getByRole("button", { name: "Run Simulation", exact: true });
  await expect(run).toBeEnabled();
  await run.click();
  await expect(page.getByText("GBA native · Locked from creation")).toBeVisible();
  await expect.poll(() => state.runtimeTicks.length).toBeGreaterThan(0);
  expect(state.runtimeTicks).toEqual([null]);
  expect(state.runPayload.procurement_execution).toEqual(native);
});
