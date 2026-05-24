"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/me/state/page.tsx
 * @brief      Sprint 3 Jalon 3 — UI for the User State Vector.
 *             5 cartes (mood, current_focus, recent_topics, open_loops,
 *             energy_budget) + bouton "Recalculer maintenant" + toggle
 *             JSON brut. Sibling de /me/learning, même surface "radical
 *             transparency".
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 * @version    1.7.0
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Compass, Loader2, AlertCircle, RefreshCw, LayoutGrid, FileCode,
  Smile, Target, Hash, GitPullRequestArrow, Battery, BatteryLow, BatteryMedium,
} from "lucide-react";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api, type UserStateResponse, type EnergyBudget } from "@/lib/api";

type ViewMode = "cards" | "json";

// ── Helpers ────────────────────────────────────────────────────────────────
const ENERGY_LABELS: Record<EnergyBudget, { label: string; color: string }> = {
  high:   { label: "élevé",  color: "text-emerald-300" },
  normal: { label: "normal", color: "text-cyber-cyan" },
  low:    { label: "bas",    color: "text-amber-300" },
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function UserStatePage() {
  const t = useTranslations("userState");
  const [state, setState]       = useState<UserStateResponse | null>(null);
  const [view, setView]         = useState<ViewMode>("cards");
  const [loading, setLoading]   = useState(true);
  const [busy, setBusy]         = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [flash, setFlash]       = useState<string | null>(null);

  const fetchState = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getUserState();
      setState(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur réseau");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchState(); }, [fetchState]);

  const recompute = async () => {
    setBusy(true);
    setError(null);
    setFlash(null);
    try {
      const data = await api.recomputeUserState();
      setState(data);
      if (data.refreshed) {
        setFlash(t("recomputeSuccess"));
      } else if (data.reason === "disabled") {
        setFlash(t("recomputeDisabled"));
      } else if (data.reason === "no_conversations") {
        setFlash(t("recomputeNoConversations"));
      } else {
        setFlash(t("recomputeNoChange"));
      }
      // Auto-clear the flash after 4s
      setTimeout(() => setFlash(null), 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur réseau");
    } finally {
      setBusy(false);
    }
  };

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
            {/* ── Top bar ── */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <Compass className="w-5 h-5 text-cyber-cyan" />
                <h1 className="text-lg font-medium text-text-primary">
                  {t("title")}
                </h1>
                <span className="text-[11px] text-text-muted">
                  {t("subtitle")}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <div className="flex border border-border-dim rounded overflow-hidden">
                  <button
                    onClick={() => setView("cards")}
                    title={t("viewCardsTooltip")}
                    className={`p-1.5 transition-all ${
                      view === "cards"
                        ? "bg-cyber-cyan/10 text-cyber-cyan"
                        : "text-text-muted hover:text-text-secondary"
                    }`}
                  >
                    <LayoutGrid className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setView("json")}
                    title={t("viewJsonTooltip")}
                    className={`p-1.5 transition-all ${
                      view === "json"
                        ? "bg-cyber-cyan/10 text-cyber-cyan"
                        : "text-text-muted hover:text-text-secondary"
                    }`}
                  >
                    <FileCode className="w-3.5 h-3.5" />
                  </button>
                </div>

                <button
                  onClick={recompute}
                  disabled={busy || loading}
                  className="btn primary"
                >
                  {busy ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3.5 h-3.5" />
                  )}
                  <span>{t("recomputeNow")}</span>
                </button>
              </div>
            </div>

            {/* ── Kill-switch banner ── */}
            {state?.disabled && (
              <div className="flex items-center gap-2 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded px-3 py-2">
                <AlertCircle className="w-4 h-4" />
                {t("disabledBanner")}
              </div>
            )}

            {/* ── Error / Flash ── */}
            {error && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                <AlertCircle className="w-4 h-4" />
                {error}
              </div>
            )}
            {flash && !error && (
              <div className="flex items-center gap-2 text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 rounded px-3 py-2">
                {flash}
              </div>
            )}

            {/* ── Body ── */}
            {loading && (
              <div className="flex items-center justify-center py-12 text-text-muted">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                {t("loading")}
              </div>
            )}

            {!loading && state && view === "cards" && <CardsView state={state} />}
            {!loading && state && view === "json" && <JsonView state={state} />}

            {/* ── Footer note ── */}
            <p className="text-[10px] text-text-muted pt-2 border-t border-border-dim">
              {t("lastRefreshed", { date: fmtDate(state?.updated_at ?? null) })}
              {state?.prompt_version && (
                <>
                  {" · "}
                  <span className="font-mono">{t("promptVersion", { hash: state.prompt_version })}</span>
                </>
              )}
              {" · "}
              {t("privacyNote")}
            </p>
          </main>
        </div>
      </div>
    </AuthGuard>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Cards view
// ───────────────────────────────────────────────────────────────────────────

function CardsView({ state }: { state: UserStateResponse }) {
  const t = useTranslations("userState");
  const hasSignal =
    state.current_focus !== "" ||
    state.recent_topics.length > 0 ||
    state.open_loops.length > 0 ||
    state.mood !== "neutral" ||
    state.energy_budget !== "normal";

  return (
    <div className="space-y-4">
      {!hasSignal && (
        <div className="bg-bg-secondary border border-border-dim rounded-lg p-6 text-center">
          <p className="text-sm text-text-muted">{t("emptyState")}</p>
          <p className="text-[11px] text-text-muted/70 mt-1">{t("emptyHint")}</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <FieldCard
          icon={Smile}
          title={t("fieldMood")}
          value={state.mood || "—"}
          accent="text-cyber-cyan"
        />
        <FieldCard
          icon={EnergyIcon(state.energy_budget)}
          title={t("fieldEnergy")}
          value={ENERGY_LABELS[state.energy_budget]?.label ?? state.energy_budget}
          accent={ENERGY_LABELS[state.energy_budget]?.color ?? "text-cyber-cyan"}
        />
      </div>

      <FieldCard
        icon={Target}
        title={t("fieldFocus")}
        value={state.current_focus || t("notSet")}
        accent="text-cyber-cyan"
        wide
      />

      <ListCard
        icon={Hash}
        title={t("fieldTopics")}
        items={state.recent_topics}
        emptyText={t("emptyTopics")}
        chip
      />

      <ListCard
        icon={GitPullRequestArrow}
        title={t("fieldOpenLoops")}
        items={state.open_loops}
        emptyText={t("emptyLoops")}
      />
    </div>
  );
}

function EnergyIcon(level: EnergyBudget) {
  if (level === "high") return Battery;
  if (level === "low") return BatteryLow;
  return BatteryMedium;
}

function FieldCard({
  icon: Icon,
  title,
  value,
  accent = "text-cyber-cyan",
  wide = false,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  value: string;
  accent?: string;
  wide?: boolean;
}) {
  return (
    <section
      className={`bg-bg-secondary border border-border-dim rounded-lg overflow-hidden ${
        wide ? "" : ""
      }`}
    >
      <header className="flex items-center gap-2 px-4 py-2.5 border-b border-border-dim">
        <Icon className={`w-4 h-4 ${accent}`} />
        <h2 className="text-xs font-medium text-text-secondary uppercase tracking-wide">
          {title}
        </h2>
      </header>
      <div className="p-4">
        <p className={`text-sm ${accent} font-medium`}>{value}</p>
      </div>
    </section>
  );
}

function ListCard({
  icon: Icon,
  title,
  items,
  emptyText,
  chip = false,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  items: string[];
  emptyText: string;
  chip?: boolean;
}) {
  return (
    <section className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
      <header className="flex items-center gap-2 px-4 py-2.5 border-b border-border-dim">
        <Icon className="w-4 h-4 text-cyber-cyan" />
        <h2 className="text-xs font-medium text-text-secondary uppercase tracking-wide">
          {title}
        </h2>
        <span className="ml-auto text-[10px] text-text-muted">{items.length}</span>
      </header>
      <div className="p-4">
        {items.length === 0 ? (
          <p className="text-xs text-text-muted italic">{emptyText}</p>
        ) : chip ? (
          <div className="flex flex-wrap gap-1.5">
            {items.map((it, idx) => (
              <span
                key={idx}
                className="px-2 py-0.5 rounded bg-bg-primary text-cyber-cyan/80 text-xs"
              >
                {it}
              </span>
            ))}
          </div>
        ) : (
          <ul className="space-y-1">
            {items.map((it, idx) => (
              <li key={idx} className="text-xs text-text-primary flex items-start gap-2">
                <span className="text-cyber-cyan/60 shrink-0">•</span>
                <span className="flex-1">{it}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// JSON view
// ───────────────────────────────────────────────────────────────────────────

function JsonView({ state }: { state: UserStateResponse }) {
  return (
    <article className="bg-bg-secondary border border-border-dim rounded-lg p-6">
      <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap overflow-x-auto">
        {JSON.stringify(state, null, 2)}
      </pre>
    </article>
  );
}
