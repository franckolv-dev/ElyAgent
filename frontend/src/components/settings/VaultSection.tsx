// =============================================================================
// @project    ELY — Exactly Like You
// @file       frontend/src/components/settings/VaultSection.tsx
// @brief      Le coffre : déverrouiller, ranger un secret, lire ses étiquettes.
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
// @license    MIT
//            https://opensource.org/licenses/MIT
// @link       https://github.com/franckolv-dev/PhysicalAgent
// =============================================================================
"use client";

// 07/09/2026 — le coffre existait côté API (AES-GCM, Argon2id, référence
// `vault://étiquette` résolue par la passerelle) mais n'avait AUCUNE
// interface : il était vide en prod. Une mission qui crée un compte pour
// l'utilisateur y range le mot de passe ; il faut pouvoir l'ouvrir, y
// déposer ses propres identifiants, et lire ce qu'Ely y a rangé. Une valeur
// n'est jamais réaffichée : on montre l'étiquette, le mémo, la référence.

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { KeyRound, Loader2, Lock, LockOpen, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";

interface VaultSecret {
  label: string;
  hint: string | null;
  created_at: string | null;
}

export function VaultSection() {
  const t = useTranslations("settings.vaultSection");
  const [locked, setLocked] = useState<boolean | null>(null);
  const [secrets, setSecrets] = useState<VaultSecret[]>([]);
  const [master, setMaster] = useState("");
  const [label, setLabel] = useState("");
  const [value, setValue] = useState("");
  const [hint, setHint] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [status, list] = await Promise.all([api.vaultStatus(), api.vaultSecrets()]);
      setLocked(status.locked);
      setSecrets(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("loadFailed"));
    }
  }, [t]);

  useEffect(() => { refresh(); }, [refresh]);

  const unlock = async () => {
    if (master.length < 8) return;
    setBusy("unlock");
    setError("");
    try {
      await api.vaultUnlock(master);
      setMaster("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("wrongPassword"));
    } finally {
      setBusy(null);
    }
  };

  const lock = async () => {
    setBusy("lock");
    try { await api.vaultLock(); await refresh(); } finally { setBusy(null); }
  };

  const add = async () => {
    if (!label.trim() || !value) return;
    setBusy("add");
    setError("");
    try {
      await api.vaultStore(label.trim(), value, hint.trim());
      setLabel(""); setValue(""); setHint("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("loadFailed"));
    } finally {
      setBusy(null);
    }
  };

  const remove = async (l: string) => {
    if (!window.confirm(t("deleteConfirm", { label: l }))) return;
    setBusy(`del:${l}`);
    try { await api.vaultDelete(l); await refresh(); } finally { setBusy(null); }
  };

  return (
    <section>
      <div className="flex items-center gap-2 mb-4">
        <KeyRound className="w-4 h-4 text-cyber-cyan" />
        <h2 className="text-sm font-medium text-text-primary">{t("title")}</h2>
        {locked !== null && (
          <span className={`ml-auto inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full ${locked ? "bg-emerald-400/10 text-emerald-400" : "bg-amber-400/10 text-amber-400"}`}>
            {locked ? <Lock className="w-3 h-3" /> : <LockOpen className="w-3 h-3" />}
            {locked ? t("locked") : t("unlocked")}
          </span>
        )}
      </div>
      <div className="section-block space-y-4">
        <p className="text-xs text-text-muted">{t("intro")}</p>

        {locked !== false ? (
          <div className="flex flex-col gap-2 max-w-md">
            <label className="text-xs text-text-secondary">{t("masterPassword")}</label>
            <div className="flex gap-2">
              <input
                type="password"
                value={master}
                onChange={(e) => setMaster(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") unlock(); }}
                placeholder="••••••••"
                className="flex-1 text-xs bg-bg-secondary border border-border-dim rounded px-2.5 py-1.5 text-text-primary focus:outline-none focus:border-cyber-cyan/60"
              />
              <button onClick={unlock} disabled={busy !== null || master.length < 8} className="btn primary text-xs">
                {busy === "unlock" ? <Loader2 className="w-3 h-3 animate-spin" /> : <LockOpen className="w-3 h-3" />}
                {t("unlock")}
              </button>
            </div>
            <p className="text-[11px] text-text-muted">{t("masterPasswordHint")}</p>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button onClick={lock} disabled={busy !== null} className="btn text-xs">
              <Lock className="w-3 h-3" /> {t("lock")}
            </button>
            <span className="text-[11px] text-text-muted">{t("autoLock")}</span>
          </div>
        )}

        {error && <p className="text-xs text-red-400">{error}</p>}

        <div>
          <h3 className="text-xs font-medium text-text-primary mb-2">{t("secrets")}</h3>
          {secrets.length === 0 ? (
            <p className="text-xs text-text-muted">{t("empty")}</p>
          ) : (
            <ul className="divide-y divide-border-dim">
              {secrets.map((s) => (
                <li key={s.label} className="py-2 flex items-start gap-3 text-xs">
                  <div className="flex-1 min-w-0">
                    <div className="text-text-primary font-medium">{s.label}</div>
                    {s.hint && <div className="text-text-muted">{s.hint}</div>}
                    <code className="text-[11px] text-cyber-cyan">vault://{s.label}</code>
                  </div>
                  <button
                    onClick={() => remove(s.label)}
                    disabled={busy !== null || locked !== false}
                    title={t("delete")}
                    className="text-text-muted hover:text-red-400 disabled:opacity-40"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="text-[11px] text-text-muted mt-2">{t("reference")}</p>
        </div>

        {locked === false && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 max-w-2xl">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t("label")}
              className="text-xs bg-bg-secondary border border-border-dim rounded px-2.5 py-1.5 text-text-primary focus:outline-none focus:border-cyber-cyan/60"
            />
            <input
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={t("value")}
              className="text-xs bg-bg-secondary border border-border-dim rounded px-2.5 py-1.5 text-text-primary focus:outline-none focus:border-cyber-cyan/60"
            />
            <div className="flex gap-2">
              <input
                value={hint}
                onChange={(e) => setHint(e.target.value)}
                placeholder={t("hint")}
                className="flex-1 text-xs bg-bg-secondary border border-border-dim rounded px-2.5 py-1.5 text-text-primary focus:outline-none focus:border-cyber-cyan/60"
              />
              <button onClick={add} disabled={busy !== null || !label.trim() || !value} className="btn primary text-xs">
                {busy === "add" ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                {t("add")}
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
