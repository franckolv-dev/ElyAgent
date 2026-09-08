import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// 08/09/2026 — « Générer un outil » : trois clics, rien. Le backend répondait
// `status: "frozen"` (la fabrique d'outils est gelée depuis #370) et la page
// ne montrait qu'un flash fugace « Génération échouée (status: frozen) »,
// puis proposait à nouveau le bouton. Désormais la raison s'affiche sur la
// carte, le bouton disparaît, et les deux issues restantes sont claires.
const page = readFileSync(join(__dirname, "..", "incidents", "page.tsx"), "utf-8");
const fr = JSON.parse(readFileSync(join(__dirname, "..", "..", "..", "..", "..", "messages", "fr.json"), "utf-8"));
const en = JSON.parse(readFileSync(join(__dirname, "..", "..", "..", "..", "..", "messages", "en.json"), "utf-8"));

describe("la fabrique d'outils gelée", () => {
  it("est reconnue dans la réponse et retenue pour la page", () => {
    expect(page).toContain('result.status === "frozen"');
    expect(page).toContain("setFabriqueGelee(");
  });

  it("cache le bouton et affiche la raison sur les cartes de la voie B", () => {
    expect(page).toMatch(/voie === "B" && !fabriqueGelee &&/);
    expect(page).toMatch(/voie === "B" && fabriqueGelee &&/);
  });

  it("a ses textes en français et en anglais", () => {
    for (const dict of [fr, en]) {
      expect(dict.incidents.frozen_title).toBeTruthy();
      expect(dict.incidents.frozen_hint).toBeTruthy();
    }
  });
});
