import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { splitSentences } from "../tts";

// 08/09/2026 — XTTS synthétise plus vite que le temps réel, mais phrase par
// phrase : une réponse de trois phrases attendue d'un bloc coûte douze
// secondes, la première phrase seule une seconde et demie. Le client découpe
// et demande chaque phrase, la suivante se charge pendant que l'une se joue.

describe("splitSentences", () => {
  it("suit la ponctuation forte", () => {
    expect(splitSentences("Bonjour Franck. Tu veux que je réserve la salle ? Bien sûr, je m'en occupe !")).toEqual([
      "Bonjour Franck.",
      "Tu veux que je réserve la salle ?",
      "Bien sûr, je m'en occupe !",
    ]);
  });

  it("ne coupe pas sur un nombre ni sur une abréviation", () => {
    expect(splitSentences("Rendez-vous à 14h30. Tarif : 12.50 euros, M. Dupont confirme.")).toEqual([
      "Rendez-vous à 14h30.",
      "Tarif : 12.50 euros, M. Dupont confirme.",
    ]);
  });

  it("regroupe les miettes", () => {
    expect(splitSentences("Oui. Non. Peut-être.")).toEqual(["Oui. Non. Peut-être."]);
  });

  it("rend vide pour du vide", () => {
    expect(splitSentences("  \n ")).toEqual([]);
  });
});

describe("les deux lecteurs demandent phrase par phrase", () => {
  const tts = readFileSync(join(__dirname, "..", "tts.ts"), "utf-8");
  const hook = readFileSync(join(__dirname, "..", "..", "hooks", "useVoiceConversation.ts"), "utf-8");

  it("le lecteur du chat enchaîne les phrases avec une avance de chargement", () => {
    expect(tts).toContain("splitSentences(");
    expect(tts).toMatch(/prefetch|suivante|next/i);
  });

  it("le mode voix passe par le même lecteur", () => {
    expect(hook).toContain("speakSentences(");
    expect(hook).not.toContain('body: JSON.stringify({ text })');
  });
});
