"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/transparence/page.tsx
 * @brief      Le contrat visible et le registre de sortie, en un ecran.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *            https://www.elastic.co/licensing/elastic-license
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */

/**
 * ⚠️ POURQUOI CETTE PAGE (audit du 02/09/2026)
 *
 * Ely tient deux garanties que peu d'agents tiennent, et aucune des deux ne se
 * VOYAIT : la nature de chaque outil decide de qui tranche, et la PII est
 * masquee avant tout appel a un modele. La donnee existait, eparpillee sur
 * quatre modules backend ; la promesse, elle, ne vivait que dans le README.
 *
 * Deux onglets pour deux questions, pas deux pages : « qu'a-t-elle le droit de
 * faire pour moi » et « qu'est-ce qui est sorti de ma machine » sont la meme
 * interrogation prise par ses deux bouts, et les lire cote a cote est le point.
 *
 * ⚠️ CE QUE CETTE PAGE NE PROMET PAS. Le registre de sortie n'affiche AUCUN
 * compteur de masquages : `usage_logs` ne sait pas dire qu'une valeur a ete
 * remplacee pendant un tour donne, et un « 12 donnees masquees » invente ici
 * detruirait la seule chose qu'une page de transparence apporte. Elle annonce
 * la regle, l'echantillon sur lequel porte la composition, et le fait que le
 * cout est ESTIME — le depot a exactement cette discipline ailleurs.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations, useLocale } from "next-intl";
import {
  AlertTriangle, Cloud, Eye, FileWarning, HardDrive, HelpCircle,
  Loader2, Lock, RefreshCw, Scale, ScrollText, Search, ShieldCheck, Target,
} from "lucide-react";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";
import {
  api,
  type ContractTool,
  type EgressKind,
  type TransparencyContract,
  type TransparencyEgress,
} from "@/lib/api";

type Tab = "contract" | "egress";
type Filtre = "all" | "always" | "engaging" | "revertible" | "mine";

/** Les fenetres proposees. Le backend plafonne a 92 ; on ne propose pas plus. */
const FENETRES = [1, 7, 30, 92] as const;

const EFFETS = ["LECTURE", "ECRITURE", "ENGAGEANT"] as const;

/** Un effet, une couleur — la meme partout sur la page, sinon rien n'est lisible. */
const TEINTE_EFFET: Record<string, string> = {
  LECTURE: "text-cyber-cyan border-cyber-cyan/30 bg-cyber-cyan/10",
  ECRITURE: "text-amber-300 border-amber-500/30 bg-amber-500/10",
  ENGAGEANT: "text-red-300 border-red-500/30 bg-red-500/10",
};

const TEINTE_DESTINATION: Record<EgressKind, string> = {
  local: "text-emerald-300 border-emerald-500/30 bg-emerald-500/10",
  cloud: "text-amber-300 border-amber-500/30 bg-amber-500/10",
  unknown: "text-text-muted border-border-dim bg-bg-tertiary",
};

// ─────────────────────────────────────────────────────────────────────────
// Briques
// ─────────────────────────────────────────────────────────────────────────

function Tuile({ value, label, help }: { value: string; label: string; help: string }) {
  return (
    <div className="bg-bg-secondary border border-border-dim rounded-lg p-3">
      <p className="text-xl font-mono text-text-primary">{value}</p>
      <p className="text-[11px] text-text-secondary mt-0.5">{label}</p>
      <p className="text-[10px] text-text-muted mt-1 leading-snug">{help}</p>
    </div>
  );
}

function Puce({ children, tone }: { children: React.ReactNode; tone: string }) {
  return (
    <span className={`px-1.5 py-0.5 text-[10px] font-mono rounded border whitespace-nowrap ${tone}`}>
      {children}
    </span>
  );
}

