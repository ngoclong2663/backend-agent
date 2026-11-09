// Story 26.5: the evaluation's browser (from the business-value lab): one Playwright process driven with JSON lines
// on stdin, so a screen is captured at the exact moment of a workflow step (between two API calls). One browser
// context per signed-in user. Runs inside bga-runner-node (Chromium in /ms-playwright).
//
//   node walk.mjs [host]      host: what `localhost` means (host.docker.internal from a container)
//
// Commands (one JSON object per line), each answered by one JSON line on stdout:
//   {"cmd":"login","user":"<key>","url":"<sign-in page>","field":"email","login":"...","password":"...","file":"..."}
//   {"cmd":"shot","user":"<key>|null","url":"...","file":"/out/x.png"}
//   {"cmd":"tour","url":"<frontend>","signIn":"/login","field":"email","login":"...","password":"...","role":"...",
//        "shot":"/out/tour-01-staff","maxSteps":60}   (Story 28.6: plays the guided tour on the mocks, see `tour`)
//   {"cmd":"quit"}
import { createInterface } from "node:readline";
import { chromium } from "playwright-core";

const host = process.argv[2];
const browser = await chromium.launch({
  args: host ? [`--host-resolver-rules=MAP localhost ${host}`] : [],
});
const contexts = new Map();

async function context(user) {
  const key = user || "anonymous";
  if (!contexts.has(key)) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    // the screens as they are: the guided tour (Story 26.4) does not start on its own in this browser
    if (!process.env.BGA_TOUR) await ctx.addInitScript(() => { try { localStorage.setItem("bga-tour-off", "1"); } catch {} });
    contexts.set(key, ctx);
  }
  return contexts.get(key);
}

function watch(page) {
  const problems = [];
  page.on("pageerror", (error) => problems.push(`page error: ${error.message.slice(0, 200)}`));
  page.on("response", (response) => {
    if (response.status() >= 400 && response.request().resourceType() === "fetch" && !response.url().includes("/_next/")) {
      problems.push(`${response.request().method()} ${new URL(response.url()).pathname} → ${response.status()}`);
    }
  });
  return problems;
}

async function settle(page) {
  await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(800);
}

async function pageText(page) {
  return (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 3000);
}

