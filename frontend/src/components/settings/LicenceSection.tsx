"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/settings/LicenceSection.tsx
 * @brief      Licence activation + status panel (Phase 1)
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 *
 * Two states :
 *   1. licence already provisioned → show summary + "Mettre à jour"
 *   2. no active licence → show the three activation choices
 *      (free / paid key).
 *
 * All POSTs require admin role on the backend (require_admin guard) — we
 * still render the form for non-admin users so they see what's available,
 * but they get a 403 if they try to submit.
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, KeyRound, Gift, Building2, ShieldCheck, AlertTriangle } from "lucide-react";
import { useTranslations, useLocale } from "next-intl";
import { api } from "@/lib/api";

type Tier = "free" | "pro" | "business" | "enterprise";

interface LicenceStatus {
  tier: Tier | null;
  max_users: number | null;
  current_users: number;
  customer_label: string | null;
  valid_until: string | null;
  days_remaining: number | null;
  is_demo_expired: boolean;
  is_provisioned: boolean;
  consent_personal_use: boolean;
  activated_at: string | null;
}

function formatDate(iso: string | null, locale: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(locale === "fr" ? "fr-FR" : "en-GB");
  } catch {
    return iso;
  }
}

export function LicenceSection() {
  const t = useTranslations("settings.licence.panel");
  const locale = useLocale();
  const TIER_LABEL: Record<Tier, string> = {
    free: t("choiceFreeTitle"),
    pro: t("tierPro"),
    business: t("tierBusiness"),
    enterprise: t("tierEnterprise"),
  };
  const [status, setStatus] = useState<LicenceStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"free" | "paid" | null>(null);

  // Switch the panel from "summary" to "edit" when the user clicks
  // "{t("btnUpdate")}" on an already-provisioned install.
  const [editing, setEditing] = useState(false);

  // Activation form state
  const [choice, setChoice] = useState<"free" | "paid">("free");
  const [consent, setConsent] = useState(false);
  const [paidTier, setPaidTier] = useState<"pro" | "business" | "enterprise">("pro");
  const [orgName, setOrgName] = useState("");
  const [licenceKey, setLicenceKey] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const s = await api.licenceStatus();
      setStatus(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const submitFree = async () => {
    setBusy("free");
    setError("");
    try {
      await api.activateFree(consent);
      setEditing(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errActivateFailed"));
    } finally {
      setBusy(null);
    }
  };

  const submitPaid = async () => {
    setBusy("paid");
    setError("");
    try {
      await api.activatePaid(paidTier, licenceKey, orgName);
      setEditing(false);
      setLicenceKey("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("errActivateFailed"));
    } finally {
      setBusy(null);
    }
  };

  // ────────────────────────────────────────────────────────────────────────
  // Render — loading / error states
  // ────────────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <section className="space-y-4">
        <div className="flex items-center gap-2 text-xs text-text-muted">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span>{t("titleProvisioned")}…</span>
        </div>
      </section>
    );
  }

  // ────────────────────────────────────────────────────────────────────────
  // Render — provisioned summary
  // ────────────────────────────────────────────────────────────────────────
  const showSummary = status?.is_provisioned && !editing;

  if (showSummary && status) {
    const tierLabel = status.tier ? TIER_LABEL[status.tier] : "—";
    const usage =
      status.max_users === null
        ? `${status.current_users} / ∞ utilisateurs`
        : `${status.current_users} / ${status.max_users} utilisateurs`;

    return (
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-cyber-cyan" />
          <h2 className="text-sm font-medium text-text-primary">{t("titleProvisioned")}</h2>
        </div>

        <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-2">
          <div className="grid grid-cols-1 sm:grid-cols-[140px_1fr] gap-y-1 text-xs">
            <div className="text-text-muted">{t("tierLabel")}</div>
            <div className="text-text-primary font-medium">{tierLabel}</div>
            <div className="text-text-muted">{t("limitLabel")}</div>
            <div className="text-text-primary">{usage}</div>
            <div className="text-text-muted">{t("customerLabel")}</div>
            <div className="text-text-primary">{status.customer_label || "—"}</div>
            <div className="text-text-muted">{t("expiryLabel")}</div>
            <div className="text-text-primary">
              {status.valid_until ? (
                <>
                  {formatDate(status.valid_until, locale)}
                  {status.days_remaining !== null && (
                    <span className="text-text-muted">
                      {" "}
                      {status.days_remaining === 1 ? "(in 1 day)" : "(in " + status.days_remaining + " days)"}
                    </span>
                  )}
                </>
              ) : (
                t("expiryNever")
              )}
            </div>
            <div className="text-text-muted">{t("expiryLabel")}</div>
            <div className="text-text-primary">{formatDate(status.activated_at, locale)}</div>
          </div>


          <div className="flex gap-2 pt-3 border-t border-border-dim">
            <button
              type="button"
              onClick={() => {
                setEditing(true);
                setOrgName(status.customer_label || "");
              }}
              className="btn"
            >
              Mettre à jour la licence
            </button>
            <a
              href="https://agent-ely.fr/legal/cgu"
              target="_blank"
              rel="noopener noreferrer"
              className="btn"
            >
              {t("consentLink")}
            </a>
          </div>
        </div>

        {error && (
          <div className="text-xs text-cyber-red border border-cyber-red/30 bg-cyber-red/5 rounded px-3 py-2">
            {error}
          </div>
        )}
      </section>
    );
  }

  // ────────────────────────────────────────────────────────────────────────
  // Render — activation flow
  // ────────────────────────────────────────────────────────────────────────
  return (
    <section className="space-y-4">
      <div className="flex items-center gap-2">
        <KeyRound className="w-4 h-4 text-cyber-cyan" />
        <h2 className="text-sm font-medium text-text-primary">
          {status?.is_provisioned ? t("btnUpdate") : t("titleActivate")}
        </h2>
      </div>

      {!status?.is_provisioned && (
        <p className="text-xs text-text-muted">
          {t("intro")}
        </p>
      )}

      {error && (
        <div className="text-xs text-cyber-red border border-cyber-red/30 bg-cyber-red/5 rounded px-3 py-2">
          {error}
        </div>
      )}

      <div className="bg-bg-secondary border border-border-dim rounded-lg divide-y divide-border-dim">
        {/* ─── Free tier ────────────────────────────────────────────────── */}
        <div className="p-4 space-y-3">
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              name="licence-choice"
              checked={choice === "free"}
              onChange={() => setChoice("free")}
              className="mt-0.5"
            />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <Gift className="w-3.5 h-3.5 text-cyber-cyan" />
                <span className="text-sm font-medium text-text-primary">
                  {t("choiceFreeTitle")}
                </span>
              </div>
              <p className="text-[11px] text-text-muted mt-1">
                {t("choiceFreeBlurb")}
              </p>
            </div>
          </label>
          {choice === "free" && (
            <div className="pl-6 space-y-2">
              <label className="flex items-start gap-2 text-xs text-text-secondary">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  {t("consentRequired")}{" "}
                  <a
                    href="https://agent-ely.fr/legal/cgu"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-cyber-cyan hover:underline"
                  >
                    {t("consentLink")}
                  </a>
                </span>
              </label>
              <button
                type="button"
                onClick={submitFree}
                disabled={!consent || busy !== null}
                className="btn primary"
              >
                {busy === "free" ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-1" />
                    Activation…
                  </>
                ) : (
                  t("choiceFreeBtn")
                )}
              </button>
            </div>
          )}
        </div>

        {/* ─── Paid tier ────────────────────────────────────────────────── */}
        <div className="p-4 space-y-3">
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              name="licence-choice"
              checked={choice === "paid"}
              onChange={() => setChoice("paid")}
              className="mt-0.5"
            />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <Building2 className="w-3.5 h-3.5 text-cyber-cyan" />
                <span className="text-sm font-medium text-text-primary">
                  {t("choicePaidTitle")}
                </span>
              </div>
              <p className="text-[11px] text-text-muted mt-1">
                {t("choicePaidBlurb")}
              </p>
            </div>
          </label>
          {choice === "paid" && (
            <div className="pl-6 space-y-2">
              <label className="block text-xs text-text-secondary">
                {t("tierField")}
                <select
                  value={paidTier}
                  onChange={(e) => setPaidTier(e.target.value as "pro" | "business" | "enterprise")}
                  className="block mt-1 w-full bg-bg-tertiary border border-border-dim rounded px-2 py-1 text-xs text-text-primary"
                >
                  <option value="pro">Pro (5 utilisateurs — 490 €/an)</option>
                  <option value="business">Business (25 utilisateurs — 1 990 €/an)</option>
                  <option value="enterprise">Enterprise (illimité — sur devis)</option>
                </select>
              </label>
              <label className="block text-xs text-text-secondary">
                {t("orgField")}
                <input
                  type="text"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  placeholder={t("orgPlaceholder")}
                  className="block mt-1 w-full bg-bg-tertiary border border-border-dim rounded px-2 py-1 text-xs text-text-primary"
                />
              </label>
              <label className="block text-xs text-text-secondary">
                {t("keyField")}
                <textarea
                  value={licenceKey}
                  onChange={(e) => setLicenceKey(e.target.value)}
                  placeholder={t("keyPlaceholder")}
                  rows={3}
                  className="block mt-1 w-full bg-bg-tertiary border border-border-dim rounded px-2 py-1 text-xs font-mono text-text-primary"
                />
              </label>
              <button
                type="button"
                onClick={submitPaid}
                disabled={
                  !licenceKey.trim() || !orgName.trim() || busy !== null
                }
                className="btn primary"
              >
                {busy === "paid" ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-1" />
                    Activation…
                  </>
                ) : (
                  t("btnActivatePaid")
                )}
              </button>
            </div>
          )}
        </div>

      </div>

      {status?.is_provisioned && editing && (
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="text-xs text-text-muted hover:text-text-primary underline"
        >
          {locale === "fr" ? "Annuler" : "Cancel"}
        </button>
      )}
    </section>
  );
}
