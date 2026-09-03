// =============================================================================
// @project    ELY — Exactly Like You
// @file       frontend/vitest.config.ts
// @brief      Harnais de test du frontend.
// @license    MIT
//            https://opensource.org/licenses/MIT
// =============================================================================
//
// ⚠️ CE QUE ÇA CORRIGE (02/09/2026) : le frontend n'avait AUCUN test — zero
// fichier *.test.*, aucun script `npm test`, et la CI se limitait a
// `tsc --noEmit`. Les helpers purs de src/lib/ (conversion de cadence en cron,
// libelle humain d'un cron, generation du YAML de mandat) n'etaient donc
// verifies par rien.
//
// Environnement `node` volontairement : on teste des modules PURS, pas du
// rendu React. Pas de jsdom a installer tant que ce n'est pas necessaire.
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
