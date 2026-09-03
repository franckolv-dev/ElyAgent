/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/mandate.ts
 * @brief      C6 — générateur de spec v2 avec mandat d'autonomie. Le mandat
 *             se déclarait UNIQUEMENT à la main dans le YAML « Mission
 *             structurée » (piège UX vécu 2×) — ce module + le formulaire
 *             de la modal le génèrent proprement.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 */

/** Miroir de MANDATE_TOOL_FAMILIES (backend mission_spec.py) — vocabulaire
 *  FERMÉ. Le serveur reste le validateur : une famille ajoutée côté backend
 *  sans être listée ici reste utilisable à la main dans le YAML. */
export const MANDATE_TOOL_FAMILIES = [
  "email", "calendar", "contacts", "tasks", "drive", "docs", "sheets",
  "web", "files", "vision", "maps", "youtube", "github", "pdf", "notes",
  "memory", "knowledge", "messaging", "scheduler", "media",
] as const;

/** Défauts des seuils de NOTIFICATION (pas des plafonds bloquants) —
 *  miroir de MandateBudgets côté backend. */
export const DEFAULT_DAILY_TOOL_ACTIONS_NOTIFY = 500;
export const DEFAULT_DAILY_LLM_CALLS_NOTIFY = 100;

export interface MandateFormValues {
  toolsAllow: string[];
  autonomy: "autonomous" | "supervised";
  onUnforeseen: "escalate" | "decide";
  /** "" = null côté spec → le tier COMPLEX est forcé à l'exécution (D3). */
  llmTier: "" | "simple" | "medium" | "complex";
  dailyToolActionsNotify: number;
  dailyLlmCallsNotify: number;
}

export const MANDATE_FORM_DEFAULTS: MandateFormValues = {
  toolsAllow: [],
  autonomy: "autonomous",
  onUnforeseen: "escalate",
  llmTier: "",
  dailyToolActionsNotify: DEFAULT_DAILY_TOOL_ACTIONS_NOTIFY,
  dailyLlmCallsNotify: DEFAULT_DAILY_LLM_CALLS_NOTIFY,
};

/** Génère une spec v2 COMPLÈTE (mandate + steps squelette) prête à éditer.
 *  Fonction pure — le YAML émis suit exactement le contrat parse_mission_spec
 *  (indentation 2 espaces, clés du vocabulaire fermé) ; le serveur revalide
 *  à la création (422 avec toutes les erreurs). Remplace le contenu du
 *  textarea (le formulaire demande confirmation si non vide). */
export function buildMandateSpecYaml(v: MandateFormValues): string {
  const lines: string[] = ["version: 2", "mandate:"];
  lines.push(`  tools_allow: [${v.toolsAllow.join(", ")}]`);
  lines.push(`  autonomy: ${v.autonomy}`);
  lines.push(`  on_unforeseen: ${v.onUnforeseen}`);
  if (v.llmTier) lines.push(`  llm_tier: ${v.llmTier}`);
  const budgetLines: string[] = [];
  if (v.dailyToolActionsNotify !== DEFAULT_DAILY_TOOL_ACTIONS_NOTIFY) {
    budgetLines.push(`    daily_tool_actions_notify: ${v.dailyToolActionsNotify}`);
  }
  if (v.dailyLlmCallsNotify !== DEFAULT_DAILY_LLM_CALLS_NOTIFY) {
    budgetLines.push(`    daily_llm_calls_notify: ${v.dailyLlmCallsNotify}`);
  }
  if (budgetLines.length) {
    lines.push("  budgets:", ...budgetLines);
  }
  lines.push(
    "steps:",
    "  - id: etape_1",
    '    do: "Décris ici la première étape de la mission"',
  );
  return lines.join("\n") + "\n";
}
