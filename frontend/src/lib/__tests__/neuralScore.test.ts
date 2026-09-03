import { describe, expect, it } from "vitest";

import { neuralScoreForModel } from "../neuralScore";

// Audit 02/09/2026 : le « score neural » affiché à côté du modèle était
// produit par Math.random() — un chiffre inventé, qui changeait à chaque
// tour pour le même modèle. Il reflète désormais le palier du modèle, et
// rien d'autre.
describe("neuralScoreForModel", () => {
  it("rend le même score pour le même modèle", () => {
    for (const m of ["claude-opus-5", "gpt-5.6-sol", "google/gemma-4-26b-a4b", "inconnu"]) {
      expect(neuralScoreForModel(m)).toBe(neuralScoreForModel(m));
    }
  });

  it("ordonne les paliers", () => {
    expect(neuralScoreForModel("claude-opus-5")).toBeGreaterThan(neuralScoreForModel("claude-haiku-4-5"));
    expect(neuralScoreForModel("mistral-large-latest")).toBeGreaterThan(neuralScoreForModel("mistral-small-latest"));
  });

  it("reste dans l'échelle 0-100", () => {
    for (const m of ["opus", "sonnet", "haiku", "flash", "qwen", "gpt-5.6", "gemma", ""]) {
      const s = neuralScoreForModel(m);
      expect(s).toBeGreaterThanOrEqual(0);
      expect(s).toBeLessThanOrEqual(100);
    }
  });
});
