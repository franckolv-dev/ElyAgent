"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/knowledge/WatchedFoldersSection.tsx
 * @brief      Watched folders — auto-indexed local folders → RAG
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Folder, FolderPlus, Trash2, RefreshCw, Loader2, Check, X,
  Power, PowerOff, AlertCircle,
} from "lucide-react";
import { api } from "@/lib/api";

interface WatchedFolder {
  id: string;
  path: string;
  recursive: boolean;
  enabled: boolean;
  include_extensions: string;
  exclude_paths: string;
  last_scan_at: string | null;
  last_scan_status: string;
  last_scan_message: string;
  files_indexed: number;
  created_at: string;
}

const STATUS_COLOR: Record<string, string> = {
  ok: "text-emerald-400 border-emerald-500/30 bg-emerald-500/5",
  partial: "text-amber-400 border-amber-500/30 bg-amber-500/5",
  error: "text-cyber-red border-cyber-red/30 bg-cyber-red/5",
  // `offline` n'est pas une erreur : le démon ELY Desktop n'est pas connecté,
  // donc rien n'a pu être tenté. Ambre plutôt que rouge — c'est une condition
  // à remplir, pas une panne à chercher.
  offline: "text-amber-400 border-amber-500/30 bg-amber-500/5",
  running: "text-cyber-cyan border-cyber-cyan/30 bg-cyber-cyan/5",
  pending: "text-text-muted border-border-dim bg-bg-tertiary/30",
};

function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return "à l'instant";
  if (ms < 3_600_000) return `il y a ${Math.floor(ms / 60_000)} min`;
  if (ms < 86_400_000) return `il y a ${Math.floor(ms / 3_600_000)} h`;
  return new Date(iso).toLocaleDateString();
}

