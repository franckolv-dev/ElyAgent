import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// 03/09/2026 : une mission se décrit par son objectif et tourne sur la boucle
// du chat (#370). La spec YAML et le formulaire de mandat, qui générait cette
// spec, quittent le formulaire de création. Les missions structurées déjà en
// base restent lisibles sur leur page de détail.
const RACINE = join(__dirname, "..");
const creation = readFileSync(join(RACINE, "page.tsx"), "utf-8");
const detail = readFileSync(join(RACINE, "[id]", "page.tsx"), "utf-8");

describe("le formulaire de mission", () => {
  it("ne propose plus de spec YAML", () => {
    expect(creation).not.toContain("spec_yaml");
    expect(creation).not.toContain("specToggle");
    expect(creation).not.toContain("specPlaceholder");
  });

  it("ne génère plus de mandat en YAML", () => {
    expect(creation).not.toContain("buildMandateSpecYaml");
    expect(creation).not.toContain("mandateGenerate");
    expect(creation).not.toContain("@/lib/mandate");
  });

  it("garde l'objectif, les budgets et l'autonomie", () => {
    for (const champ of ["goal", "budget_iterations", "budget_tokens", "autonomous"]) {
      expect(creation).toContain(champ);
    }
  });
});

describe("la page de détail", () => {
  it("affiche encore les missions structurées existantes", () => {
    expect(detail).toContain("StructuredRunPanel");
    expect(detail).toContain("missionsApi.structure(");
  });
});
