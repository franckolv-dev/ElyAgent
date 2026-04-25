"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/missions/page.tsx
 * @brief      Missions list — goal-driven persistence loop dashboard
 *
 * @author     Franck OLLIVIER <franck.olv@gmail.com>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { Target, Plus, Loader2, AlertCircle, X } from "lucide-react";
import {
  missionsApi, type Mission, type MissionStatus, STATUS_META,
} from "@/lib/missions";

type FilterTab = "all" | "active" | "terminal";

export default function MissionsPage() {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [filter, setFilter]     = useState<FilterTab>("all");
  const [showCreate, setShowCreate] = useState(false);

  const fetchAll = useCallback(async () => {
    setError(null);
    try {
      const data = await missionsApi.list();
      setMissions(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Auto-refresh every 5 s if any mission is active (running/planning)
  useEffect(() => {
    const hasActive = missions.some((m) => m.status === "running" || m.status === "planning");
    if (!hasActive) return;
    const t = setInterval(fetchAll, 5_000);
    return () => clearInterval(t);
  }, [missions, fetchAll]);

  const filtered = missions.filter((m) => {
    if (filter === "active") return ["draft", "planning", "running", "paused"].includes(m.status);
    if (filter === "terminal") return ["completed", "failed", "aborted"].includes(m.status);
    return true;
  });

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Header />

          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {/* Header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Target className="w-5 h-5 text-cyber-cyan" />
                <h1 className="text-lg font-medium text-text-primary">Missions</h1>
                <span className="text-[11px] text-text-muted">
                  Goals long-terme poursuivis par Éli — boucle Plan → Act → Eval → Replan
                </span>
              </div>
              <button
                onClick={() => setShowCreate(true)}
                className="inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all"
              >
                <Plus className="w-3.5 h-3.5" />
                Nouvelle mission
              </button>
            </div>

            {/* Tabs */}
            <div className="flex gap-1 border-b border-border-dim">
              {(["all", "active", "terminal"] as FilterTab[]).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setFilter(tab)}
                  className={`text-xs px-3 py-2 -mb-px border-b-2 transition-all ${
                    filter === tab
                      ? "border-cyber-cyan text-cyber-cyan"
                      : "border-transparent text-text-muted hover:text-text-secondary"
                  }`}
                >
                  {tab === "all" ? "Toutes" : tab === "active" ? "Actives" : "Terminées"}
                  <span className="ml-1.5 text-[10px] text-text-muted">
                    ({tab === "all" ? missions.length :
                       tab === "active" ? missions.filter(m => ["draft","planning","running","paused"].includes(m.status)).length :
                       missions.filter(m => ["completed","failed","aborted"].includes(m.status)).length})
                  </span>
                </button>
              ))}
            </div>

            {/* List */}
            {error && (
              <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                <AlertCircle className="w-4 h-4" />
                {error}
              </div>
            )}

            {loading ? (
              <div className="flex items-center justify-center py-12 text-text-muted">
                <Loader2 className="w-5 h-5 animate-spin mr-2" /> Chargement…
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-center py-12 text-text-muted text-sm">
                {filter === "all"
                  ? "Pas encore de missions. Crée-en une via le bouton ci-dessus."
                  : `Aucune mission ${filter === "active" ? "active" : "terminée"} pour l'instant.`}
              </div>
            ) : (
              <div className="space-y-2">
                {filtered.map((m) => (
                  <MissionCard key={m.id} mission={m} />
                ))}
              </div>
            )}
          </div>

          {showCreate && (
            <CreateMissionModal
              onClose={() => setShowCreate(false)}
              onCreated={() => { setShowCreate(false); fetchAll(); }}
            />
          )}
        </div>
      </div>
    </AuthGuard>
  );
}

// ── Mission card ────────────────────────────────────────────────────────────

