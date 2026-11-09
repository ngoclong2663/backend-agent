// Design checklist measurements for a built site (Story 17.7, templates/nextjs_overlay/DESIGN_CHECKLIST.md).
// Runs inside bga-runner-node from the project directory, after `pnpm build`: a static export (out/) is served as
// files; a dynamic app (no out/) runs with `next start` on its mock API (MOCK_TEST_API=true, Story 20.4).
//
//   node design-check.mjs <shots-dir> <page-route>...
//
// For every page at 390 / 768 / 1440 px, light and dark: a full-page screenshot and the measurements below, written
// to <shots-dir>/report.json. Dev tool only; not part of the generation pipeline.
// DESIGN_CHECK_WIDTHS / DESIGN_CHECK_SCHEMES (comma-separated) narrow the views, e.g. the diversity report (Story 20.1)
// takes only 1440 / light. Pages load with reduced motion, so screenshots show every element in its final state.
// DESIGN_CHECK_MOTION=1 adds two passes per page at 1440 px (Story 20.6): with motion on, the time until the hero's
// call to action is fully visible (from load, and from the first section's appearance: `ctaDelayMs`, the motion's
// share) and, after scrolling to the end, anything still transparent or displaced; with
// JavaScript off, anything not fully visible. Results: `<page>-motion` entries in report.json.
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { chromium } from "@playwright/test";

const [shots = "shots", ...routes] = process.argv.slice(2);
const list = (value, fallback) => (value ? value.split(",").map((item) => item.trim()) : fallback);
const WIDTHS = list(process.env.DESIGN_CHECK_WIDTHS, ["390", "768", "1440"]).map(Number);
const SCHEMES = list(process.env.DESIGN_CHECK_SCHEMES, ["light", "dark"]);
const PORT = 3199;
// Story 30.1: DESIGN_CHECK_LOGIN=<email>:<password> signs in on the app's sign-in page (DESIGN_CHECK_SIGN_IN, default
// /login) before the routes are shot, so the measurements are what a signed-in user sees.
const LOGIN = process.env.DESIGN_CHECK_LOGIN ? process.env.DESIGN_CHECK_LOGIN.split(":") : null;
const SIGN_IN = process.env.DESIGN_CHECK_SIGN_IN || "/login";
// Story 30.3 (the design plugin gates): DESIGN_CHECK_RECIPES=a,b shoots every view once per recipe (the build carries
// each recipe's CSS under `:root[data-recipe=<name>]`, `recipe_css(..., scope=)`); DESIGN_CHECK_STATES=empty,error,loading
// adds the mock API's states (`bga-mock-state`) per view; DESIGN_CHECK_A11Y=1 adds the keyboard pass (focus rings) and
// the contrast of every text element against its backdrop.
const RECIPES = list(process.env.DESIGN_CHECK_RECIPES, [null]);
const STATES = list(process.env.DESIGN_CHECK_STATES, []);
const A11Y = process.env.DESIGN_CHECK_A11Y === "1";
mkdirSync(shots, { recursive: true });

const exported = existsSync("out");
const server = exported
  ? spawn("node", ["scripts/serve-static.mjs", "out", String(PORT)], { stdio: "inherit" })
  : spawn("pnpm", ["exec", "next", "start", "-p", String(PORT), "-H", "127.0.0.1"], {
      stdio: "inherit",
      env: { ...process.env, MOCK_TEST_API: "true", API_BASE_URL: "" },
    });
await waitForServer(exported ? "/" : "/api/runtime-config");

