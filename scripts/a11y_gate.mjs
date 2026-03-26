import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { extname, join, normalize } from "node:path";

import { chromium } from "playwright";

const require = createRequire(import.meta.url);
const AXE_SOURCE_PATH = require.resolve("axe-core/axe.min.js");

const HOST = "127.0.0.1";
const PORT = 4173;
const ROOT = process.cwd();
const START_PATH = "/index.html";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".mjs": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
};

function safePath(urlPath) {
  const cleanPath = (urlPath || "/").split("?")[0].split("#")[0];
  const target = cleanPath === "/" ? START_PATH : cleanPath;
  const normalized = normalize(target).replace(/^([.][.][/\\])+/, "");
  return join(ROOT, normalized);
}

function createStaticServer() {
  return createServer(async (req, res) => {
    try {
      const filePath = safePath(req.url || START_PATH);
      const bytes = await readFile(filePath);
      const contentType = MIME[extname(filePath).toLowerCase()] || "application/octet-stream";
      res.writeHead(200, {
        "Content-Type": contentType,
        "Cache-Control": "no-store",
      });
      res.end(bytes);
    } catch {
      res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("Not found");
    }
  });
}

function printViolations(violations) {
  for (const violation of violations) {
    const impact = violation.impact || "unknown";
    console.error(`- [${impact}] ${violation.id}: ${violation.description}`);
    for (const node of violation.nodes.slice(0, 3)) {
      console.error(`  target: ${node.target.join(" ")}`);
      console.error(`  failure: ${node.failureSummary || "n/a"}`);
    }
  }
}

