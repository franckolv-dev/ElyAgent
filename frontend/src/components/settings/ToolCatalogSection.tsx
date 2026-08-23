/* =============================================================================
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/settings/ToolCatalogSection.tsx
 * @brief      Ce que chaque outil coûte à chaque tour, et ce qu'il a servi.
 * @license    Elastic License 2.0
 * ============================================================================
 *
 * ⚠️ POURQUOI CET ÉCRAN EXISTE (24/08).
 *
 *   Franck, en regardant la charge réelle reçue par gemma dans LM Studio :
 *   « À quoi sert le dernier outil qrcode_generate ? Quel intérêt d'envoyer
 *     un tel outil, voire même d'avoir un tel outil ? »
 *
 * La question était juste et sans réponse : rien nulle part ne disait ce qu'un
 * outil coûte ni s'il avait déjà servi. 200 outils, ~60 900 tokens de schémas
 * envoyés à chaque tour, et aucune façon de trier.
 *
 * L'écran ne tranche pas à la place de l'utilisateur — il met les deux chiffres
 * côte à côte et la décision se prend seule :
 *
 *     qrcode_generate    235 tokens/tour    0 appel
 *
 * ⚠️ « 0 appel » ne veut pas dire « inutile » : l'outil a pu ne jamais servir
 * parce que personne n'en a eu besoin, ou parce que le modèle ne l'a jamais
 * trouvé. D'où la fenêtre d'observation affichée en clair sous le total.
 *
 * ⚠️ Le coût est une APPROXIMATION (le vrai découpage dépend du tokenizer de
 * chaque modèle) et l'écran le dit — « ≈ » partout, et une note. Un chiffre
 * faux présenté comme exact ferait supprimer des outils sur du vent.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ChevronDown, ChevronRight, Loader2, ToggleLeft, ToggleRight, Wrench,
} from "lucide-react";
import { api } from "@/lib/api";

type Tool = {
  name: string;
  description: string;
  approx_tokens: number;
  calls: number;
};

type SkillRow = {
  name: string;
  display_name: string;
  icon: string;
  enabled: boolean;
  enabled_by_default: boolean;
  tool_count: number;
  approx_tokens: number;
  calls: number;
  tools: Tool[];
};

type Catalog = {
  enabled_tool_count: number;
  enabled_approx_tokens: number;
  total_tool_count: number;
  usage_since: string | null;
  skills: SkillRow[];
};

const nombre = (n: number) => n.toLocaleString("fr-FR");

export function ToolCatalogSection() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [ouverts, setOuverts] = useState<Set<string>>(new Set());
  const [enCours, setEnCours] = useState<string | null>(null);

  const charger = useCallback(async () => {
    try {
      setCatalog(await api.getToolCatalog());
      setErreur(null);
    } catch {
      setErreur("Catalogue indisponible.");
    }
  }, []);

  useEffect(() => { void charger(); }, [charger]);

  const basculer = async (skill: SkillRow) => {
    setEnCours(skill.name);
    // Optimiste, mais on RECHARGE derrière : le total en tête doit refléter
    // ce que le backend a réellement retenu, pas ce que l'écran a supposé.
    setCatalog((c) => c && {
      ...c,
      skills: c.skills.map((s) =>
        s.name === skill.name ? { ...s, enabled: !s.enabled } : s),
    });
    try {
      await api.updateSkill(skill.name, { enabled: !skill.enabled });
    } finally {
      await charger();
      setEnCours(null);
    }
  };

  if (erreur) {
    return <p className="text-sm text-[var(--text-secondary)]">{erreur}</p>;
  }
  if (!catalog) {
    return (
      <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
        <Loader2 className="w-4 h-4 animate-spin" /> Chargement du catalogue…
      </div>
    );
  }

  const depuis = catalog.usage_since
    ? new Date(catalog.usage_since).toLocaleDateString("fr-FR")
    : null;

  return (
    <div className="space-y-4">
      {/* Le bandeau : ce qui part RÉELLEMENT au modèle à chaque tour. C'est
          ce chiffre qui bouge quand on actionne un interrupteur, donc le seul
          qui aide à décider. */}
      <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
          <span className="text-2xl font-semibold text-[var(--text-primary)]">
            ≈ {nombre(catalog.enabled_approx_tokens)} tokens
          </span>
          <span className="text-sm text-[var(--text-secondary)]">
            envoyés à chaque tour · {catalog.enabled_tool_count} outils actifs
            sur {catalog.total_tool_count}
          </span>
        </div>
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          Estimation à partir de la description et du schéma de chaque outil —
          le découpage exact dépend du modèle.
          {depuis && <> Appels comptés depuis le {depuis}.</>}{" "}
          Un outil jamais appelé n&apos;est pas forcément inutile : il a pu ne
          jamais être nécessaire.
        </p>
      </div>

      <ul className="space-y-2">
        {catalog.skills.map((s) => {
          const ouvert = ouverts.has(s.name);
          return (
            <li
              key={s.name}
              className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)]"
            >
              <div className="flex items-center gap-3 p-3">
                <button
                  type="button"
                  onClick={() => setOuverts((o) => {
                    const n = new Set(o);
                    n.has(s.name) ? n.delete(s.name) : n.add(s.name);
                    return n;
                  })}
                  className="flex flex-1 items-center gap-3 text-left"
                  aria-expanded={ouvert}
                >
                  {ouvert
                    ? <ChevronDown className="w-4 h-4 shrink-0 text-[var(--text-muted)]" />
                    : <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" />}
                  <span className="text-base">{s.icon || "🔧"}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-[var(--text-primary)]">
                      {s.display_name}
                    </span>
                    <span className="block text-xs text-[var(--text-muted)]">
                      {s.tool_count} outil{s.tool_count > 1 ? "s" : ""}
                      {" · "}≈ {nombre(s.approx_tokens)} tk
                      {" · "}
                      {s.calls === 0
                        ? <span className="text-[var(--text-muted)]">jamais appelée</span>
                        : <>{nombre(s.calls)} appel{s.calls > 1 ? "s" : ""}</>}
                    </span>
                  </span>
                </button>

                <button
                  type="button"
                  onClick={() => void basculer(s)}
                  disabled={enCours === s.name}
                  aria-label={s.enabled ? "Désactiver" : "Activer"}
                  className="shrink-0 disabled:opacity-40"
                >
                  {s.enabled
                    ? <ToggleRight className="w-8 h-8 text-[var(--accent)]" />
                    : <ToggleLeft className="w-8 h-8 text-[var(--text-muted)]" />}
                </button>
              </div>

              {ouvert && (
                <ul className="border-t border-[var(--border-default)] px-3 py-2">
                  {s.tools.map((t) => (
                    <li
                      key={t.name}
                      className="flex items-baseline gap-3 py-1.5 text-xs"
                    >
                      <Wrench className="w-3 h-3 shrink-0 translate-y-0.5 text-[var(--text-muted)]" />
                      <code className="shrink-0 text-[var(--text-primary)]">{t.name}</code>
                      <span className="min-w-0 flex-1 truncate text-[var(--text-muted)]">
                        {t.description}
                      </span>
                      <span className="shrink-0 tabular-nums text-[var(--text-secondary)]">
                        ≈ {nombre(t.approx_tokens)} tk
                      </span>
                      <span
                        className={`shrink-0 tabular-nums ${
                          t.calls === 0
                            ? "text-[var(--text-muted)]"
                            : "text-[var(--text-secondary)]"
                        }`}
                      >
                        {nombre(t.calls)} appel{t.calls > 1 ? "s" : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