async function waitForServer(path) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}${path}`);
      if (response.ok) return;
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`the site did not start on port ${PORT}`);
}

function measure() {
  const visible = (el) => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const lines = (el) => {
    const style = getComputedStyle(el);
    const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.2;
    return Math.round(el.getBoundingClientRect().height / lineHeight);
  };
  const textElements = [...document.querySelectorAll("body *")].filter(
    (el) => visible(el) && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()),
  );
  const sizes = [...new Set(textElements.map((el) => getComputedStyle(el).fontSize))].sort(
    (a, b) => parseFloat(a) - parseFloat(b),
  );
  const families = [...new Set(textElements.map((el) => getComputedStyle(el).fontFamily.split(",")[0].trim()))];
  const loaded = [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family.replaceAll('"', ""));
  const h1 = document.querySelector("h1");
  const header = document.querySelector("header");
  const hero = document.querySelector('[data-bga-component="Hero"]');
  const cta = hero?.querySelector("a");
  const paragraphs = [...document.querySelectorAll("main p")].filter((p) => visible(p) && lines(p) >= 2);
  const perLine = paragraphs.map((p) => Math.round(p.textContent.length / lines(p)));
  const body = getComputedStyle(document.body);
  // Story 22.5: an app form's inputs (the kit's `form[data-bga-form]`)
  const form = document.querySelector("form[data-bga-form]");
  const controls = form
    ? [...form.querySelectorAll('input:not([type="hidden"]), textarea, button[data-bga-input], [role="switch"], button[role="combobox"]')]
        // primitives' visually hidden inputs (a Select's, a radio's) are not controls a reader sees
        .filter((el) => visible(el) && el.getBoundingClientRect().height > 4 && el.getAttribute("aria-hidden") !== "true")
    : [];
  const labelled = (el) =>
    (el.labels && el.labels.length > 0) || el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || el.closest("label");
  const fields = form ? [...form.querySelectorAll('[data-slot="field"]')].filter(visible) : [];
  // Story 30.1: the kit's structural markers (shell, views, details, cards, filters, figures), for the fingerprints
  const markers = {};
  for (const key of ["shell", "view", "detail", "card", "filters", "figures", "home"]) {
    const values = [...new Set([...document.querySelectorAll(`[data-bga-${key}]`)].map((el) => el.getAttribute(`data-bga-${key}`)))];
    if (values.length) markers[key] = values;
  }
  // Story 30.3: the contrast of text against the backdrop behind it (the nearest painted background colour up the
  // tree; text over an image or a gradient is skipped: the check cannot see the pixels), WCAG 2.x AA
  const parseColor = (value) => {
    const m = /rgba?\(([^)]+)\)/.exec(value || "");
    if (!m) return null;
    const parts = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };
  const luminance = ({ r, g, b }) => {
    const channel = (c) => {
      const v = c / 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const blend = (top, under) => ({
    r: top.r * top.a + under.r * (1 - top.a),
    g: top.g * top.a + under.g * (1 - top.a),
    b: top.b * top.a + under.b * (1 - top.a),
    a: 1,
  });
  const backdrop = (el) => {
    const layers = [];
    for (let node = el; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.backgroundImage && style.backgroundImage !== "none") return null;
      const color = parseColor(style.backgroundColor);
      if (color && color.a > 0) {
        layers.unshift(color);
        if (color.a >= 1) break;
      }
      if (node === document.documentElement) break;
    }
    if (!layers.length || layers[0].a < 1) layers.unshift({ r: 255, g: 255, b: 255, a: 1 });
    return layers.reduce((under, top) => blend(top, under));
  };
  const contrastFailures = [];
  let contrastChecked = 0;
  for (const el of textElements) {
    if (el.closest("[data-bga-media], video, canvas, svg, [aria-hidden='true']")) continue;
    const style = getComputedStyle(el);
    const color = parseColor(style.color);
    const under = backdrop(el);
    if (!color || !under || color.a === 0) continue;
    const fore = color.a < 1 ? blend(color, under) : color;
    const l1 = luminance(fore);
    const l2 = luminance(under);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const size = parseFloat(style.fontSize);
    const large = size >= 24 || (size >= 18.66 && parseInt(style.fontWeight, 10) >= 700);
    contrastChecked += 1;
    if (ratio < (large ? 3 : 4.5) && contrastFailures.length < 12) {
      const text = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join(" ").slice(0, 40);
      contrastFailures.push({ text, ratio: Math.round(ratio * 100) / 100, color: style.color, size: Math.round(size) });
    }
  }
  return {
    markers,
    contrast: { checked: contrastChecked, failing: contrastFailures },
    h1Lines: h1 ? lines(h1) : null,
    navHeight: header ? Math.round(header.getBoundingClientRect().height) : null,
    ctaAboveFold: cta ? cta.getBoundingClientRect().bottom <= window.innerHeight : null,
    typeSizes: sizes,
    families,
    loadedFonts: [...new Set(loaded)],
    maxCharsPerLine: perLine.length ? Math.max(...perLine) : null,
    background: body.backgroundColor,
    foreground: body.color,
    overflowX: document.documentElement.scrollWidth > window.innerWidth,
    form: form
      ? {
          fields: fields.length,
          columns: new Set(fields.map((f) => Math.round(f.getBoundingClientRect().left))).size,
          nativeDateInputs: form.querySelectorAll('input[type="date"], input[type="datetime-local"]').length,
          // controls past the form's edge (a card clips them, so the page itself does not scroll)
          clipped: [...form.querySelectorAll("button, input, textarea")]
            .filter((el) => visible(el) && el.getBoundingClientRect().right > form.getBoundingClientRect().right + 1)
            .map((el) => el.id || el.getAttribute("aria-label") || el.tagName.toLowerCase()),
          unlabelled: controls.filter((el) => !labelled(el)).map((el) => el.id || el.tagName.toLowerCase()),
          minControlHeight: Math.min(
            ...controls.filter((el) => el.getAttribute("role") !== "switch").map((el) => Math.round(el.getBoundingClientRect().height)),
          ),
        }
      : null,
  };
}

/** Text and images in the page's main area that are not fully visible (opacity below 1 up the tree) or still moved. */
function notShown() {
  const shown = (el) => {
    let opacity = 1;
    for (let node = el; node && node !== document.body; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") return true; // hidden on purpose (responsive)
      opacity *= parseFloat(style.opacity);
      if (style.translate !== "none" && style.translate !== "0px" && node.closest("[data-bga-section]")) return false;
    }
    return opacity >= 0.99;
  };
  const content = [...document.querySelectorAll("main *")].filter(
    (el) => el.tagName === "IMG" || [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()),
  );
  return content
    .filter((el) => !shown(el))
    .slice(0, 10)
    .map((el) => `${el.tagName.toLowerCase()} in ${el.closest("[data-bga-component]")?.dataset.bgaComponent ?? "page"}`);
}

async function motionPass(browser, route) {
  const url = `http://127.0.0.1:${PORT}${route}`;
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "no-preference" });
  await page.goto(url, { waitUntil: "domcontentloaded" });
  // A dynamic app renders behind its mock gate: wait for the first section, then time the call to action from there
  // (the mock API's start-up is not the motion's cost).
  await page.waitForSelector("[data-bga-section]", { timeout: 30_000 });
  const sectionMs = await page.evaluate(() => performance.now());
  await page.waitForFunction(() => {
    const cta = document.querySelector('[data-bga-component="Hero"] a');
    let opacity = 1;
    for (let node = cta; node; node = node.parentElement) opacity *= parseFloat(getComputedStyle(node).opacity);
    return opacity >= 0.99;
  });
  const ctaVisibleMs = Math.round(await page.evaluate(() => performance.now()));
  const ctaDelayMs = Math.round(ctaVisibleMs - sectionMs);
  await page.waitForLoadState("networkidle");
  const motionOn = await page.evaluate(() => document.documentElement.dataset.motion === "on");
  const height = await page.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y <= height; y += 450) {
    await page.evaluate((top) => window.scrollTo(0, top), y);
    await page.waitForTimeout(120);
  }
  await page.waitForTimeout(1500);
  const hidden = await page.evaluate(notShown);
  await page.close();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, javaScriptEnabled: false });
  const still = await context.newPage();
  await still.goto(url, { waitUntil: "load" });
  const noJsHidden = await still.evaluate(notShown);
  await context.close();
  return { motionOn, ctaVisibleMs, ctaDelayMs, hidden, noJsHidden };
}