function MissionCard({ mission }: { mission: Mission }) {
  const meta = STATUS_META[mission.status];
  const progress = mission.budget_iterations
    ? Math.round((mission.iterations_used / mission.budget_iterations) * 100)
    : 0;

  return (
    <Link
      href={`/missions/${mission.id}`}
      className="block bg-bg-secondary border border-border-dim hover:border-cyber-cyan/40 rounded-lg p-4 transition-all"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-sm font-medium text-text-primary truncate">{mission.title}</h3>
            <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border ${meta.color} shrink-0`}>
              {meta.emoji} {meta.label}
            </span>
          </div>
          <p className="text-[11px] text-text-muted line-clamp-2">{mission.goal}</p>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-4 text-[10px] text-text-muted">
        <span title="Itérations utilisées / budget">
          ⚙️ {mission.iterations_used}/{mission.budget_iterations}
        </span>
        <span title="Tokens consommés / budget">
          🔢 {mission.tokens_used.toLocaleString()}/{mission.budget_tokens.toLocaleString()}
        </span>
        <span>📅 {new Date(mission.created_at).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
        {mission.tick_interval_seconds && (
          <span title="Intervalle heartbeat">⏱️ tick chaque {mission.tick_interval_seconds}s</span>
        )}
      </div>

      {/* Progress bar */}
      <div className="mt-2 h-1 bg-bg-primary rounded overflow-hidden">
        <div
          className={`h-full transition-all ${mission.status === "completed" ? "bg-emerald-400" : mission.status === "failed" || mission.status === "aborted" ? "bg-red-400/50" : "bg-cyber-cyan"}`}
          style={{ width: `${Math.min(100, progress)}%` }}
        />
      </div>

      {/* Final state preview */}
      {mission.final_summary && (
        <p className="mt-2 text-[11px] text-emerald-300/80 line-clamp-1">✓ {mission.final_summary}</p>
      )}
      {mission.failure_reason && (
        <p className="mt-2 text-[11px] text-red-300/80 line-clamp-1">⚠ {mission.failure_reason}</p>
      )}
    </Link>
  );
}

// ── Create modal ────────────────────────────────────────────────────────────

function CreateMissionModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [title, setTitle]   = useState("");
  const [goal, setGoal]     = useState("");
  const [budgetIter, setBudgetIter] = useState(15);
  const [budgetTok, setBudgetTok]   = useState(50_000);
  const [busy, setBusy]     = useState(false);
  const [err, setErr]       = useState<string | null>(null);

  const submit = async () => {
    if (!title.trim() || goal.trim().length < 5) {
      setErr("Titre requis et goal d'au moins 5 caractères");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await missionsApi.create({
        title: title.trim(),
        goal: goal.trim(),
        budget_iterations: budgetIter,
        budget_tokens: budgetTok,
      });
      onCreated();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Erreur création");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-bg-primary border border-border-dim rounded-lg w-full max-w-xl shadow-xl">
        <div className="flex items-center justify-between p-4 border-b border-border-dim">
          <h2 className="text-sm font-medium text-text-primary">Nouvelle mission</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary"><X className="w-4 h-4" /></button>
        </div>

        <div className="p-4 space-y-3">
          <div>
            <label className="text-[11px] text-text-muted block mb-1">Titre court</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Ex. Préparer le résumé hebdo IA"
              className="w-full text-sm bg-bg-secondary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
            />
          </div>

          <div>
            <label className="text-[11px] text-text-muted block mb-1">Goal — décris ce qu'Éli doit accomplir</label>
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="Ex. Trouve les 3 articles les plus récents sur Gemma 4, fais un résumé en 200 mots dans un Google Doc nouveau, et envoie-moi un mail avec le lien."
              rows={5}
              className="w-full text-sm bg-bg-secondary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40 resize-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-text-muted block mb-1">
                Budget itérations <span className="text-text-muted/60">(max ticks)</span>
              </label>
              <input
                type="number" min={1} max={200} value={budgetIter}
                onChange={(e) => setBudgetIter(Math.max(1, Math.min(200, +e.target.value || 1)))}
                className="w-full text-sm bg-bg-secondary border border-border-dim rounded px-3 py-2 text-text-primary focus:outline-none focus:border-cyber-cyan/40"
              />
            </div>
            <div>
              <label className="text-[11px] text-text-muted block mb-1">
                Budget tokens <span className="text-text-muted/60">(LLM)</span>
              </label>
              <input
                type="number" min={1000} max={500_000} step={1000} value={budgetTok}
                onChange={(e) => setBudgetTok(Math.max(1000, Math.min(500_000, +e.target.value || 1000)))}
                className="w-full text-sm bg-bg-secondary border border-border-dim rounded px-3 py-2 text-text-primary focus:outline-none focus:border-cyber-cyan/40"
              />
            </div>
          </div>

          {err && (
            <div className="flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-2 py-1.5">
              <AlertCircle className="w-3.5 h-3.5" />
              {err}
            </div>
          )}

          <p className="text-[10px] text-text-muted">
            La mission sera créée en mode <strong>brouillon</strong>. Sur la page de détail tu pourras la lancer (ou laisser le heartbeat la déclencher quand il sera implémenté).
          </p>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-border-dim">
          <button
            onClick={onClose}
            disabled={busy}
            className="text-xs px-3 py-1.5 rounded border border-border-dim text-text-muted hover:text-text-secondary"
          >
            Annuler
          </button>
          <button
            onClick={submit}
            disabled={busy || !title.trim() || goal.trim().length < 5}
            className="text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 disabled:opacity-50"
          >
            {busy ? "Création…" : "Créer la mission"}
          </button>
        </div>
      </div>
    </div>
  );
}
