"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/settings/SovereigntySection.tsx
 * @brief      PII-sovereignty toggle. When on, all tier-B/C cloud calls are
 *             routed to the EU Mistral chain (Large → Medium → Small) instead
 *             of the default cloud provider (typically DeepSeek). Off by
 *             default (opt-in). Local + maintenance tiers are unaffected
 *             (already local).
 *
 *             If no Mistral instance is configured (backend returns
 *             mistral_configured=false) we show a warning: the toggle is
 *             honoured but there's no EU provider to route to → graceful
 *             fallback to the default chain. The admin must configure
 *             Mistral in Settings → LLM for this toggle to have an effect.
 *
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, Globe, Loader2, ShieldCheck } from "lucide-react";

import { api } from "@/lib/api";

interface SovereigntyPrefs {
  sovereignty_strict: boolean;
  mistral_configured: boolean;
}

export function SovereigntySection() {
  const t = useTranslations("sovereignty");

  const [prefs, setPrefs]     = useState<SovereigntyPrefs | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getSovereigntyPrefs();
      setPrefs(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errorLoad"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { refresh(); }, [refresh]);

  const toggle = async (next: boolean) => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const data = await api.updateSovereigntyPrefs({ sovereignty_strict: next });
      setPrefs(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errorSave"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section>
      <div className="flex items-center gap-2 mb-4">
        <Globe className="w-4 h-4 text-cyber-cyan" />
        <h2 className="text-sm font-medium text-text-primary">{t("title")}</h2>
      </div>
      <div className="section-block space-y-3">
        <p className="text-xs text-text-muted">{t("description")}</p>

        {loading && (
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            {t("loading")}
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded px-3 py-2">
            <AlertTriangle className="w-3.5 h-3.5" />
            {error}
          </div>
        )}

        {prefs && (
          <>
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={prefs.sovereignty_strict}
                disabled={saving}
                onChange={(e) => toggle(e.target.checked)}
                className="w-4 h-4 accent-cyber-cyan"
              />
              <span className="text-sm text-text-primary">
                {t("toggleLabel")}
              </span>
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin text-text-muted" />}
            </label>

            {prefs.sovereignty_strict && prefs.mistral_configured && (
              <div className="flex items-start gap-2 text-xs text-cyber-cyan bg-cyber-cyan/10 border border-cyber-cyan/30 rounded px-3 py-2">
                <ShieldCheck className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span>{t("activeNote")}</span>
              </div>
            )}

            {prefs.sovereignty_strict && !prefs.mistral_configured && (
              <div className="flex items-start gap-2 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded px-3 py-2">
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span>{t("noMistralWarning")}</span>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
