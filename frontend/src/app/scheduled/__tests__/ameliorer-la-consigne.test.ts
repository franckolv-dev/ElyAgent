/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/scheduled/__tests__/ameliorer-la-consigne.test.ts
 * @brief      « Améliorer la consigne » vit sur la fiche de la tâche ; la page
 *             Incidents & propositions n'existe plus.
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// 19/09/2026 : la page Incidents accumulait 81 cartes depuis juin. « Confirmer »
// ne faisait rien, un correctif remplacé ne pouvait plus être vérifié, et chaque
// exécution douteuse coûtait un appel LLM. Il n'en reste que ce dont Franck se
// servait : la réécriture de consigne, demandée depuis la fiche de la tâche.
const RACINE = join(__dirname, "..");
const SRC = join(RACINE, "..", "..");
const page = readFileSync(join(RACINE, "page.tsx"), "utf-8");
const lib = readFileSync(join(SRC, "lib", "scheduler.ts"), "utf-8");
const api = readFileSync(join(SRC, "lib", "api.ts"), "utf-8");
const nav = readFileSync(join(SRC, "components", "layout", "nav.ts"), "utf-8");
const fr = JSON.parse(readFileSync(join(SRC, "..", "messages", "fr.json"), "utf-8"));
const en = JSON.parse(readFileSync(join(SRC, "..", "messages", "en.json"), "utf-8"));

describe("améliorer la consigne d'une tâche planifiée", () => {
  it("propose le bouton seulement quand la dernière exécution le demande", () => {
    expect(page).toContain("task.needs_attention && !task.prompt_patch");
    expect(page).toContain("schedulerApi.improvePrompt(task.id)");
  });

  it("montre l'avant / après, et permet d'appliquer, de rejeter ou de revenir en arrière", () => {
    expect(page).toContain("task.prompt_patch.old_value");
    expect(page).toContain("task.prompt_patch.new_value");
    for (const action of ['"apply"', '"reject"', '"revert"']) {
      expect(page).toContain(`onPatch(task, ${action})`);
    }
  });

  it("appelle les routes du planificateur, pas celles de l'administration", () => {
    expect(lib).toContain("/improve-prompt");
    expect(lib).toContain("/scheduler/prompt-patches/");
    expect(api).not.toContain("/admin/learning/incidents");
    expect(api).not.toContain("/admin/learning/patches");
  });

  it("a ses libellés dans les deux langues", () => {
    const cles = [
      "improve", "improveBusy", "improveHint", "improveProposed", "improveStateProposed",
      "improveStateApplied", "improveBefore", "improveAfter", "improveApply",
      "improveReject", "improveRevert", "improveApplied", "improveReverted", "improveRejected",
    ];
    for (const dict of [fr, en]) {
      for (const cle of cles) expect(dict.scheduled[cle], cle).toBeTruthy();
    }
  });
});

describe("la page Incidents & propositions", () => {
  it("n'existe plus : ni route, ni entrée de menu, ni libellés", () => {
    expect(existsSync(join(SRC, "app", "me", "learning", "incidents"))).toBe(false);
    expect(nav).not.toContain("/me/learning/incidents");
    for (const dict of [fr, en]) {
      expect(dict.incidents).toBeUndefined();
      expect(JSON.stringify(dict)).not.toContain("navLearningIncidents");
    }
  });
});
