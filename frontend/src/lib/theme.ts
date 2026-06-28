/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/theme.ts
 * @brief      Theme utilities — colour scheme and FOUC prevention
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *            https://www.elastic.co/licensing/elastic-license
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */
/** Minimal theme manager — persists 'dark' | 'light' in localStorage. */

const KEY = "ely-theme";
export type Theme = "dark" | "light";

export function getTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  return (localStorage.getItem(KEY) as Theme) ?? "dark";
}

export function applyTheme(theme: Theme) {
  const html = document.documentElement;
  html.classList.remove("dark", "light");
  html.classList.add(theme);
  // Also set data-theme on <body> so the new design tokens (--bg-app etc.)
  // resolve correctly. The CSS rules in globals.css honor BOTH selectors
  // so legacy components (html.light) keep working during the refonte.
  if (typeof document !== "undefined" && document.body) {
    document.body.dataset.theme = theme;
  }
  localStorage.setItem(KEY, theme);
}

export function toggleTheme(): Theme {
  const next: Theme = getTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  return next;
}

/** Inline script string — paste into <script> to avoid FOUC. */
export const THEME_SCRIPT = `
(function(){
  var t=localStorage.getItem('ely-theme')||'dark';
  document.documentElement.classList.add(t);
  // data-theme on body for the new design tokens (refonte mai 2026)
  document.addEventListener('DOMContentLoaded', function(){
    if (document.body) document.body.dataset.theme = t;
  });
  if (document.body) document.body.dataset.theme = t;
})();
`.trim();
