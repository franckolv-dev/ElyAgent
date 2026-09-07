import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// 07/09/2026 — le coffre existait côté API (AES-GCM, Argon2id) mais n'avait
// aucune interface : impossible de le créer, de le déverrouiller ou d'y
// déposer un secret. Une mission qui crée un compte pour l'utilisateur y range
// le mot de passe ; il faut donc pouvoir l'ouvrir et le lire.
const RACINE = join(__dirname, "..", "..", "..");
const section = readFileSync(join(__dirname, "..", "VaultSection.tsx"), "utf-8");
const settings = readFileSync(join(RACINE, "app", "settings", "page.tsx"), "utf-8");
const api = readFileSync(join(RACINE, "lib", "api.ts"), "utf-8");
const fr = JSON.parse(readFileSync(join(RACINE, "..", "messages", "fr.json"), "utf-8"));
const en = JSON.parse(readFileSync(join(RACINE, "..", "messages", "en.json"), "utf-8"));

describe("le coffre a une interface", () => {
  it("est rendu dans l'onglet Mon compte", () => {
    expect(settings).toContain("<VaultSection");
    expect(settings).toContain('activeTab === "compte" && <VaultSection');
  });

  it("sait déverrouiller, verrouiller, lister, ajouter et supprimer", () => {
    for (const fn of ["vaultStatus", "vaultUnlock", "vaultLock", "vaultSecrets", "vaultStore", "vaultDelete"]) {
      expect(api).toContain(`${fn}:`);
      expect(section).toContain(`api.${fn}(`);
    }
    expect(api).toContain("/api/vault/unlock");
    expect(api).toContain("/api/vault/secrets");
  });

  it("montre la référence à donner à Ely et ne réaffiche jamais une valeur", () => {
    expect(section).toContain("vault://");
    expect(section).toContain('type="password"');
  });

  it("a ses textes en français et en anglais", () => {
    for (const dict of [fr, en]) {
      const v = dict.settings.vaultSection;
      for (const cle of ["title", "intro", "unlock", "lock", "masterPassword", "label", "value", "hint", "add", "delete", "empty", "reference"]) {
        expect(v[cle], cle).toBeTruthy();
      }
    }
  });
});