async function signIn(page) {
  await page.goto(`http://127.0.0.1:${PORT}${SIGN_IN}`, { waitUntil: "networkidle" });
  await page.locator('input[name="email"], input[type="email"]').first().fill(LOGIN[0], { timeout: 15_000 });
  await page.locator('input[type="password"]').first().fill(LOGIN.slice(1).join(":"));
  await page.locator('form button[type="submit"]').first().click();
  await page.waitForURL((url) => !url.pathname.startsWith(SIGN_IN), { timeout: 20_000 }).catch(() => {});
  await page.waitForLoadState("networkidle");
}

/** Story 30.3: Tab through the page: every focused element should show a ring (an outline or a box shadow). */
async function keyboardPass(page) {
  const seen = new Set();
  const withoutRing = [];
  let tabbed = 0;
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.keyboard.press("Tab");
  for (let step = 0; step < 40; step += 1) {
    const focused = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return null;
      const style = getComputedStyle(el);
      const ring =
        (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0) ||
        (style.boxShadow && style.boxShadow !== "none") ||
        el.matches(":focus-visible") === false; // the browser decided no ring is due (a pointer-style control)
      const label = `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${el.getAttribute("aria-label") ? "[" + el.getAttribute("aria-label") + "]" : ""}`;
      return { label, ring, key: label + "@" + Math.round(el.getBoundingClientRect().top) };
    });
    if (!focused || seen.has(focused.key)) break;
    seen.add(focused.key);
    tabbed += 1;
    if (!focused.ring && withoutRing.length < 10) withoutRing.push(focused.label);
    await page.keyboard.press("Tab");
  }
  return { tabbed, withoutRing };
}

