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

  // 09/09 — l'ombre est floutée SANS masque (un masque coupait le flou net :
  // « trop de type contour »), et passe sous une plaque opaque qui cache son
  // centre : liseré + plaque à z -1, ombre à z -2, le dock isole le contexte.
  it("est une ombre floutée sous une plaque opaque, jamais un contour masqué", () => {
    expect(css).toMatch(/\.ely-input-dock\s*\{[^}]*isolation:\s*isolate/);
    expect(css).toMatch(/\.ely-input-dock::before\s*\{[^}]*z-index:\s*-1[^}]*padding-box/);
    const apres = css.match(/\.ely-input-dock::after\s*\{([^}]*z-index[^}]*)\}/)?.[1] ?? "";
    expect(apres).toMatch(/z-index:\s*-2/);
    expect(apres).not.toMatch(/mask/);
  });

  it("ne tourne pas pour qui a demandé moins d'animations", () => {
    expect(css).toMatch(/prefers-reduced-motion: reduce\)[\s\S]*\.ely-input-dock\.is-working::before[\s\S]*animation:\s*none/);
  });

  it("n'empile pas le halo sur l'anneau de focus", () => {
    expect(css).toMatch(/\.ely-input-dock\.is-working:focus-within\s*\{[^}]*box-shadow:\s*none/);
  });
});
