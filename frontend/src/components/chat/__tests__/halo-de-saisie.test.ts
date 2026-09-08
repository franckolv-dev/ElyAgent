import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// 08/09/2026 — tant qu'Ely travaille, un halo tourne autour de la zone de
// saisie (comme le mode IA de Google) : l'utilisateur voit qu'elle est
// occupée sans chercher un indicateur ailleurs. Discret : un liseré de deux
// pixels et une lueur douce, pas une guirlande.
const input = readFileSync(join(__dirname, "..", "ChatInput.tsx"), "utf-8");
const css = readFileSync(join(__dirname, "..", "..", "..", "styles", "globals.css"), "utf-8");

describe("le halo de saisie", () => {
  it("s'allume sur le dock quand Ely travaille, et seulement là", () => {
    expect(input).toMatch(/className=\{`ely-input-dock\$\{isLoading \? " is-working" : ""\}`\}/);
  });

  it("est un liseré en dégradé qui tourne, avec une lueur douce", () => {
    expect(css).toContain("@property --halo-angle");
    expect(css).toContain(".ely-input-dock.is-working::before");
    expect(css).toContain(".ely-input-dock.is-working::after");
    expect(css).toContain("conic-gradient(from var(--halo-angle)");
    expect(css).toContain("@keyframes ely-halo-spin");
    expect(css).toMatch(/\.ely-input-dock::before,\s*\.ely-input-dock::after\s*\{[^}]*inset:\s*-2px/);
    expect(css).toMatch(/\.ely-input-dock::after\s*\{[^}]*filter:\s*blur\(/);
  });

  it("ne tourne pas pour qui a demandé moins d'animations", () => {
    expect(css).toMatch(/prefers-reduced-motion: reduce\)[\s\S]*\.ely-input-dock\.is-working::before[\s\S]*animation:\s*none/);
  });

  it("n'empile pas le halo sur l'anneau de focus", () => {
    expect(css).toMatch(/\.ely-input-dock\.is-working:focus-within\s*\{[^}]*box-shadow:\s*none/);
  });
});
