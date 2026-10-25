import { expect, test, type APIRequestContext } from "@playwright/test";

/** Play one episode through the agent protocol with uniformly random legal actions. */
async function playEpisode(api: APIRequestContext, token: string): Promise<string> {
  const headers = { Authorization: `Bearer ${token}` };
  const created = await api.post("/api/v1/episodes", {
    headers,
    data: { track: "red-1", keys: [crypto.randomUUID()] },
  });
  expect(created.status()).toBe(201);
  const [ep] = (await created.json()).episodes;
  let { t, n_actions: n } = ep;
  for (;;) {
    const r = await api.post("/api/v1/step", {
      headers,
      data: { steps: [{ id: ep.id, t, action: Math.floor(Math.random() * n) }] },
    });
    expect(r.ok()).toBeTruthy();
    const [res] = (await r.json()).results;
    expect(res.ok).toBe(true);
    if (res.final) {
      expect(res.final.verified).toBe(true);
      return ep.id;
    }
    ({ t, n_actions: n } = res);
  }
}

test("sign in, create an agent, play episodes, and watch a replay", async ({ page, request }) => {
  // The site runs under the production CSP (Caddyfile.local): the board's animations set styles
  // through the DOM, which it allows, never with inline style elements, which it refuses.
  const csp: string[] = [];
  page.on("console", (m) => /Content Security Policy|Refused to/.test(m.text()) && csp.push(m.text()));
  const stamp = Date.now().toString(36);
  const login = `e2e-${stamp}`;
  const slug = `bot-${stamp}`;
  const name = `E2E bot ${stamp}`; // unique, so reruns against the same database don't collide

  // Sign in through the mock OpenID provider (it plays GitHub here).
  await page.goto("/");
  await page.getByRole("link", { name: "Sign in with Dev login" }).click();
  await page.locator('input[name="username"]').fill(login);
  await page.locator('input[type="submit"], button[type="submit"]').first().click();
  await expect(page.getByText(login, { exact: true })).toBeVisible();

  // Create an agent and mint a token: shown once.
  await page.getByRole("link", { name: "Your agents" }).click();
  await page.getByLabel(/^Slug/).fill(slug);
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByRole("button", { name: "Create agent" }).click();
  const card = page.getByRole("region", { name });
  await card.getByLabel("Token label").fill("e2e");
  await card.getByRole("button", { name: "New token" }).click();
  const token = (await page.getByTestId("new-token").textContent())!.trim();
  expect(token).toMatch(/^jdk_/);

  // The agent plays three episodes over the API, like a researcher's client would.
  const ids = [];
  for (let k = 0; k < 3; k++) ids.push(await playEpisode(request, token));

  // It shows up under In progress (3 of its 500 runs).
  await page.goto("/");
  const standings = page.getByRole("region", { name: "Standings" });
  const row = standings.getByRole("row").filter({ has: page.getByRole("link", { name }) });
  await expect(row).toBeVisible();
  await expect(row.getByRole("progressbar", { name: "3 of 500 runs" })).toBeVisible();

  // Its page lists the episodes; a replay opens with the seed revealed and steps with the keys.
  await row.getByRole("link", { name }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await page.getByRole("link", { name: ids[0]!.slice(0, 8) }).click();
  await expect(page.getByText("✓ Verified")).toBeVisible();
  await expect(page.getByText("step 0 /", { exact: false })).toBeVisible();
  // The board, then a step jumped (Shift+→) and one played out (→).
  await expect(page.getByRole("group", { name: /^Jokers / })).toBeVisible();
  await page.keyboard.press("Shift+ArrowRight");
  await expect(page.getByText("step 1 /", { exact: false })).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByText("step 2 /", { exact: false })).toBeVisible();
  await expect(page.locator(".log [aria-current='step']")).toBeVisible();

  // The tape is public and names the same seed, shown under Run details.
  const tape = await (await request.get(`/api/episodes/${ids[0]}/tape`)).json();
  await page.getByText("Run details").click();
  await expect(page.getByText(tape.seed)).toBeVisible();

  expect(csp).toEqual([]);

  // Sign out.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("link", { name: "Sign in with Dev login" })).toBeVisible();
});

test("pages work for a signed-out visitor", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  await page.goto("/docs");
  await expect(page.getByRole("heading", { name: "Get started" })).toBeVisible();
  await page.goto("/no-such-page");
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  const health = await page.request.get("/healthz/deep");
  expect(health.ok()).toBeTruthy();
  expect(errors).toEqual([]);
});
