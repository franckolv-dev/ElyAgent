#!/usr/bin/env node
/**
 * @project    ELY — Exactly Like You
 * @file       scripts/screenshots/take-screenshots.mjs
 * @brief      Génère 28 captures d'écran pour le site agent-ely.fr.
 *
 * 7 pages × 2 thèmes (dark / light) × 2 langues (fr / en) = 28 PNG haute résolution.
 *
 * Usage :
 *   cd scripts/screenshots
 *   npm install                # première fois (installe playwright)
 *   npx playwright install chromium   # première fois (télécharge le browser)
 *   node take-screenshots.mjs
 *
 * Variables d'environnement (toutes optionnelles) :
 *   ELY_BASE_URL    URL de ton instance (default: http://localhost:3000)
 *   ELY_LOGIN       admin (default: admin)
 *   ELY_PASSWORD    mot de passe admin (default: changeme)
 *   ELY_OUT_DIR     dossier de sortie (default: ./out)
 *   ELY_HEADED      "1" pour voir le navigateur (debug). Sinon headless.
 *   ELY_SCALE       device pixel ratio (default: 2 pour Retina)
 *   ELY_VIEWPORT    "1920x1080" par défaut
 *
 * Sortie : ./out/<page>-<theme>-<lang>.png
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 */
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";

// ─── Config ──────────────────────────────────────────────────────────────────

const BASE_URL  = process.env.ELY_BASE_URL  ?? "http://localhost:3000";
const API_URL   = process.env.ELY_API_URL   ?? "http://localhost:8000";
const LOGIN     = process.env.ELY_LOGIN     ?? "admin";
const PASSWORD  = process.env.ELY_PASSWORD  ?? "changeme";
const OUT_DIR   = process.env.ELY_OUT_DIR   ?? path.resolve("out");
const HEADED    = process.env.ELY_HEADED    === "1";
const SCALE     = parseInt(process.env.ELY_SCALE ?? "2", 10);
const [VW, VH]  = (process.env.ELY_VIEWPORT ?? "1920x1080").split("x").map(Number);

// 7 pages à capturer. Le selector "ready" est ce qu'on attend pour considérer
// la page stable avant le screenshot (évite les états de chargement).
const PAGES = [
  { slug: "chat",       path: "/chat",         ready: ".chat-empty, .chat-suggestions, [data-chat-message]" },
  { slug: "missions",   path: "/missions",     ready: "main h1, main h2, button:has-text('Nouvelle')" },
  { slug: "ai-models",  path: "/settings",     ready: "[role='tablist'], main h2", afterReady: async (page) => {
    // Settings ouvre par défaut sur "Modèles IA" — rien à faire, mais on
    // attend les cards d'instances qui se chargent en async.
    await page.waitForTimeout(800);
  } },
  { slug: "hitl",       path: "/settings",     ready: "[role='tablist']", afterReady: async (page) => {
    // Switch sur l'onglet HITL Confirmations
    await page.getByRole("tab", { name: /HITL|Confirmations|Confirmations HITL/i }).click().catch(() => {});
    await page.waitForTimeout(1200);
  } },
  { slug: "dashboard",  path: "/dashboard",    ready: "svg, main", afterReady: async (page) => {
    // Le BarChart est SVG, on lui laisse le temps d'animer
    await page.waitForTimeout(1500);
  } },
  { slug: "arena",      path: "/arena",        ready: "main h1, textarea, [data-arena-prompt]" },
  { slug: "security",   path: "/security",     ready: "main h1, [data-security-tile], main h2" },
];

const THEMES  = ["dark", "light"];
const LOCALES = ["fr", "en"];

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** POST /auth/login → { access_token } */
async function loginAndGetToken() {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: LOGIN, password: PASSWORD }),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`Login failed (${res.status}): ${txt.slice(0, 200)}`);
  }
  const data = await res.json();
  if (!data.access_token) throw new Error(`Login OK but no access_token in response`);
  return data.access_token;
}

/** Inject locale cookie + theme + token in localStorage BEFORE the page loads. */
async function preparePage(context, token, theme, locale) {
  // Locale via cookie NEXT_LOCALE (next-intl pattern)
  await context.addCookies([{
    name: "NEXT_LOCALE",
    value: locale,
    url: BASE_URL,
    sameSite: "Lax",
  }]);
  // Theme + token via localStorage — injectés AVANT navigation via init script
  await context.addInitScript(({ tk, th }) => {
    try {
      window.localStorage.setItem("cyber_entity_token", tk);
      window.localStorage.setItem("ely-theme", th);
    } catch (e) { /* SecurityError on first navigation, ignored */ }
  }, { tk: token, th: theme });
}

/** Wait for the page to be visually settled. */
async function waitForStable(page, readySelector) {
  await page.waitForLoadState("domcontentloaded");
  // Premier signal : un sélecteur attendu est visible
  if (readySelector) {
    await page.waitForSelector(readySelector, { timeout: 15_000, state: "attached" }).catch(() => {});
  }
  // Deuxième signal : le réseau se calme
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
  // Buffer pour les animations CSS (avatar pulse, transitions theme, etc.)
  await page.waitForTimeout(500);
}

// ─── Main ────────────────────────────────────────────────────────────────────

async function run() {
  console.log(`▶ ELY screenshots — base=${BASE_URL} → out=${OUT_DIR}`);
  console.log(`  viewport=${VW}x${VH} scale=${SCALE} headed=${HEADED ? "yes" : "no"}`);

  await mkdir(OUT_DIR, { recursive: true });

  console.log(`▶ Authenticating as ${LOGIN}…`);
  const token = await loginAndGetToken();
  console.log(`  ✓ Token obtained (${token.length} chars)`);

  const browser = await chromium.launch({ headless: !HEADED });
  let count = 0;
  const total = PAGES.length * THEMES.length * LOCALES.length;

  try {
    for (const locale of LOCALES) {
      for (const theme of THEMES) {
        // Un context par combo (locale, theme) pour éviter les fuites entre pages
        const context = await browser.newContext({
          viewport: { width: VW, height: VH },
          deviceScaleFactor: SCALE,
          // Force aussi prefers-color-scheme côté CSS pour les composants qui
          // s'y appuient (au cas où data-theme ne suffirait pas)
          colorScheme: theme,
        });
        await preparePage(context, token, theme, locale);

        for (const p of PAGES) {
          count++;
          const filename = `${p.slug}-${theme}-${locale}.png`;
          const filepath = path.join(OUT_DIR, filename);
          process.stdout.write(`  [${String(count).padStart(2, "0")}/${total}] ${filename} …`);

          const page = await context.newPage();
          try {
            await page.goto(`${BASE_URL}${p.path}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
            await waitForStable(page, p.ready);
            if (p.afterReady) await p.afterReady(page);
            // Re-stabiliser après afterReady (qui peut déclencher des fetches)
            await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => {});
            await page.waitForTimeout(400);
            await page.screenshot({ path: filepath, fullPage: true });
            console.log(" ✓");
          } catch (err) {
            console.log(` ✗  ${err.message.split("\n")[0]}`);
          } finally {
            await page.close();
          }
        }
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }

  console.log(`▶ Done. ${count} screenshots in ${OUT_DIR}`);
  console.log(`  Tip: pour les optimiser pour le web → \`npx @squoosh/cli --webp '{}' out/*.png\``);
}

run().catch((err) => {
  console.error("FATAL:", err);
  process.exit(1);
});