const browser = await chromium.launch();
const report = {};
try {
  for (const scheme of SCHEMES) {
    for (const width of WIDTHS) {
      for (const recipe of RECIPES) {
        const page = await browser.newPage({
          viewport: { width, height: 900 },
          colorScheme: scheme,
          reducedMotion: "reduce",
        });
        if (recipe) await page.addInitScript((name) => { document.documentElement.dataset.recipe = name; }, recipe);
        if (LOGIN) await signIn(page);
        const suffix = recipe ? `-${recipe}` : "";
        for (const route of routes) {
          await page.goto(`http://127.0.0.1:${PORT}${route}`, { waitUntil: "networkidle" });
          await page.evaluate(() => document.fonts.ready);
          const name = `${route === "/" ? "home" : route.slice(1).replaceAll("/", "-")}-${width}-${scheme}${suffix}`;
          await page.screenshot({ path: `${shots}/${name}.png`, fullPage: true });
          report[name] = await page.evaluate(measure);
          if (A11Y) report[name].keyboard = await keyboardPass(page);
          for (const state of STATES) {
            // the mock API's state for the next load only (the key is read per request)
            await page.evaluate((value) => localStorage.setItem("bga-mock-state", value), state === "loading" ? "slow" : state);
            await page.goto(`http://127.0.0.1:${PORT}${route}`, { waitUntil: state === "loading" ? "domcontentloaded" : "networkidle" });
            if (state === "loading") await page.waitForTimeout(600);
            await page.screenshot({ path: `${shots}/${name}-${state}.png`, fullPage: true });
            report[`${name}-${state}`] = await page.evaluate(measure);
            await page.evaluate(() => localStorage.removeItem("bga-mock-state"));
          }
        }
        await page.close();
      }
    }
  }
  if (process.env.DESIGN_CHECK_MOTION === "1") {
    for (const route of routes) {
      report[`${route === "/" ? "home" : route.slice(1).replaceAll("/", "-")}-motion`] = await motionPass(browser, route);
    }
  }
} finally {
  await browser.close();
  server.kill();
}
writeFileSync(`${shots}/report.json`, JSON.stringify(report, null, 2));
console.log(`design check: ${Object.keys(report).length} page views → ${shots}/report.json`);
