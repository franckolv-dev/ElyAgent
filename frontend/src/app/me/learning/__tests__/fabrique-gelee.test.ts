import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// La page ne doit jamais appeler la fabrique gelée, même au premier clic.
const page = readFileSync(join(__dirname, "..", "incidents", "page.tsx"), "utf-8");
const fr = JSON.parse(readFileSync(join(__dirname, "..", "..", "..", "..", "..", "messages", "fr.json"), "utf-8"));
const en = JSON.parse(readFileSync(join(__dirname, "..", "..", "..", "..", "..", "messages", "en.json"), "utf-8"));

describe("les corrections d’incidents", () => {
  it("ne propose plus une génération impossible, même au premier affichage", () => {
    expect(page).not.toContain("adminLearningIncidentGenerate");
    expect(page).not.toContain("generateTool");
    expect(page).not.toContain('t("generate")');
  });

  it("offre une correction applicable et son annulation", () => {
    expect(page).toContain("inc.repair_available");
    expect(page).toContain("api.adminLearningApplyPatch");
    expect(page).toContain("api.adminLearningRevertPatch");
  });

  it("distingue correction active et résultat vérifié dans les deux langues", () => {
    for (const dict of [fr, en]) {
      expect(dict.incidents.verification_pending).toBeTruthy();
      expect(dict.incidents.verification_succeeded).toBeTruthy();
      expect(dict.incidents.verification_failed).toBeTruthy();
      expect(dict.incidents.manualRequired).toBeTruthy();
    }
  });
});