async function login(cmd) {
  const ctx = await context(cmd.user);
  const page = await ctx.newPage();
  const problems = watch(page);
  await page.goto(cmd.url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await settle(page);
  const field = page.locator(`input[name="${cmd.field}"], input[type="email"]`).first();
  await field.fill(cmd.login, { timeout: 15000 });
  await page.locator('input[type="password"]').first().fill(cmd.password);
  await page.locator('form button[type="submit"]').first().click();
  await page.waitForURL((url) => !url.toString().startsWith(cmd.url), { timeout: 20000 }).catch(() => {});
  await settle(page);
  const stillOnSignIn = await page.locator('input[type="password"]').count();
  if (cmd.wait) await page.waitForTimeout(cmd.wait);
  if (cmd.file) await page.screenshot({ path: cmd.file });
  const result = { ok: stillOnSignIn === 0, url: page.url(), problems, text: await pageText(page) };
  await page.close();
  return result;
}

async function shot(cmd) {
  const ctx = await context(cmd.user);
  const page = await ctx.newPage();
  const problems = watch(page);
  const response = await page.goto(cmd.url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await settle(page);
  if (cmd.wait) await page.waitForTimeout(cmd.wait);
  await page.screenshot({ path: cmd.file, fullPage: true });
  const result = { ok: true, status: response?.status() ?? null, url: page.url(), problems, text: await pageText(page) };
  await page.close();
  return result;
}

// -- Story 28.6: the guided tour, played ------------------------------------------------------------------------------
//
// A fresh browser context per role, on the mock API whatever the server runs (the kit's `bga-mock-api` switch, so no
// real record is made) and with the tour on. The walker reads the step the tour shows (`data-bga-tour-step`, its
// `-kind`), presses Next on `look` and `note` steps, and on a `do` step clicks the control the tour points at
// (`data-bga-tour-current`), uses "Fill with an example", gives a required upload a sample file and presses the
// form's submit button, then waits for the tour to move on. A step that does not move on is `stuck` (a screenshot,
// the API answers seen), and the tour's own skip moves past it so the rest can be played. "Continue as <role>" is
// followed, so a workflow is played across roles.

const SAMPLES = "/walk/samples";
const SAMPLE_BY_ACCEPT = [
  ["video/", "sample.mp4"],
  ["audio/", "sample.mp3"],
  ["text/vtt", "sample.en.vtt"],
  ["application/x-subrip", "sample.en.srt"],
  ["image/", "sample-poster.jpg"],
];

function sampleFor(accept) {
  const found = SAMPLE_BY_ACCEPT.find(([prefix]) => (accept || "").includes(prefix));
  return `${SAMPLES}/${found ? found[1] : "placeholder.png"}`;
}

async function currentStep(page) {
  return page.evaluate(() => {
    const el = document.querySelector("[data-bga-tour-step]");
    if (!el) return null;
    return {
      id: el.getAttribute("data-bga-tour-step"),
      kind: el.getAttribute("data-bga-tour-kind"),
      tour: el.getAttribute("data-bga-tour-tour"),
      blocked: el.getAttribute("data-bga-tour-blocked"),
      continueAs: document.querySelector("[data-bga-tour-continue-as]")?.getAttribute("data-bga-tour-continue-as") ?? null,
    };
  });
}

async function waitStep(page, change, ms) {
  const started = Date.now();
  while (Date.now() - started < ms) {
    const step = await currentStep(page);
    if (change(step)) return step;
    await page.waitForTimeout(300);
  }
  return await currentStep(page);
}

async function clickIf(page, selector) {
  const target = page.locator(selector).first();
  if ((await target.count()) === 0) return false;
  try {
    await target.click({ timeout: 3000 });
    return true;
  } catch {
    return false;
  }
}

async function tour(cmd) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript(() => {
    try {
      localStorage.setItem("bga-mock-api", "1");
      localStorage.removeItem("bga-tour-off");
    } catch {}
  });
  const page = await ctx.newPage();
  const problems = watch(page);
  const steps = [];
  const log = [];
  let completed = false;
  let tourId = null;
  let shots = 0;
  async function snapshot(name) {
    if (!cmd.shot) return null;
    shots += 1;
    const file = `${cmd.shot}-${shots}-${name.replace(/[^a-z0-9]+/gi, "-").slice(0, 40)}.png`;
    await page.screenshot({ path: file, fullPage: true }).catch(() => {});
    return file;
  }
  try {
    if (cmd.login) {
      await page.goto(cmd.url + (cmd.signIn || "/login"), { waitUntil: "domcontentloaded", timeout: 60000 });
      await settle(page);
      await page.locator(`input[name="${cmd.field}"], input[type="email"]`).first().fill(cmd.login, { timeout: 15000 });
      await page.locator('input[type="password"]').first().fill(cmd.password);
      await page.locator('form button[type="submit"]').first().click();
      await page.waitForURL((url) => !url.pathname.startsWith(cmd.signIn || "/login"), { timeout: 20000 }).catch(() => {});
      await settle(page);
      log.push(`signed in as ${cmd.login}: ${page.url()}`);
    } else {
      await page.goto(cmd.url + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
      await settle(page);
    }
    let step = await waitStep(page, (s) => Boolean(s), 15000);
    if (!step) {
      // no tour started by itself: the checklist's Continue
      await clickIf(page, "[data-bga-guide]");
      await page.waitForTimeout(500);
      await clickIf(page, "[data-bga-checklist-continue]");
      step = await waitStep(page, (s) => Boolean(s), 10000);
    }
    if (!step) {
      return { ok: false, error: "the tour did not start", steps, completed, tour: tourId, log, problems };
    }
    let previous = null;
    for (let count = 0; step && count < (cmd.maxSteps || 60); count += 1) {
      tourId = step.tour ?? tourId;
      const started = Date.now();
      problems.length = 0;
      if (step.id === "outcome") {
        await clickIf(page, "[data-action=primary]");
        completed = true;
        log.push("outcome shown");
        break;
      }
      const key = `${step.tour}/${step.id}`;
      if (step.continueAs && step.kind === "note") {
        // another role's step: continue as that role's demo user (the tour resumes at this step)
        log.push(`continue as ${step.continueAs} at ${step.id}`);
        await clickIf(page, "[data-bga-tour-continue-as]");
        step = await waitStep(page, (s) => Boolean(s) && s.kind !== "note", 25000);
        if (step && step.id === previous) continue;
        if (step) continue;
        steps.push({ tour: tourId, id: key.split("/")[1], kind: "note", result: "stuck", reason: "the tour did not resume after signing in", ms: Date.now() - started });
        break;
      }
      let result = "completed";
      let reason = null;
      let file = null;
      if (step.kind === "do") {
        const clicked = await clickIf(page, "[data-bga-tour-current]");
        await page.waitForTimeout(700);
        if (await clickIf(page, "[data-bga-tour-fill]")) await page.waitForTimeout(700);
        const files = page.locator('form[data-bga-form] input[type="file"]');
        for (let index = 0; index < (await files.count()); index += 1) {
          const input = files.nth(index);
          const accept = await input.getAttribute("accept");
          await input.setInputFiles(sampleFor(accept)).catch(() => {});
          await page.waitForTimeout(1200);
        }
        const submit = page.locator('form[data-bga-form] [data-bga-action="submit"]').last();
        if ((await submit.count()) > 0 && (await submit.isEnabled().catch(() => false))) await submit.click({ timeout: 3000 }).catch(() => {});
        const next = await waitStep(page, (s) => !s || s.id !== step.id, 20000);
        if (next && next.id === step.id) {
          result = "stuck";
          reason = [clicked ? null : "no control to click", ...problems.slice(0, 3)].filter(Boolean).join("; ") || "the step did not complete";
          file = await snapshot(step.id);
          await clickIf(page, "[data-bga-tour-skip]");
        }
      } else {
        if (step.blocked) {
          result = "skipped";
          reason = step.blocked;
        }
        await clickIf(page, "[data-action=primary]");
      }
      steps.push({ tour: tourId, id: step.id, kind: step.kind, result, ...(reason ? { reason } : {}), ms: Date.now() - started, ...(file ? { file } : {}) });
      previous = step.id;
      step = await waitStep(page, (s) => !s || s.id !== previous, 12000);
      if (step && step.id === previous) {
        log.push(`the tour stayed on ${previous}`);
        break;
      }
    }
    return { ok: true, steps, completed, tour: tourId, log, problems: problems.slice(0, 10) };
  } catch (error) {
    return { ok: false, error: String(error?.message || error).slice(0, 300), steps, completed, tour: tourId, log };
  } finally {
    await ctx.close().catch(() => {});
  }
}

const rl = createInterface({ input: process.stdin });
for await (const line of rl) {
  if (!line.trim()) continue;
  let cmd;
  try {
    cmd = JSON.parse(line);
    if (cmd.cmd === "quit") break;
    const result = cmd.cmd === "login" ? await login(cmd) : cmd.cmd === "tour" ? await tour(cmd) : await shot(cmd);
    process.stdout.write(JSON.stringify(result) + "\n");
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(error?.message || error).slice(0, 500) }) + "\n");
  }
}
await browser.close();