function Bandeau({
  tone, icon, title, children,
}: {
  tone: "danger" | "warn" | "ok";
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  const styles = {
    danger: "bg-red-500/10 border-red-500/30 text-red-300",
    warn: "bg-amber-500/10 border-amber-500/30 text-amber-300",
    ok: "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  }[tone];
  return (
    <div className={`flex gap-2 px-3 py-2.5 rounded border text-xs ${styles}`}>
      <span className="shrink-0 mt-0.5">{icon}</span>
      <div className="min-w-0">
        <p className="font-medium">{title}</p>
        <div className="mt-1 text-[11px] opacity-90 leading-snug">{children}</div>
      </div>
    </div>
  );
}

function Section({
  icon, title, lead, children,
}: {
  icon: React.ReactNode;
  title: string;
  lead?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
      <header className="px-4 py-3 border-b border-border-dim">
        <div className="flex items-center gap-2">
          <span className="text-cyber-cyan">{icon}</span>
          <h2 className="text-sm font-medium text-text-primary">{title}</h2>
        </div>
        {lead && <p className="mt-1 text-[11px] text-text-muted leading-snug">{lead}</p>}
      </header>
      {children}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Onglet 1 — le contrat
// ─────────────────────────────────────────────────────────────────────────

function OngletContrat({ data }: { data: TransparencyContract }) {
  const t = useTranslations("transparency");
  const locale = useLocale();
  const nb = useMemo(() => new Intl.NumberFormat(locale), [locale]);

  const [recherche, setRecherche] = useState("");
  const [filtre, setFiltre] = useState<Filtre>("all");
  const [ouvertes, setOuvertes] = useState<Set<string>>(new Set());

  const s = data.summary;

  const garde = (outil: ContractTool): boolean => {
    switch (filtre) {
      case "always": return outil.approval === "always";
      case "engaging": return outil.effect === "ENGAGEANT";
      case "revertible": return outil.revertible;
      case "mine": return outil.user_preference !== null;
      default: return true;
    }
  };

  const terme = recherche.trim().toLowerCase();
  const familles = data.families
    .map((f) => ({
      ...f,
      items: f.items.filter(
        (i) => garde(i) && (!terme || i.name.toLowerCase().includes(terme)),
      ),
    }))
    .filter((f) => f.items.length > 0);

  const bascule = (nom: string) =>
    setOuvertes((cur) => {
      const suivant = new Set(cur);
      if (suivant.has(nom)) suivant.delete(nom);
      else suivant.add(nom);
      return suivant;
    });

  // Une regle unique : des que le tri laisse peu d'outils, on les montre.
  // Replier ce qu'on vient de chercher forcerait un second clic pour rien ;
  // deplier les 211 d'un coup redonnerait l'annuaire qu'on voulait fuir.
  const restants = familles.reduce((n, f) => n + f.items.length, 0);
  const deplie = (nom: string) => ouvertes.has(nom) || restants <= 40;

  const totalEffets = EFFETS.reduce((acc, e) => acc + (s.by_effect[e] ?? 0), 0) || 1;

  return (
    <div className="space-y-4">
      <p className="text-[11px] text-text-secondary bg-bg-secondary border border-border-dim rounded px-3 py-2 leading-snug">
        {t("contractLead")}
      </p>

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <Tuile value={nb.format(s.tools)} label={t("statTools")} help={t("statToolsHelp")} />
        <Tuile value={nb.format(s.approval_always)} label={t("statAlways")} help={t("statAlwaysHelp")} />
        <Tuile value={nb.format(s.approval_risk_based)} label={t("statRiskBased")} help={t("statRiskBasedHelp")} />
        <Tuile value={nb.format(s.approval_never)} label={t("statNever")} help={t("statNeverHelp")} />
        <Tuile value={nb.format(s.revertible)} label={t("statRevertible")} help={t("statRevertibleHelp")} />
      </div>

      {/* ⚠️ Le compte des annulables dit ce qui est OUTILLÉ. Drapeau éteint,
          rien n'entre au journal : la tuile seule mentirait par omission. */}
      {!s.revertible_journal_enabled && (
        <Bandeau tone="warn" icon={<AlertTriangle className="w-4 h-4" />} title={t("journalOffTitle")}>
          {t("journalOff")}
        </Bandeau>
      )}

      {/* Axe 1 — l'effet. Une barre, parce que la proportion EST l'information. */}
      <Section icon={<Scale className="w-4 h-4" />} title={t("axisEffect")}>
        <div className="p-4 space-y-3">
          <div className="flex h-2 rounded overflow-hidden bg-bg-tertiary">
            {EFFETS.map((e) => (
              <div
                key={e}
                className={
                  e === "LECTURE" ? "bg-cyber-cyan"
                    : e === "ECRITURE" ? "bg-amber-400" : "bg-red-400"
                }
                style={{ width: `${((s.by_effect[e] ?? 0) / totalEffets) * 100}%` }}
              />
            ))}
          </div>
          <ul className="grid gap-2 sm:grid-cols-3">
            {EFFETS.map((e) => (
              <li key={e} className="flex flex-col gap-1">
                <div className="flex items-baseline gap-2">
                  <Puce tone={TEINTE_EFFET[e]}>{t(`effect_${e}`)}</Puce>
                  <span className="text-sm font-mono text-text-primary">
                    {nb.format(s.by_effect[e] ?? 0)}
                  </span>
                </div>
                <p className="text-[10px] text-text-muted leading-snug">{t(`effectHelp_${e}`)}</p>
              </li>
            ))}
          </ul>
          {/* Le second axe annonce par `contractLead`. Sans son titre, la page
              promettait deux axes et n'en nommait qu'un. */}
          <div className="pt-2 border-t border-border-dim/60">
            <p className="text-[11px] font-medium text-text-primary">{t("axisArbitration")}</p>
            <p className="mt-0.5 text-[11px] text-text-secondary">
              <Target className="inline w-3 h-3 mr-1 -mt-0.5 text-cyber-cyan" />
              {t("arbitrationLead", { count: s.arbitrating, total: s.tools })}
            </p>
          </div>
        </div>
      </Section>

      {/* Les deux ecarts qui doivent sauter aux yeux. */}
      {s.unguarded_engaging.length > 0 && (
        <Bandeau tone="danger" icon={<AlertTriangle className="w-4 h-4" />} title={t("alertUnguardedTitle")}>
          <p>{t("alertUnguardedBody")}</p>
          <p className="mt-1 font-mono">{s.unguarded_engaging.join(", ")}</p>
        </Bandeau>
      )}
      {s.neutralized_user_waivers.length > 0 && (
        <Bandeau tone="warn" icon={<FileWarning className="w-4 h-4" />} title={t("alertNeutralizedTitle")}>
          <p>{t("alertNeutralizedBody")}</p>
          <p className="mt-1 font-mono">{s.neutralized_user_waivers.join(", ")}</p>
        </Bandeau>
      )}

      <Section icon={<ShieldCheck className="w-4 h-4" />} title={t("yourPreferencesTitle")}>
        <ul className="p-4 grid gap-2 sm:grid-cols-3 text-[11px] text-text-secondary">
          <li><span className="font-mono text-text-primary">{nb.format(s.waived_by_user)}</span> {t("prefWaived")}</li>
          <li><span className="font-mono text-text-primary">{nb.format(s.rearmed_by_user)}</span> {t("prefRearmed")}</li>
          <li className="flex items-baseline gap-1">
            <Lock className="w-3 h-3 shrink-0 self-center text-text-muted" />
            <span><span className="font-mono text-text-primary">{nb.format(s.never_waivable)}</span> {t("prefNeverWaivable")}</span>
          </li>
        </ul>
      </Section>

      {/* ⚠️ Cette section ne se cache PLUS quand la liste est vide (relecture
          du 02/09/2026). Toutes les dispenses d'instance ne sont pas ecrites
          dans la table des natures : l'envoi de mail « a soi-meme » est
          decide en dur dans la passerelle et dans le noyau des missions, et
          il coupe la garde de plusieurs outils d'envoi. Une page qui masque
          la section quand la table est vide laisserait croire que l'instance
          ne dispense rien — c'est exactement le mensonge par omission qu'elle
          existe pour empecher. */}
      <Section
        icon={<ScrollText className="w-4 h-4" />}
        title={t("instanceWaiversTitle")}
        lead={t("instanceWaiversLead")}
      >
        {(data.instance_waivers ?? []).length === 0 ? (
          <p className="px-4 py-3 text-[11px] text-text-muted">{t("instanceWaiversEmpty")}</p>
        ) : (
          <ul className="divide-y divide-border-dim/50">
            {(data.instance_waivers ?? []).map((w) => (
              <li key={w.tool} className="px-4 py-2.5">
                <p className="text-xs font-mono text-text-primary">{w.tool}</p>
                <p className="text-[11px] text-text-muted mt-0.5 leading-snug">{w.reason}</p>
              </li>
            ))}
          </ul>
        )}
        <p className="px-4 py-2.5 text-[11px] text-text-muted border-t border-border-dim leading-snug">
          {t("instanceWaiversSelfMail")}
        </p>
      </Section>

      <Section icon={<Target className="w-4 h-4" />} title={t("mandatesTitle")} lead={t("mandatesLead")}>
        {data.mandates.length === 0 ? (
          <p className="px-4 py-6 text-center text-xs text-text-muted">{t("mandatesEmpty")}</p>
        ) : (
          <ul className="divide-y divide-border-dim/50">
            {data.mandates.map((m) => (
              <li key={m.mission_id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-text-primary">{m.title}</span>
                  <Puce tone="text-text-muted border-border-dim bg-bg-tertiary">{m.status}</Puce>
                  {m.autonomy_state && (
                    <Puce tone="text-cyber-cyan border-cyber-cyan/30 bg-cyber-cyan/10">
                      {m.autonomy_state}
                    </Puce>
                  )}
                </div>
                {m.unreadable ? (
                  <p className="mt-1.5 text-[11px] text-amber-300">{t("mandateUnreadable")}</p>
                ) : (
                  <dl className="mt-2 grid gap-x-4 gap-y-1 sm:grid-cols-2 text-[11px]">
                    <div className="flex gap-1.5">
                      <dt className="text-text-muted">{t("mandateAutonomy")}</dt>
                      <dd className="text-text-secondary font-mono">{m.autonomy ?? "—"}</dd>
                    </div>
                    <div className="flex gap-1.5">
                      <dt className="text-text-muted">{t("mandateUnforeseen")}</dt>
                      <dd className="text-text-secondary font-mono">{m.on_unforeseen ?? "—"}</dd>
                    </div>
                    <div className="flex gap-1.5">
                      <dt className="text-text-muted">{t("mandateTier")}</dt>
                      <dd className="text-text-secondary font-mono">{m.llm_tier ?? "—"}</dd>
                    </div>
                    <div className="flex gap-1.5">
                      <dt className="text-text-muted">{t("mandateBudgets")}</dt>
                      <dd className="text-text-secondary font-mono">
                        {Object.entries(m.budgets).map(([k, v]) => `${k}=${v}`).join(" · ") || "—"}
                      </dd>
                    </div>
                    <div className="sm:col-span-2 flex flex-wrap gap-1.5 items-baseline">
                      <dt className="text-text-muted">{t("mandateTools")}</dt>
                      <dd className="flex flex-wrap gap-1">
                        {m.tools_allow.length === 0
                          ? <span className="text-text-muted">{t("mandateToolsNone")}</span>
                          : m.tools_allow.map((tool) => (
                            <Puce key={tool} tone="text-text-secondary border-border-dim bg-bg-tertiary">
                              {tool}
                            </Puce>
                          ))}
                      </dd>
                    </div>
                  </dl>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Le detail vient APRES le resume : 211 lignes brutes ne repondent a rien. */}
      <Section icon={<Search className="w-4 h-4" />} title={t("familiesTitle")}>
        <div className="px-4 py-3 border-b border-border-dim space-y-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted" />
            <input
              value={recherche}
              onChange={(e) => setRecherche(e.target.value)}
              placeholder={t("searchPlaceholder")}
              className="w-full pl-8 pr-3 py-1.5 text-xs rounded border border-border-dim bg-bg-tertiary text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/50"
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(["all", "always", "engaging", "revertible", "mine"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFiltre(f)}
                className={`px-2 py-0.5 text-[10px] rounded border transition-colors ${
                  filtre === f
                    ? "border-cyber-cyan/50 bg-cyber-cyan/10 text-cyber-cyan"
                    : "border-border-dim text-text-muted hover:text-text-secondary"
                }`}
              >
                {t(`filter${f.charAt(0).toUpperCase()}${f.slice(1)}`)}
              </button>
            ))}
          </div>
        </div>

        {familles.length === 0 ? (
          <p className="px-4 py-6 text-center text-xs text-text-muted">{t("noMatch")}</p>
        ) : (
          <ul className="divide-y divide-border-dim/50">
            {familles.map((f) => (
              <li key={f.family}>
                <button
                  onClick={() => bascule(f.family)}
                  className="w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-bg-primary/40 transition-colors"
                >
                  <span className="text-xs font-mono text-text-primary">{f.family}</span>
                  <span className="text-[10px] text-text-muted">
                    {t("familyToolCount", { count: f.items.length })}
                  </span>
                  <span className="ml-auto flex gap-1">
                    {EFFETS.filter((e) => f.items.some((i) => i.effect === e)).map((e) => (
                      <Puce key={e} tone={TEINTE_EFFET[e]}>
                        {t(`effect_${e}`)} {f.items.filter((i) => i.effect === e).length}
                      </Puce>
                    ))}
                  </span>
                </button>
                {deplie(f.family) && (
                  <div className="overflow-x-auto border-t border-border-dim/50">
                    <table className="w-full text-[11px]">
                      <thead>
                        <tr className="text-text-muted text-left">
                          <th className="px-4 py-1.5 font-normal">{t("colTool")}</th>
                          <th className="px-2 py-1.5 font-normal">{t("colEffect")}</th>
                          <th className="px-2 py-1.5 font-normal">{t("colApproval")}</th>
                          <th className="px-2 py-1.5 font-normal">{t("colRevertible")}</th>
                          <th className="px-4 py-1.5 font-normal">{t("colYours")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {f.items.map((i) => (
                          <tr key={i.name} className="border-t border-border-dim/30">
                            <td className="px-4 py-1.5 font-mono text-text-secondary">
                              {i.name}
                              {i.arbitrates && (
                                <span className="ml-1.5 text-[9px] text-cyber-purple">
                                  {t("arbitratesBadge")}
                                </span>
                              )}
                            </td>
                            <td className="px-2 py-1.5">
                              <Puce tone={TEINTE_EFFET[i.effect] ?? TEINTE_EFFET.LECTURE}>
                                {t(`effect_${i.effect}`)}
                              </Puce>
                            </td>
                            <td className="px-2 py-1.5 text-text-muted">
                              <span title={i.waiver_reason ?? undefined}>
                                {t(`approval_${i.approval}`)}
                              </span>
                              {!i.waivable && (
                                <Lock className="inline w-3 h-3 ml-1 -mt-0.5 text-text-muted" />
                              )}
                            </td>
                            <td className="px-2 py-1.5 text-text-muted">
                              {i.revertible ? (
                                <span className="text-emerald-400" title={i.compensation ?? undefined}>
                                  {t("yes")}
                                </span>
                              ) : t("no")}
                            </td>
                            <td className="px-4 py-1.5 text-text-muted">
                              {i.user_preference === null ? "—" : (
                                <>
                                  {t(`pref_${i.user_preference}`)}
                                  {!i.user_preference_effective && (
                                    <span className="ml-1 text-amber-300">({t("prefIgnored")})</span>
                                  )}
                                </>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Onglet 2 — le registre de sortie
// ─────────────────────────────────────────────────────────────────────────

const ICONE_DESTINATION: Record<EgressKind, React.ReactNode> = {
  local: <HardDrive className="w-4 h-4" />,
  cloud: <Cloud className="w-4 h-4" />,
  unknown: <HelpCircle className="w-4 h-4" />,
};

function OngletSortie({
  data, days, onDays,
}: {
  data: TransparencyEgress;
  days: number;
  onDays: (d: number) => void;
}) {
  const t = useTranslations("transparency");
  const locale = useLocale();
  const nb = useMemo(() => new Intl.NumberFormat(locale), [locale]);

  const tot = data.totals;
  const part = (n: number) => (tot.calls ? Math.round((n / tot.calls) * 1000) / 10 : 0);
  const parKind: Record<EgressKind, number> = {
    local: tot.local_calls, cloud: tot.cloud_calls, unknown: tot.unknown_calls,
  };
  const maxJour = Math.max(
    1, ...data.by_day.map((d) => d.local + d.cloud + d.unknown),
  );

  return (
    <div className="space-y-4">
      {/* Dire d'ou vient le chiffre fait partie du chiffre : ce qui n'a pas
          laisse de ligne dans le journal d'usage n'apparait nulle part ici. */}
      <p className="text-[11px] text-text-secondary bg-bg-secondary border border-border-dim rounded px-3 py-2 leading-snug">
        {t("egressLead")}{" "}
        <span className="text-text-muted">{t("egressSource")}</span>
      </p>

      <div className="flex flex-wrap items-center gap-1.5">
        {FENETRES.map((d) => (
          <button
            key={d}
            onClick={() => onDays(d)}
            className={`px-2 py-0.5 text-[10px] rounded border transition-colors ${
              days === d
                ? "border-cyber-cyan/50 bg-cyber-cyan/10 text-cyber-cyan"
                : "border-border-dim text-text-muted hover:text-text-secondary"
            }`}
          >
            {t(`window_${d}`)}
          </button>
        ))}
        <span className="text-[10px] text-text-muted ml-1">
          {t("windowCapped", { days: data.max_window_days })}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {(["local", "cloud", "unknown"] as const).map((k) => (
          <div key={k} className="bg-bg-secondary border border-border-dim rounded-lg p-3">
            <div className="flex items-center gap-2">
              <span className={TEINTE_DESTINATION[k].split(" ")[0]}>{ICONE_DESTINATION[k]}</span>
              <p className="text-xl font-mono text-text-primary">{nb.format(parKind[k])}</p>
              <span className="text-[10px] text-text-muted ml-auto">
                {t("shareOfCalls", { share: part(parKind[k]) })}
              </span>
            </div>
            <p className="text-[11px] text-text-secondary mt-1">{t(`kind_${k}`)}</p>
            <p className="text-[10px] text-text-muted mt-1 leading-snug">{t(`kindHelp_${k}`)}</p>
          </div>
        ))}
      </div>

      {tot.calls === 0 ? (
        <p className="px-4 py-6 text-center text-xs text-text-muted bg-bg-secondary border border-border-dim rounded-lg">
          {t("egressEmpty")}
        </p>
      ) : (
        <>
          {/* Ventile par DATE — un jour vide est une information, pas un trou. */}
          <Section icon={<ScrollText className="w-4 h-4" />} title={t("byDayTitle")}>
            {/* ⚠️ PAS d'`items-end` sur ce conteneur (relecture du 02/09/2026).
                Il remplace l'etirement transverse par un alignement : la
                colonne prend alors la hauteur de son CONTENU, et une barre
                dont la hauteur est un POURCENTAGE d'un parent en hauteur
                automatique se resout a zero. Mesure au navigateur avec
                `items-end` : colonnes de 2 px (les seuls `gap`), barres de
                0 px — la frise ne peignait rien. L'etirement par defaut donne
                aux colonnes une hauteur DEFINIE, contre laquelle les
                pourcentages se resolvent ; le `justify-end` de la colonne
                suffit a coller les barres en bas. */}
            <div className="p-4 flex gap-1 h-28">
              {data.by_day.map((d) => {
                const total = d.local + d.cloud + d.unknown;
                return (
                  <div
                    key={d.day}
                    className="flex-1 flex flex-col justify-end gap-px min-w-[3px]"
                    title={`${d.day} · ${nb.format(total)}`}
                  >
                    <div className="bg-text-muted/40" style={{ height: `${(d.unknown / maxJour) * 100}%` }} />
                    <div className="bg-amber-400" style={{ height: `${(d.cloud / maxJour) * 100}%` }} />
                    <div className="bg-emerald-400" style={{ height: `${(d.local / maxJour) * 100}%` }} />
                  </div>
                );
              })}
            </div>
            <div className="px-4 pb-3 flex justify-between text-[10px] text-text-muted font-mono">
              <span>{data.by_day[0]?.day}</span>
              <span>{data.by_day[data.by_day.length - 1]?.day}</span>
            </div>
          </Section>

          <Section icon={<Cloud className="w-4 h-4" />} title={t("destinationsTitle")}>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-text-muted text-left">
                    <th className="px-4 py-1.5 font-normal">{t("colProvider")}</th>
                    <th className="px-2 py-1.5 font-normal">{t("colModels")}</th>
                    <th className="px-2 py-1.5 font-normal text-right">{t("colCalls")}</th>
                    <th className="px-2 py-1.5 font-normal text-right">{t("colTokensIn")}</th>
                    <th className="px-2 py-1.5 font-normal text-right">{t("colTokensOut")}</th>
                    <th className="px-4 py-1.5 font-normal text-right">{t("colCost")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.destinations.map((d) => (
                    <tr key={d.provider} className="border-t border-border-dim/30">
                      <td className="px-4 py-1.5">
                        <Puce tone={TEINTE_DESTINATION[d.kind]}>{d.provider}</Puce>
                      </td>
                      <td className="px-2 py-1.5 font-mono text-text-muted">{d.models.join(", ") || "—"}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-text-secondary">{nb.format(d.calls)}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-text-muted">{nb.format(d.input_tokens)}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-text-muted">{nb.format(d.output_tokens)}</td>
                      <td className="px-4 py-1.5 text-right font-mono text-text-muted">${d.cost_usd.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="px-4 py-2 text-[10px] text-text-muted border-t border-border-dim leading-snug">
              {t("costEstimated")}
            </p>
          </Section>

          <div className="grid gap-4 lg:grid-cols-2">
            <Section
              icon={<Target className="w-4 h-4" />}
              title={t("purposesTitle")}
              lead={t("purposesCap", { cap: data.purposes_cap })}
            >
              <ul className="divide-y divide-border-dim/50">
                {data.purposes.map((p) => (
                  <li key={p.skill ?? "—"} className="flex items-baseline gap-2 px-4 py-1.5 text-[11px]">
                    <span className="font-mono text-text-secondary truncate">
                      {p.skill ?? t("purposeUnnamed")}
                    </span>
                    <span className="ml-auto font-mono text-text-muted">{nb.format(p.calls)}</span>
                  </li>
                ))}
              </ul>
            </Section>

            <Section icon={<Eye className="w-4 h-4" />} title={t("channelsTitle")}>
              <ul className="divide-y divide-border-dim/50">
                {data.channels.map((c) => (
                  <li key={c.channel} className="flex items-baseline gap-2 px-4 py-1.5 text-[11px]">
                    <span className="font-mono text-text-secondary">{c.channel}</span>
                    <span className="ml-auto font-mono text-text-muted">{nb.format(c.calls)}</span>
                  </li>
                ))}
              </ul>
            </Section>
          </div>

          {/* ⚠️ On DIT sur combien d'appels porte la ventilation : un pourcentage
              tire de trois tours ne doit pas passer pour la verite de la fenetre. */}
          <Section
            icon={<ScrollText className="w-4 h-4" />}
            title={t("compositionTitle")}
            lead={
              data.composition.sampled_calls === 0
                ? t("compositionNone")
                : t("compositionSample", {
                  sampled: data.composition.sampled_calls,
                  cap: data.composition.sample_cap,
                })
            }
          >
            {data.composition.categories.length > 0 && (
              <ul className="p-4 space-y-1.5">
                {data.composition.categories.map((c) => (
                  <li key={c.key} className="flex items-center gap-2 text-[11px]">
                    <span className="w-40 shrink-0 font-mono text-text-secondary truncate">{c.key}</span>
                    <span className="flex-1 h-1.5 rounded bg-bg-tertiary overflow-hidden">
                      <span className="block h-full bg-cyber-cyan" style={{ width: `${c.share}%` }} />
                    </span>
                    <span className="w-24 text-right font-mono text-text-muted">
                      {c.share}% · {nb.format(c.tokens)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </>
      )}

      <Section
        icon={<ShieldCheck className="w-4 h-4" />}
        title={t("maskingTitle")}
        lead={t("maskingRule")}
      >
        <div className="p-4 space-y-3">
          <div>
            <p className="text-[11px] text-text-secondary mb-1.5">{t("maskingAppliedTitle")}</p>
            <ul className="space-y-0.5">
              {data.masking.applied_on.map((m) => (
                <li key={m.path} className="text-[11px] text-text-secondary">
                  <span className="font-mono text-emerald-400">{m.path}</span>
                  <span className="text-text-muted"> — {m.what}</span>
                </li>
              ))}
            </ul>
          </div>
          {data.masking.not_applied_on.length > 0 && (
            <Bandeau tone="warn" icon={<AlertTriangle className="w-4 h-4" />} title={t("maskingNotAppliedTitle")}>
              <p>{t("maskingNotApplied")}</p>
              <ul className="mt-1 space-y-0.5">
                {data.masking.not_applied_on.map((m) => (
                  <li key={m.path}>
                    <span className="font-mono">{m.path}</span>
                    <span className="text-text-muted"> — {m.what}</span>
                  </li>
                ))}
              </ul>
            </Bandeau>
          )}
          <div>
            <p className="text-[11px] text-text-secondary mb-1.5">{t("maskingCategories")}</p>
            <div className="flex flex-wrap gap-1">
              {data.masking.regex_categories.map((c) => (
                <Puce key={c} tone="text-cyber-cyan border-cyber-cyan/30 bg-cyber-cyan/10">{c}</Puce>
              ))}
            </div>
          </div>
          <p className="text-[11px] text-text-secondary">
            {t("maskingNer")} :{" "}
            <span className={data.masking.ner_enabled ? "text-emerald-400" : "text-text-muted"}>
              {data.masking.ner_enabled ? t("maskingOn") : t("maskingOff")}
            </span>
          </p>
          {!data.masking.substitutions_measured && (
            <Bandeau tone="warn" icon={<AlertTriangle className="w-4 h-4" />} title={t("maskingNotMeasuredTitle")}>
              {t("maskingNotMeasured")}
            </Bandeau>
          )}
        </div>
      </Section>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// La page
// ─────────────────────────────────────────────────────────────────────────

export default function TransparencePage() {
  const t = useTranslations("transparency");

  const [tab, setTab] = useState<Tab>("contract");
  const [days, setDays] = useState<number>(7);

  const [contract, setContract] = useState<TransparencyContract | null>(null);
  const [egress, setEgress] = useState<TransparencyEgress | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const charger = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (tab === "contract") setContract(await api.transparencyContract());
      else setEgress(await api.transparencyEgress(days));
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : t(tab === "contract" ? "errorContract" : "errorEgress"),
      );
    } finally {
      setLoading(false);
    }
  }, [tab, days, t]);

  useEffect(() => { charger(); }, [charger]);

  const data = tab === "contract" ? contract : egress;

  return (
    <AuthGuard>
      <div className="flex flex-col h-screen overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar />
          <main
            className="flex-1 overflow-y-auto p-6 space-y-4"
            style={{ background: "var(--bg-app)" }}
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <Eye className="w-5 h-5 text-cyber-cyan" />
                <h1 className="text-lg font-medium text-text-primary">{t("title")}</h1>
                <span className="text-[11px] text-text-muted">{t("subtitle")}</span>
              </div>
              <div className="flex items-center gap-2">
                {contract && tab === "contract" && (
                  <span className="text-[10px] text-text-muted font-mono">
                    {t("generatedAt", { date: new Date(contract.generated_at).toLocaleString() })}
                  </span>
                )}
                <button
                  onClick={charger}
                  disabled={loading}
                  className="p-1.5 text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/10 rounded transition-colors disabled:opacity-50"
                  title={t("refresh")}
                >
                  {loading
                    ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    : <RefreshCw className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            <div className="flex gap-1 border-b border-border-dim">
              {(["contract", "egress"] as const).map((k) => (
                <button
                  key={k}
                  onClick={() => setTab(k)}
                  className={`px-3 py-1.5 text-xs border-b-2 -mb-px transition-colors ${
                    tab === k
                      ? "border-cyber-cyan text-cyber-cyan"
                      : "border-transparent text-text-muted hover:text-text-secondary"
                  }`}
                >
                  {k === "contract" ? t("tabContract") : t("tabEgress")}
                </button>
              ))}
            </div>

            {error && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                <AlertTriangle className="w-4 h-4" />
                {error}
              </div>
            )}

            {loading && !data && !error && (
              <div className="flex items-center justify-center py-12 text-text-muted">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                {t("loading")}
              </div>
            )}

            {tab === "contract" && contract && <OngletContrat data={contract} />}
            {tab === "egress" && egress && (
              <OngletSortie data={egress} days={days} onDays={setDays} />
            )}
          </main>
        </div>
      </div>
    </AuthGuard>
  );
}
