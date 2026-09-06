import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Audit GPT-6 F14 (06/09/2026) : la barre de la page de mission est
// `iterations_used / budget_iterations` — un taux de consommation du budget,
// pas un avancement du livrable. Une mission à 90 % de son budget peut
// n'avoir rien accompli. La page doit nommer ce qu'elle mesure.
const detail = readFileSync(join(__dirname, "..", "[id]", "page.tsx"), "utf-8");

describe("la page de détail d'une mission", () => {
  it("nomme la barre comme un budget consommé, pas un avancement", () => {
    expect(detail).toContain("Budget d'itérations consommé");
  });
});
