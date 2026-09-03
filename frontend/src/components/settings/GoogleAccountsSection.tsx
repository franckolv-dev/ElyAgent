"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/settings/GoogleAccountsSection.tsx
 * @brief      Multi-Google accounts management — list / add / set default / rename / remove
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, Star, Trash2, Pencil, Check, X, Loader2, Wand2 } from "lucide-react";
import { api } from "@/lib/api";
import { GoogleSetupWizard } from "./GoogleSetupWizard";

interface GoogleAccount {
  id: string;
  alias: string;
  email: string;
  is_default: boolean;
  created_at: string | null;
}

export function GoogleAccountsSection() {
  // i18n keys live under settings.googleAccounts (added in messages/{fr,en}.json)
  const t = useTranslations("settings.googleAccounts");

  const [accounts, setAccounts] = useState<GoogleAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Add-account modal
  const [showAdd, setShowAdd] = useState(false);
  const [newAlias, setNewAlias] = useState("");
  const [adding, setAdding] = useState(false);

  // Inline rename
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // Setup wizard
  const [wizardOpen, setWizardOpen] = useState(false);
  const wizardT = useTranslations("settings.googleWizard");

  // Delete confirmation
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.listGoogleAccounts();
      setAccounts(data.accounts ?? []);
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
    const alias = newAlias.trim();
    if (!alias) return;
    setAdding(true);
    try {
      const { url } = await api.getGoogleAuthUrl(alias);
      // Full-page redirect to Google consent screen
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : t("addFailed"));
      setAdding(false);
    }
  };

  const handleSetDefault = async (id: string) => {
    try {
      await api.setGoogleDefault(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("defaultFailed"));
    }
  };

  const startRename = (acc: GoogleAccount) => {
    setRenamingId(acc.id);
    setRenameValue(acc.alias);
  };

  const commitRename = async () => {
    if (!renamingId) return;
    const v = renameValue.trim();
    if (!v) {
      setRenamingId(null);
      return;
    }
    try {
      await api.renameGoogleAccount(renamingId, v);
      setRenamingId(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("renameFailed"));
    }
  };

  const confirmDelete = async () => {
    if (!deletingId) return;
    try {
      await api.deleteGoogleAccount(deletingId);
      setDeletingId(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("deleteFailed"));
      setDeletingId(null);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">{t("title")}</h3>
          <p className="text-xs text-text-muted">{t("subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setWizardOpen(true)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded border border-border-strong text-text-secondary hover:text-cyber-cyan hover:border-cyber-cyan transition-colors"
            title={wizardT("wizardBtn")}
          >
            <Wand2 className="w-3.5 h-3.5" />
            <span>{wizardT("wizardBtn")}</span>
          </button>
          <button
            type="button"
            onClick={() => { setShowAdd(true); setNewAlias(""); }}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>{t("addAccount")}</span>
          </button>
        </div>
      </div>

      <GoogleSetupWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onComplete={() => refresh()}
      />

      {error && (
        <div className="text-xs text-cyber-red border border-cyber-red/30 bg-cyber-red/5 rounded px-3 py-2">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-text-muted py-3">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span>{t("loading")}</span>
        </div>
      ) : accounts.length === 0 ? (
        <div className="text-xs text-text-muted border border-dashed border-border-dim rounded px-3 py-4 text-center">
          {t("emptyState")}
        </div>
      ) : (
        <ul className="divide-y divide-border-dim border border-border-dim rounded overflow-hidden">
          {accounts.map((acc) => (
            <li key={acc.id} className="flex items-center gap-3 px-3 py-2.5 hover:bg-bg-tertiary/40">
              {/* Alias (editable) */}
              <div className="flex-1 min-w-0">
                {renamingId === acc.id ? (
                  <div className="flex items-center gap-1">
                    <input
                      type="text"
                      autoFocus
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitRename();
                        if (e.key === "Escape") setRenamingId(null);
                      }}
                      className="text-sm bg-bg-tertiary border border-cyber-cyan/40 rounded px-2 py-0.5 w-32 text-text-primary"
                      maxLength={50}
                    />
                    <button onClick={commitRename} title={t("renameSave")} className="p-1 text-cyber-cyan hover:bg-cyber-cyan/10 rounded">
                      <Check className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => setRenamingId(null)} title={t("cancel")} className="p-1 text-text-muted hover:bg-bg-tertiary rounded">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-text-primary truncate">
                      {acc.alias}
                    </span>
                    {acc.is_default && (
                      <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/20">
                        {t("defaultBadge")}
                      </span>
                    )}
                  </div>
                )}
                <div className="text-xs text-text-muted truncate">{acc.email}</div>
              </div>

              {/* Actions */}
              {renamingId !== acc.id && (
                <div className="flex items-center gap-1">
                  {!acc.is_default && (
                    <button
                      type="button"
                      onClick={() => handleSetDefault(acc.id)}
                      title={t("setDefault")}
                      className="p-1.5 text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/10 rounded transition-colors"
                    >
                      <Star className="w-3.5 h-3.5" />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => startRename(acc)}
                    title={t("rename")}
                    className="p-1.5 text-text-muted hover:text-text-primary hover:bg-bg-tertiary rounded transition-colors"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeletingId(acc.id)}
                    title={t("remove")}
                    className="p-1.5 text-text-muted hover:text-cyber-red hover:bg-cyber-red/10 rounded transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="text-[10px] text-text-muted leading-relaxed">
        {t("hintMultiAccount")}
      </p>

      {/* ── Add-account modal ─────────────────────────────────────────── */}
      {showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => !adding && setShowAdd(false)}>
          <div
            className="bg-bg-secondary border border-cyber-cyan/30 rounded-lg p-5 w-full max-w-md mx-4 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h4 className="text-sm font-semibold text-text-primary">{t("addModalTitle")}</h4>
            <p className="text-xs text-text-muted">{t("addModalHelp")}</p>
            <div>
              <label className="text-xs text-text-secondary">{t("aliasLabel")}</label>
              <input
                type="text"
                autoFocus
                value={newAlias}
                onChange={(e) => setNewAlias(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleAdd();
                  if (e.key === "Escape") setShowAdd(false);
                }}
                placeholder={t("aliasPlaceholder")}
                maxLength={50}
                className="mt-1 w-full text-sm bg-bg-tertiary border border-border-dim rounded px-2 py-1.5 text-text-primary focus:border-cyber-cyan/40 outline-none"
              />
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setShowAdd(false)}
                disabled={adding}
                className="text-xs px-3 py-1.5 rounded border border-border-dim text-text-secondary hover:text-text-primary"
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                onClick={handleAdd}
                disabled={adding || !newAlias.trim()}
                className="text-xs px-3 py-1.5 rounded bg-cyber-cyan/10 border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/20 disabled:opacity-50 flex items-center gap-1.5"
              >
                {adding && <Loader2 className="w-3 h-3 animate-spin" />}
                <span>{t("continueToGoogle")}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete confirmation modal ─────────────────────────────────── */}
      {deletingId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setDeletingId(null)}>
          <div
            className="bg-bg-secondary border border-cyber-red/30 rounded-lg p-5 w-full max-w-md mx-4 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h4 className="text-sm font-semibold text-cyber-red">{t("deleteModalTitle")}</h4>
            <p className="text-xs text-text-secondary">
              {t("deleteModalBody", {
                alias: accounts.find((a) => a.id === deletingId)?.alias ?? "?",
              })}
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeletingId(null)}
                className="text-xs px-3 py-1.5 rounded border border-border-dim text-text-secondary hover:text-text-primary"
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                className="text-xs px-3 py-1.5 rounded bg-cyber-red/10 border border-cyber-red/30 text-cyber-red hover:bg-cyber-red/20"
              >
                {t("deleteConfirm")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
