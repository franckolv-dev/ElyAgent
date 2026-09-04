/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/scheduled/__tests__/nouvelle-tache-et-mission.test.ts
 * @brief      La page des tâches planifiées offre un bouton « Nouvelle
 *             tâche » et une case « exécuter comme mission ».
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// 04/09/2026 : le formulaire de création existait mais ne s'ouvrait que
// depuis une suggestion d'Ely — créer une tâche à la main passait par le
// chat. Et une tâche peut désormais lancer une MISSION (pont 0036).
const RACINE = join(__dirname, "..");
const page = readFileSync(join(RACINE, "page.tsx"), "utf-8");
const lib = readFileSync(join(RACINE, "..", "..", "lib", "scheduler.ts"), "utf-8");
const fr = JSON.parse(readFileSync(join(RACINE, "..", "..", "..", "messages", "fr.json"), "utf-8"));
const en = JSON.parse(readFileSync(join(RACINE, "..", "..", "..", "messages", "en.json"), "utf-8"));

describe("la page des tâches planifiées", () => {
  it("ouvre le formulaire de création sans suggestion", () => {
    expect(page).toContain("openCreateBlank");
    expect(page).toContain('t("createNew")');
  });

  it("propose d'exécuter la tâche comme mission et l'envoie à l'API", () => {
    expect(page).toContain('t("createAsMission")');
    expect(page).toContain("as_mission: prefill.asMission");
    expect(lib).toContain("as_mission?: boolean");
    expect(lib).toContain("as_mission: boolean");
  });

  it("signale les tâches qui lancent une mission", () => {
    expect(page).toContain("task.as_mission");
    expect(page).toContain('t("badgeMission")');
  });

  it("montre les cinq champs du cron et un exemple par cas courant", () => {
    // « min heure jour-du-mois mois jour-de-semaine » + UN exemple ne disait
    // pas comment écrire « tous les jours à 19h30 » (Franck, 04/09).
    expect(page).toContain('t("createCronFields")');
    for (const expr of ["30 12 * * *", "0 8 * * 1-5", "0 9 * * 1", "0 */2 * * *"]) {
      expect(page).toContain(expr);
    }
    expect(page).not.toContain("createCronHint");
  });

  it("a ses traductions dans les deux langues", () => {
    for (const cle of ["createNew", "createModalIntroManual", "createAsMission", "createAsMissionHint", "badgeMission", "badgeMissionHint", "createCronFields", "createCronEgDaily", "createCronEgWeekdays", "createCronEgMonday", "createCronEgEveryTwoHours", "createCronUseExample"]) {
      expect(fr.scheduled[cle]).toBeTruthy();
      expect(en.scheduled[cle]).toBeTruthy();
    }
  });
});
