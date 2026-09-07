import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// 07/09/2026 — « Plateformes littéraires » a épuisé ses 5 M de tokens à deux
// pas du but. Il n'y avait pas de bouton pour la relancer en gardant son
// carnet, et le formulaire plafonnait à 5 M.
const RACINE = join(__dirname, "..");
const creation = readFileSync(join(RACINE, "page.tsx"), "utf-8");
const detail = readFileSync(join(RACINE, "[id]", "page.tsx"), "utf-8");

describe("relancer une mission", () => {
  it("a un bouton qui garde le carnet et fixe un nouveau budget", () => {
    expect(detail).toContain("missionsApi.restart(");
    expect(detail).toContain("keep_history");
    expect(detail).toContain("max_tokens");
    expect(detail).toContain("Relancer");
  });

  it("repart tout de suite après la relance", () => {
    // restart remet la mission en brouillon ; sans start, elle attend un clic de plus.
    expect(detail).toMatch(/missionsApi\.restart\([\s\S]*?missionsApi\.start\(/);
  });
});

describe("le budget de tokens", () => {
  it("plafonne à dix millions dans le formulaire de création", () => {
    expect(creation).toContain("10_000_000");
    expect(creation).not.toContain("max={5_000_000}");
  });
});
