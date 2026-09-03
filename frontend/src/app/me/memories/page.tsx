"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/me/memories/page.tsx
 * @brief      Sprint 2.5 §2.5.6 — page « Mes mémoires » : parcourir ce
 *             qu'ELY retient, famille par famille, et l'oublier.
 *             Sibling de /me/state, même surface « transparence radicale ».
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 * @version    1.3.0
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  BrainCircuit, Loader2, AlertCircle, Trash2, Info, ChevronDown,
} from "lucide-react";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import {
  api,
  type MemoryEntry,
  type MemoryFamiliesResponse,
} from "@/lib/api";

// Libellés des familles. La clé est celle du serveur — la garder telle
// quelle évite d'avoir à synchroniser deux vocabulaires.
const FAMILY_LABELS: Record<string, string> = {
  fact: "Faits",
  preference: "Préférences",
  constraint: "Règles",
  episodic: "Conversations",
};

function familyLabel(key: string): string {
  return FAMILY_LABELS[key] ?? key;
}

function fmtDate(raw: string | null): string {
  if (!raw) return "—";
  // Le serveur stocke selon le magasin : ISO 8601 (facts) ou timestamp Unix
  // en secondes (préférences, contraintes). Les deux transitent en chaîne.
  const asNumber = Number(raw);
  const d = Number.isFinite(asNumber) && raw.trim() !== ""
    ? new Date(asNumber * 1000)
    : new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString("fr-FR", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function MyMemoriesPage() {
  const t = useTranslations("memories");

  const [families, setFamilies] = useState<MemoryFamiliesResponse | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [nextOffset, setNextOffset] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [forgetting, setForgetting] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ── Chargement des familles, puis de la première ────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.memoryFamilies();
        if (cancelled) return;
        setFamilies(data);
        const first = data.inspectable[0] ?? null;
        setActive(first);
        // Sans famille à ouvrir, `loadFamily` ne tournera jamais : il faut
        // couper le chargement ici, sinon le spinner tourne pour toujours.
        if (!first) setLoading(false);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Erreur réseau");
          setLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const loadFamily = useCallback(async (family: string) => {
    setLoading(true);
    setError(null);
    setConfirming(null);
    try {
      const page = await api.memoryBrowse(family);
      setEntries(page.entries);
      setNextOffset(page.next_offset);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur réseau");
      setEntries([]);
      setNextOffset(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (active) loadFamily(active);
  }, [active, loadFamily]);

  const loadMore = async () => {
    if (!active || !nextOffset) return;
    setLoadingMore(true);
    try {
      const page = await api.memoryBrowse(active, nextOffset);
      setEntries((prev) => [...prev, ...page.entries]);
      setNextOffset(page.next_offset);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur réseau");
    } finally {
      setLoadingMore(false);
    }
  };

  const forget = async (entryId: string) => {
    if (!active) return;
    setForgetting(entryId);
    setError(null);
    try {
      await api.memoryForget(active, entryId);
      // Retrait local : recharger la page entière ferait sauter le curseur
      // de pagination déjà consommé.
      setEntries((prev) => prev.filter((e) => e.id !== entryId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur réseau");
    } finally {
      setForgetting(null);
      setConfirming(null);
    }
  };

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden">
          <main
            className="flex-1 overflow-y-auto p-6 space-y-4"
            style={{ background: "var(--bg-app)" }}
          >
            {/* ── Barre de titre ── */}
            <div className="flex items-center gap-3">
              <BrainCircuit className="w-5 h-5 text-cyber-cyan" />
              <h1 className="text-lg font-medium text-text-primary">
                {t("title")}
              </h1>
              <span className="text-[11px] text-text-muted">
                {t("subtitle")}
              </span>
            </div>

            {/* ── Onglets de famille ── */}
            {families && (
              <div className="flex flex-wrap gap-1.5">
                {families.inspectable.map((f) => (
                  <button
                    key={f}
                    onClick={() => setActive(f)}
                    className={`px-3 py-1.5 text-xs rounded border transition-all ${
                      active === f
                        ? "bg-cyber-cyan/10 text-cyber-cyan border-cyber-cyan/40"
                        : "text-text-muted border-border-dim hover:text-text-secondary"
                    }`}
                  >
                    {familyLabel(f)}
                  </button>
                ))}
              </div>
            )}

            {/* ── Familles sans surface d'audit, AVEC la raison ──
                 Les masquer laisserait croire à une mémoire à quatre
                 familles ; les montrer sans raison ferait croire à une
                 panne. C'est l'invariant « un repli doit se voir ». */}
            {families?.uninspectable.map((u) => (
              <div
                key={u.family}
                className="flex items-start gap-2 text-[11px] text-text-muted bg-white/[0.02] border border-border-dim rounded px-3 py-2"
              >
                <Info className="w-3.5 h-3.5 mt-px shrink-0" />
                <span>
                  <span className="text-text-secondary">{u.family}</span>
                  {" — "}{u.reason}
                </span>
              </div>
            ))}

            {/* ── Erreur ── */}
            {error && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                <AlertCircle className="w-4 h-4" />
                {error}
              </div>
            )}

            {/* ── Liste ── */}
            {loading ? (
              <div className="flex items-center gap-2 text-xs text-text-muted">
                <Loader2 className="w-4 h-4 animate-spin" />
                {t("loading")}
              </div>
            ) : entries.length === 0 ? (
              <p className="text-xs text-text-muted">{t("empty")}</p>
            ) : (
              <ul className="space-y-1.5">
                {entries.map((e) => (
                  <li
                    key={e.id}
                    className="group flex items-start justify-between gap-3 bg-white/[0.02] border border-border-dim rounded px-3 py-2"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-xs text-text-primary whitespace-pre-wrap break-words">
                        {e.content || <em className="text-text-muted">{t("noContent")}</em>}
                      </p>
                      <p className="text-[10px] text-text-muted mt-1">
                        {fmtDate(e.created_at)}
                      </p>
                    </div>

                    {confirming === e.id ? (
                      <div className="flex items-center gap-1.5 shrink-0">
                        <button
                          onClick={() => forget(e.id)}
                          disabled={forgetting === e.id}
                          className="text-[11px] px-2 py-1 rounded bg-red-500/15 text-red-300 border border-red-500/30 hover:bg-red-500/25"
                        >
                          {forgetting === e.id ? (
                            <Loader2 className="w-3 h-3 animate-spin" />
                          ) : (
                            t("confirmForget")
                          )}
                        </button>
                        <button
                          onClick={() => setConfirming(null)}
                          className="text-[11px] px-2 py-1 rounded text-text-muted hover:text-text-secondary"
                        >
                          {t("cancel")}
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirming(e.id)}
                        title={t("forget")}
                        className="shrink-0 p-1.5 rounded text-text-muted opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-red-400 transition-all"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {/* ── Pagination ── */}
            {!loading && nextOffset && (
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="flex items-center gap-1.5 text-xs text-text-muted hover:text-cyber-cyan"
              >
                {loadingMore ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <ChevronDown className="w-3.5 h-3.5" />
                )}
                {t("loadMore")}
              </button>
            )}
          </main>
        </div>
        </div>
      </div>
    </AuthGuard>
  );
}
