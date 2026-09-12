/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/theme.ts
 * @brief      Theme utilities — colour scheme and FOUC prevention
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 */
/** Minimal theme manager — persists 'dark' | 'light' in localStorage. */

const KEY = "ely-theme";
export type Theme = "dark" | "light";

export function getTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  try { return localStorage.getItem(KEY) === "light" ? "light" : "dark"; }
  catch { return document.documentElement.classList.contains("light") ? "light" : "dark"; }
}

export function applyTheme(theme: Theme) {
  const html = document.documentElement;
  html.classList.remove("dark", "light");
  html.classList.add(theme);
  // Keep theme state on the hydration-suppressed root, not on body.
  html.dataset.theme = theme;
  document.body?.removeAttribute("data-theme");
  try { localStorage.setItem(KEY, theme); } catch { /* Storage can be disabled. */ }
}

export function toggleTheme(): Theme {
  const next: Theme = getTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  return next;
}

export const THEME_SCRIPT = `
(function(){
  var t='dark';
  try { if(localStorage.getItem('ely-theme')==='light') t='light'; } catch(e) {}
  document.documentElement.classList.add(t);
  document.documentElement.dataset.theme=t;
})();
`.trim();