async function run() {
  const server = createStaticServer();
  await new Promise((resolve) => server.listen(PORT, HOST, resolve));

  let browser;
  let context;
  let failed = false;

  try {
    browser = await chromium.launch({ headless: true });
    context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
    const page = await context.newPage();

    await page.addInitScript(() => {
    class SilentWebSocket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;

      constructor() {
        this.readyState = SilentWebSocket.CONNECTING;
        setTimeout(() => {
          this.readyState = SilentWebSocket.CLOSED;
          if (typeof this.onclose === "function") {
            this.onclose({ code: 1006, reason: "ws disabled in a11y gate" });
          }
        }, 0);
      }

      send() {}

      close() {
        this.readyState = SilentWebSocket.CLOSED;
        if (typeof this.onclose === "function") {
          this.onclose({ code: 1000, reason: "closed" });
        }
      }

      addEventListener() {}
      removeEventListener() {}
    }

    window.WebSocket = SilentWebSocket;
    });

    const url = `http://${HOST}:${PORT}${START_PATH}`;
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(700);

    await page.addScriptTag({ path: AXE_SOURCE_PATH });
    const axeResults = await page.evaluate(async () => {
      return window.axe.run(document, {
        runOnly: {
          type: "tag",
          values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"],
        },
      });
    });

    const blockingAxeViolations = axeResults.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious"
    );

    const semanticIssues = await page.evaluate(() => {
    const issues = [];

    const mains = document.querySelectorAll("main, [role='main']");
    if (mains.length !== 1) {
      issues.push(`Expected exactly 1 main landmark, found ${mains.length}.`);
    }

    const interactive = Array.from(document.querySelectorAll("input, select, textarea"));
    for (const el of interactive) {
      const tag = el.tagName.toLowerCase();
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (tag === "input" && ["hidden", "submit", "button", "reset", "image"].includes(type)) {
        continue;
      }
      const hasVisibleLabel =
        (el.labels && Array.from(el.labels).some((label) => (label.textContent || "").trim().length > 0)) ||
        Boolean((el.getAttribute("aria-label") || "").trim()) ||
        Boolean((el.getAttribute("aria-labelledby") || "").trim());
      if (!hasVisibleLabel) {
        const marker = el.id ? `#${el.id}` : `<${tag}>`;
        issues.push(`Form control ${marker} is missing an accessible label.`);
      }
    }

    const statusIds = ["st-text", "source-badge", "audio-status"];
    for (const id of statusIds) {
      const el = document.getElementById(id);
      if (!el) {
        issues.push(`Missing status element #${id}.`);
        continue;
      }
      const ownLive = el.getAttribute("aria-live") || el.getAttribute("role") === "status";
      let inheritedLive = false;
      let p = el.parentElement;
      while (p && !inheritedLive) {
        inheritedLive = Boolean(p.getAttribute("aria-live") || p.getAttribute("role") === "status");
        p = p.parentElement;
      }
      if (!ownLive && !inheritedLive) {
        issues.push(`#${id} should be in an aria-live/status region.`);
      }
    }

    const canvases = Array.from(document.querySelectorAll("canvas"));
    for (const canvas of canvases) {
      const hasName =
        Boolean((canvas.getAttribute("aria-label") || "").trim()) ||
        Boolean((canvas.getAttribute("aria-labelledby") || "").trim()) ||
        (canvas.textContent || "").trim().length > 0;
      if (!hasName) {
        const marker = canvas.id ? `#${canvas.id}` : "<canvas>";
        issues.push(`Canvas ${marker} should expose a text alternative.`);
      }
    }

      return issues;
    });

    const requiredFocusIds = [
      "experience-select",
      "escalation-regulator",
      "audio-toggle-btn",
      "line-trim-preset",
    ];

    const focusSequence = [];
    const uniqueFocused = new Set();
    let unchangedStreak = 0;
    let lastKey = "";

    for (let i = 0; i < 70; i += 1) {
      await page.keyboard.press("Tab");
      const focus = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el) {
          return { key: "none", id: "", isInteractive: false, hasFocusRing: false };
        }
        const tag = el.tagName.toLowerCase();
        const id = el.id || "";
        const role = el.getAttribute("role") || "";
        const key = id ? `#${id}` : `${tag}[role='${role}']`;
        const style = window.getComputedStyle(el);
        const outlineVisible = style.outlineStyle !== "none" && parseFloat(style.outlineWidth || "0") > 0;
        const boxShadowVisible = Boolean(style.boxShadow && style.boxShadow !== "none");
        const isInteractive = ["a", "button", "input", "select", "textarea"].includes(tag) || el.hasAttribute("tabindex");
        return { key, id, isInteractive, hasFocusRing: outlineVisible || boxShadowVisible };
      });

      focusSequence.push(focus.key);
      uniqueFocused.add(focus.key);

      if (focus.key === lastKey) {
        unchangedStreak += 1;
      } else {
        unchangedStreak = 0;
        lastKey = focus.key;
      }
    }

    const focusIssues = [];
    if (uniqueFocused.size < 10) {
      focusIssues.push(`Keyboard focus reached only ${uniqueFocused.size} unique targets (expected >= 10).`);
    }

    for (const id of requiredFocusIds) {
      if (!focusSequence.includes(`#${id}`)) {
        focusIssues.push(`Keyboard tab path never reached #${id}.`);
      }
    }

    if (unchangedStreak >= 8) {
      focusIssues.push("Potential keyboard trap detected (focus repeated without progression).");
    }

    failed =
      blockingAxeViolations.length > 0 || semanticIssues.length > 0 || focusIssues.length > 0;

    if (blockingAxeViolations.length > 0) {
      console.error("\nAxe serious/critical violations:");
      printViolations(blockingAxeViolations);
    }

    if (semanticIssues.length > 0) {
      console.error("\nSemantic/label gate failures:");
      for (const issue of semanticIssues) {
        console.error(`- ${issue}`);
      }
    }

    if (focusIssues.length > 0) {
      console.error("\nKeyboard focus gate failures:");
      for (const issue of focusIssues) {
        console.error(`- ${issue}`);
      }
    }

    if (!failed) {
      console.log("Accessibility gate passed: axe-core + focus traversal + semantic label checks.");
    }
  } finally {
    if (context) {
      await context.close();
    }
    if (browser) {
      await browser.close();
    }
    await new Promise((resolve) => server.close(resolve));

    if (failed) {
      process.exitCode = 1;
    }
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