export function WatchedFoldersSection() {
  const t = useTranslations("knowledge.watchedFolders");

  const [folders, setFolders] = useState<WatchedFolder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Add modal
  const [showAdd, setShowAdd] = useState(false);
  const [newPath, setNewPath] = useState("");
  const [newRecursive, setNewRecursive] = useState(true);
  const [adding, setAdding] = useState(false);

  // Per-folder scanning state (folder.id → boolean)
  const [scanning, setScanning] = useState<Record<string, boolean>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.listWatchedFolders();
      setFolders(data.folders ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // ── Handlers ──────────────────────────────────────────────────────────
  const handleAdd = async () => {
    const p = newPath.trim();
    if (!p) return;
    setAdding(true);
    setError("");
    try {
      await api.createWatchedFolder({ path: p, recursive: newRecursive });
      setShowAdd(false);
      setNewPath("");
      setNewRecursive(true);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("addFailed"));
    } finally {
      setAdding(false);
    }
  };

  const handleScan = async (id: string) => {
    setScanning((s) => ({ ...s, [id]: true }));
    setError("");
    try {
      await api.scanWatchedFolderNow(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("scanFailed"));
    } finally {
      setScanning((s) => ({ ...s, [id]: false }));
    }
  };

  const handleToggle = async (f: WatchedFolder) => {
    try {
      await api.updateWatchedFolder(f.id, { enabled: !f.enabled });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("toggleFailed"));
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t("confirmDelete"))) return;
    try {
      await api.deleteWatchedFolder(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("deleteFailed"));
    }
  };

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
            <Folder className="w-4 h-4 text-cyber-cyan" /> {t("title")}
          </h3>
          <p className="text-xs text-text-muted mt-0.5">{t("subtitle")}</p>
        </div>
        <button
          type="button"
          onClick={() => { setShowAdd(true); setNewPath(""); setError(""); }}
          className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 transition-colors"
        >
          <FolderPlus className="w-3.5 h-3.5" />
          <span>{t("addFolder")}</span>
        </button>
      </div>

      {error && (
        <div className="text-xs text-cyber-red border border-cyber-red/30 bg-cyber-red/5 rounded px-3 py-2 flex items-start gap-2">
          <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-text-muted py-3">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span>{t("loading")}</span>
        </div>
      ) : folders.length === 0 ? (
        <div className="text-xs text-text-muted border border-dashed border-border-dim rounded px-3 py-4 text-center">
          {t("emptyState")}
        </div>
      ) : (
        <ul className="divide-y divide-border-dim border border-border-dim rounded overflow-hidden">
          {folders.map((f) => {
            const statusClass = STATUS_COLOR[f.last_scan_status] ?? STATUS_COLOR.pending;
            const isScanning = scanning[f.id] || f.last_scan_status === "running";
            return (
              <li key={f.id} className="px-3 py-2.5 hover:bg-bg-tertiary/30">
                <div className="flex items-center gap-3">
                  <Folder className={`w-4 h-4 shrink-0 ${f.enabled ? "text-cyber-cyan" : "text-text-muted"}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-mono truncate ${f.enabled ? "text-text-primary" : "text-text-muted"}`}>
                        {f.path}
                      </span>
                      {f.recursive && (
                        <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-bg-tertiary border border-border-dim text-text-muted">
                          {t("recursiveBadge")}
                        </span>
                      )}
                      {!f.enabled && (
                        <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-text-muted/10 border border-border-dim text-text-muted">
                          {t("disabledBadge")}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-1 text-[11px] text-text-muted">
                      <span className={`px-1.5 py-0.5 rounded border ${statusClass}`}>
                        {f.last_scan_status}
                      </span>
                      <span>{formatRelative(f.last_scan_at)}</span>
                      <span>·</span>
                      <span>{t("filesIndexed", { count: f.files_indexed })}</span>
                    </div>
                    {f.last_scan_message && (
                      <div className="text-[11px] text-text-muted mt-0.5 italic truncate">
                        {f.last_scan_message}
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      onClick={() => handleScan(f.id)}
                      disabled={isScanning}
                      title={t("scanNow")}
                      className="p-1.5 text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/10 rounded transition-colors disabled:opacity-50"
                    >
                      {isScanning
                        ? <Loader2 className="w-3.5 h-3.5 animate-spin text-cyber-cyan" />
                        : <RefreshCw className="w-3.5 h-3.5" />}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleToggle(f)}
                      title={f.enabled ? t("disable") : t("enable")}
                      className="p-1.5 text-text-muted hover:text-text-primary hover:bg-bg-tertiary rounded transition-colors"
                    >
                      {f.enabled
                        ? <Power className="w-3.5 h-3.5" />
                        : <PowerOff className="w-3.5 h-3.5 text-text-muted" />}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(f.id)}
                      title={t("remove")}
                      className="p-1.5 text-text-muted hover:text-cyber-red hover:bg-cyber-red/10 rounded transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <p className="text-[10px] text-text-muted leading-relaxed">
        {t("hintCron")}
      </p>

      {/* ── Add modal ─────────────────────────────────────────────────── */}
      {showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => !adding && setShowAdd(false)}>
          <div
            className="bg-bg-secondary border border-cyber-cyan/30 rounded-lg p-5 w-full max-w-md mx-4 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h4 className="text-sm font-semibold text-text-primary">{t("addModalTitle")}</h4>
            <p className="text-xs text-text-muted">{t("addModalHelp")}</p>

            <div>
              <label className="text-xs text-text-secondary">{t("pathLabel")}</label>
              <input
                type="text"
                autoFocus
                value={newPath}
                onChange={(e) => setNewPath(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleAdd();
                  if (e.key === "Escape") setShowAdd(false);
                }}
                placeholder={t("pathPlaceholder")}
                className="mt-1 w-full text-sm bg-bg-tertiary border border-border-dim rounded px-2 py-1.5 text-text-primary focus:border-cyber-cyan/40 outline-none font-mono"
              />
            </div>

            <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
              <input
                type="checkbox"
                checked={newRecursive}
                onChange={(e) => setNewRecursive(e.target.checked)}
                className="accent-cyber-cyan"
              />
              <span>{t("recursiveOption")}</span>
            </label>

            <p className="text-[10px] text-text-muted">{t("addModalDaemonHint")}</p>

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setShowAdd(false)}
                disabled={adding}
                className="text-xs px-3 py-1.5 rounded border border-border-dim text-text-secondary hover:text-text-primary"
              >
                <X className="w-3 h-3 inline mr-1" />
                {t("cancel")}
              </button>
              <button
                type="button"
                onClick={handleAdd}
                disabled={adding || !newPath.trim()}
                className="text-xs px-3 py-1.5 rounded bg-cyber-cyan/10 border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/20 disabled:opacity-50 flex items-center gap-1.5"
              >
                {adding ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                <span>{t("addConfirm")}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
