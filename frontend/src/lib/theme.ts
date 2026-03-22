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
})();
`.trim();
