/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/__tests__/scheduler.test.ts
 * @brief      Premier test frontend du depot.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 */

/**
 * ⚠️ CE QUE ÇA CORRIGE (02/09/2026) : le frontend n'avait aucun test, et la CI
 * n'executait que `tsc --noEmit`. Or `cadenceToCron` et `describeCron` sont du
 * code de conversion pur : le typage ne dit rien de ce qu'ils CALCULENT. Une
 * inversion minute/heure, un jour de semaine decale, un cron a 6 champs mal
 * rejete — tout cela passait vert.
 *
 * Le test central est l'ALLER-RETOUR : la modal d'anticipation ecrit un cron
 * avec `cadenceToCron`, la liste des taches le relit avec `describeCron`. Les
 * deux vivent dans le meme fichier et personne ne verifiait qu'elles
 * s'accordent.
 */
import { describe, expect, it } from "vitest";

import { cadenceToCron, describeCron } from "../scheduler";

describe("cadenceToCron", () => {
  it("traduit une cadence quotidienne en cron a 5 champs", () => {
    expect(cadenceToCron("daily@09:00")).toBe("0 9 * * *");
    expect(cadenceToCron("daily@07:45")).toBe("45 7 * * *");
    expect(cadenceToCron("daily@00:00")).toBe("0 0 * * *");
  });

  it("place le jour de la semaine dans le 5e champ, pas ailleurs", () => {
    // dim=0 … sam=6 : l'ordre du cron POSIX, pas l'ordre francais.
    expect(cadenceToCron("weekly:sun@09:00")).toBe("0 9 * * 0");
    expect(cadenceToCron("weekly:mon@09:00")).toBe("0 9 * * 1");
    expect(cadenceToCron("weekly:fri@18:30")).toBe("30 18 * * 5");
    expect(cadenceToCron("weekly:sat@23:59")).toBe("59 23 * * 6");
  });

  it("rend null sur une cadence non reconnue plutot qu'un cron invalide", () => {
    // La modal retombe sur un champ vide ; un cron faux serait accepte par
    // le formulaire et refuse par le serveur, bien plus tard.
    expect(cadenceToCron("")).toBeNull();
    expect(cadenceToCron("daily@9:00")).toBeNull();      // heure non zero-padded
    expect(cadenceToCron("weekly:lun@09:00")).toBeNull(); // jour en francais
    expect(cadenceToCron("weekly:MON@09:00")).toBeNull(); // casse differente
    expect(cadenceToCron("monthly@09:00")).toBeNull();
  });
});

describe("describeCron", () => {
  it("nomme les motifs courants en francais", () => {
    expect(describeCron("0 9 * * *")).toBe("tous les jours à 09:00");
    expect(describeCron("30 8 * * 1-5")).toBe("en semaine à 08:30");
    expect(describeCron("0 9 * * 3")).toBe("chaque mer. à 09:00");
  });

  it("traite dow=7 comme dimanche, comme le fait cron", () => {
    // 0 et 7 designent tous deux dimanche ; un rendu « chaque undefined. »
    // serait le symptome d'un modulo oublie.
    expect(describeCron("0 9 * * 7")).toBe("chaque dim. à 09:00");
    expect(describeCron("0 9 * * 0")).toBe("chaque dim. à 09:00");
  });

  it("rend l'expression brute quand elle n'entre dans aucun motif", () => {
    expect(describeCron("*/15 * * * *")).toBe("*/15 * * * *");
    expect(describeCron("0 9 1 * *")).toBe("0 9 1 * *");
    expect(describeCron("0 9 * * 1,3")).toBe("0 9 * * 1,3");
    // 6 champs (cron avec secondes) : pas notre format, on ne devine pas.
    expect(describeCron("0 0 9 * * *")).toBe("0 0 9 * * *");
  });
});

describe("aller-retour cadence -> cron -> libelle", () => {
  it("relit ce que la modal a ecrit", () => {
    const cases: Array<[string, string]> = [
      ["daily@09:00", "tous les jours à 09:00"],
      ["daily@18:05", "tous les jours à 18:05"],
      ["weekly:mon@09:00", "chaque lun. à 09:00"],
      ["weekly:sun@07:30", "chaque dim. à 07:30"],
    ];
    for (const [cadence, expected] of cases) {
      const cron = cadenceToCron(cadence);
      expect(cron, `cadence non traduite : ${cadence}`).not.toBeNull();
      expect(describeCron(cron as string)).toBe(expected);
    }
  });
});
