import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// 07/09/2026 : une mission libre peut poser une question et attendre la
// réponse (statut `waiting_user`). La page de détail montre la question et un
// champ de réponse ; la liste connaît le statut.
const RACINE = join(__dirname, "..");
const lib = readFileSync(join(RACINE, "..", "..", "lib", "missions.ts"), "utf-8");
const detail = readFileSync(join(RACINE, "[id]", "page.tsx"), "utf-8");
const liste = readFileSync(join(RACINE, "page.tsx"), "utf-8");

describe("une mission qui attend une réponse", () => {
  it("a un statut connu de la bibliothèque et de la liste", () => {
    expect(lib).toContain('"waiting_user"');
    expect(lib).toContain("waiting_user:");
    expect(lib).toContain("pending_question");
    expect(lib).toContain("answer: (id: string, answer: string)");
    expect(liste).toContain('"waiting_user"');
  });

  it("montre la question et un champ de réponse sur la page de détail", () => {
    expect(detail).toContain("mission.pending_question");
    expect(detail).toContain("missionsApi.answer(");
  });
});
