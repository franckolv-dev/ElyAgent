"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/settings/GoogleSetupWizard.tsx
 * @brief      Step-by-step modal wizard to set up Google OAuth credentials
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *
 * 7 steps :
 *   1. Welcome / overview
 *   2. Create Google Cloud project (deep link)
 *   3. Enable 7 APIs (deep links + checklist)
 *   4. Configure OAuth consent screen (scopes copy-paste, test users)
 *   5. Create OAuth credentials (redirect URIs copy-paste)
 *   6. Paste credentials in ELY (input fields, save)
 *   7. Test connection (auto-launch OAuth flow)
 *
 * The wizard saves credentials via POST /api/google/app-config (admin only).
 */
import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  X,
  ChevronRight,
  ChevronLeft,
  Check,
  ExternalLink,
  Copy,
  CheckCircle2,
} from "lucide-react";
import { api } from "@/lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
  onComplete?: () => void;
}

const TOTAL_STEPS = 7;

const SCOPES = [
  "https://www.googleapis.com/auth/gmail.modify",
  "https://www.googleapis.com/auth/gmail.send",
  "https://www.googleapis.com/auth/calendar",
  "https://www.googleapis.com/auth/drive",
  "https://www.googleapis.com/auth/documents",
  "https://www.googleapis.com/auth/spreadsheets",
  "https://www.googleapis.com/auth/tasks",
  "https://www.googleapis.com/auth/contacts",
];

const APIS: Array<{ name: string; url: string }> = [
  { name: "Gmail API", url: "https://console.cloud.google.com/apis/library/gmail.googleapis.com" },
  { name: "Calendar API", url: "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com" },
  { name: "Drive API", url: "https://console.cloud.google.com/apis/library/drive.googleapis.com" },
  { name: "Docs API", url: "https://console.cloud.google.com/apis/library/docs.googleapis.com" },
  { name: "Sheets API", url: "https://console.cloud.google.com/apis/library/sheets.googleapis.com" },
  { name: "Tasks API", url: "https://console.cloud.google.com/apis/library/tasks.googleapis.com" },
  { name: "People API (Contacts)", url: "https://console.cloud.google.com/apis/library/people.googleapis.com" },
];

function CopyButton({ text, label }: { text: string; label: string }) {
  const t = useTranslations("settings.googleWizard");
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded border border-border-dim hover:border-cyber-cyan hover:text-cyber-cyan transition"
      title={label}
    >
      {done ? <CheckCircle2 size={12} /> : <Copy size={12} />}
      {done ? t("copied") : t("copy")}
    </button>
  );
}

function ExternalButton({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-cyber-cyan/10 border border-cyber-cyan/40 text-cyber-cyan hover:bg-cyber-cyan/20 transition font-medium"
    >
      <ExternalLink size={12} />
      {label}
    </a>
  );
}

export function GoogleSetupWizard({ open, onClose, onComplete }: Props) {
  const t = useTranslations("settings.googleWizard");
  const [step, setStep] = useState(1);
  const [apisChecked, setApisChecked] = useState<Record<string, boolean>>({});
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  if (!open) return null;

  // Compute redirect URIs from current host (so wizard works wherever ELY runs)
  const apiBase =
    typeof window !== "undefined"
      ? `${window.location.origin}/api/google/oauth/callback`
      : "/api/google/oauth/callback";
  const redirectUris = [apiBase, "http://localhost:8000/api/google/oauth/callback"]
    .filter((v, i, a) => a.indexOf(v) === i)
    .join("\n");

  const handleSaveCredentials = async () => {
    setSaving(true);
    setError("");
    try {
      await api.saveGoogleAppConfig(clientId.trim(), clientSecret.trim());
      setSaved(true);
      setTimeout(() => {
        setStep(7);
        setSaved(false);
      }, 800);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("step6Error"));
    } finally {
      setSaving(false);
    }
  };

  const handleConnect = async () => {
    try {
      const { url } = await api.getGoogleAuthUrl("default");
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "OAuth URL fetch failed");
    }
  };

  const next = () => setStep((s) => Math.min(s + 1, TOTAL_STEPS));
  const prev = () => setStep((s) => Math.max(s - 1, 1));

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="google-wizard-title"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.7)",
        zIndex: 200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg-elevated, #11161c)",
          border: "1px solid var(--border-strong, #2a333e)",
          borderRadius: 12,
          width: "100%",
          maxWidth: 720,
          maxHeight: "90vh",
          overflowY: "auto",
          boxShadow: "0 24px 60px -12px rgba(0,0,0,0.65)",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 20px",
            borderBottom: "1px solid var(--border-subtle, #1f2730)",
          }}
        >
          <div>
            <h2 id="google-wizard-title" style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>
              {t("wizardTitle")}
            </h2>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
              {t("stepLabel", { current: step, total: TOTAL_STEPS })}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label={t("close")}
            style={{
              background: "transparent",
              border: 0,
              color: "var(--text-muted)",
              cursor: "pointer",
              padding: 4,
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Progress bar */}
        <div style={{ height: 3, background: "var(--bg-secondary)" }}>
          <div
            style={{
              height: "100%",
              width: `${(step / TOTAL_STEPS) * 100}%`,
              background: "var(--cyber-cyan, #13bbc2)",
              transition: "width 200ms",
            }}
          />
        </div>

        {/* Body */}
        <div style={{ padding: 24, fontSize: 13, lineHeight: 1.6 }}>
          {step === 1 && (
            <>
              <h3 style={{ fontSize: 18, marginTop: 0, marginBottom: 12 }}>{t("step1Title")}</h3>
              <p style={{ color: "var(--text-secondary)" }}>{t("step1Body")}</p>
            </>
          )}

          {step === 2 && (
            <>
              <h3 style={{ fontSize: 18, marginTop: 0, marginBottom: 12 }}>{t("step2Title")}</h3>
              <p style={{ color: "var(--text-secondary)" }}>{t("step2Body")}</p>
              <div style={{ marginTop: 16 }}>
                <ExternalButton
                  href="https://console.cloud.google.com/projectcreate"
                  label={t("openInGoogle")}
                />
              </div>
            </>
          )}

          {step === 3 && (
            <>
              <h3 style={{ fontSize: 18, marginTop: 0, marginBottom: 12 }}>{t("step3Title")}</h3>
              <p style={{ color: "var(--text-secondary)" }}>{t("step3Body")}</p>
              <ul style={{ listStyle: "none", padding: 0, margin: "16px 0", display: "flex", flexDirection: "column", gap: 6 }}>
                {APIS.map((apiInfo) => (
                  <li
                    key={apiInfo.name}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "8px 12px",
                      background: "var(--bg-secondary)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: 6,
                    }}
                  >
                    <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={!!apisChecked[apiInfo.name]}
                        onChange={(e) =>
                          setApisChecked((p) => ({ ...p, [apiInfo.name]: e.target.checked }))
                        }
                        style={{ accentColor: "var(--cyber-cyan)" }}
                      />
                      <span style={{ fontSize: 12 }}>{apiInfo.name}</span>
                    </label>
                    <ExternalButton href={apiInfo.url} label={t("openInGoogle")} />
                  </li>
                ))}
              </ul>
              <p style={{ fontSize: 11, color: "var(--text-muted)", fontStyle: "italic" }}>
                {t("step3Note")}
              </p>
            </>
          )}

          {step === 4 && (
            <>
              <h3 style={{ fontSize: 18, marginTop: 0, marginBottom: 12 }}>{t("step4Title")}</h3>
              <p style={{ color: "var(--text-secondary)", marginBottom: 12 }}>{t("step4Body")}</p>
              <div style={{ margin: "12px 0" }}>
                <ExternalButton
                  href="https://console.cloud.google.com/apis/credentials/consent"
                  label={t("openInGoogle")}
                />
              </div>
              <ol style={{ paddingLeft: 18, color: "var(--text-secondary)", display: "flex", flexDirection: "column", gap: 8 }}>
                <li>{t("step4StepUserType")}</li>
                <li>{t("step4StepAppInfo")}</li>
                <li>
                  {t("step4StepScopes")}
                  <div
                    style={{
                      marginTop: 8,
                      padding: 12,
                      background: "var(--bg-secondary)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: 6,
                      fontFamily: "var(--font-mono, monospace)",
                      fontSize: 11,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-all",
                      position: "relative",
                    }}
                  >
                    <div style={{ position: "absolute", top: 6, right: 6 }}>
                      <CopyButton text={SCOPES.join("\n")} label={t("copy")} />
                    </div>
                    {SCOPES.join("\n")}
                  </div>
                </li>
                <li>{t("step4StepTestUsers")}</li>
                <li>{t("step4StepPublish")}</li>
              </ol>
            </>
          )}

          {step === 5 && (
            <>
              <h3 style={{ fontSize: 18, marginTop: 0, marginBottom: 12 }}>{t("step5Title")}</h3>
              <p style={{ color: "var(--text-secondary)", marginBottom: 12 }}>{t("step5Body")}</p>
              <div style={{ margin: "12px 0" }}>
                <ExternalButton
                  href="https://console.cloud.google.com/apis/credentials"
                  label={t("openInGoogle")}
                />
              </div>
              <ol style={{ paddingLeft: 18, color: "var(--text-secondary)", display: "flex", flexDirection: "column", gap: 8 }}>
                <li>{t("step5StepName")}</li>
                <li>{t("step5StepOrigins")}</li>
                <li>
                  {t("step5StepRedirect")}
                  <div
                    style={{
                      marginTop: 8,
                      padding: 12,
                      background: "var(--bg-secondary)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: 6,
                      fontFamily: "var(--font-mono, monospace)",
                      fontSize: 11,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-all",
                      position: "relative",
                    }}
                  >
                    <div style={{ position: "absolute", top: 6, right: 6 }}>
                      <CopyButton text={redirectUris} label={t("copy")} />
                    </div>
                    {redirectUris}
                  </div>
                </li>
                <li style={{ color: "var(--cyber-cyan)" }}>{t("step5StepNote")}</li>
              </ol>
            </>
          )}

          {step === 6 && (
            <>
              <h3 style={{ fontSize: 18, marginTop: 0, marginBottom: 12 }}>{t("step6Title")}</h3>
              <p style={{ color: "var(--text-secondary)", marginBottom: 16 }}>{t("step6Body")}</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <label style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  {t("step6FieldClientId")}
                  <input
                    type="text"
                    value={clientId}
                    onChange={(e) => setClientId(e.target.value)}
                    placeholder="123456789-abcde.apps.googleusercontent.com"
                    style={{
                      display: "block",
                      width: "100%",
                      marginTop: 4,
                      padding: "8px 10px",
                      background: "var(--bg-tertiary)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: 4,
                      fontSize: 12,
                      fontFamily: "var(--font-mono, monospace)",
                      color: "var(--text-primary)",
                    }}
                  />
                </label>
                <label style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  {t("step6FieldClientSecret")}
                  <input
                    type="password"
                    value={clientSecret}
                    onChange={(e) => setClientSecret(e.target.value)}
                    placeholder="GOCSPX-..."
                    style={{
                      display: "block",
                      width: "100%",
                      marginTop: 4,
                      padding: "8px 10px",
                      background: "var(--bg-tertiary)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: 4,
                      fontSize: 12,
                      fontFamily: "var(--font-mono, monospace)",
                      color: "var(--text-primary)",
                    }}
                  />
                </label>
                {error && (
                  <div style={{ fontSize: 12, color: "var(--cyber-red, #ef4444)" }}>{error}</div>
                )}
                {saved && (
                  <div style={{ fontSize: 12, color: "var(--cyber-cyan)" }}>
                    <Check size={12} style={{ display: "inline", verticalAlign: "middle" }} />{" "}
                    {t("step6Saved")}
                  </div>
                )}
              </div>
            </>
          )}

          {step === 7 && (
            <>
              <h3 style={{ fontSize: 18, marginTop: 0, marginBottom: 12 }}>{t("step7Title")}</h3>
              <p style={{ color: "var(--text-secondary)", marginBottom: 16 }}>{t("step7Body")}</p>
              <button
                type="button"
                onClick={handleConnect}
                style={{
                  padding: "10px 16px",
                  background: "var(--cyber-cyan)",
                  color: "#001012",
                  fontWeight: 600,
                  fontSize: 13,
                  border: 0,
                  borderRadius: 6,
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                {t("step7Connect")} <ChevronRight size={14} />
              </button>
              <div style={{ marginTop: 16 }}>
                <button
                  type="button"
                  onClick={() => {
                    onComplete?.();
                    onClose();
                  }}
                  style={{
                    fontSize: 12,
                    color: "var(--text-muted)",
                    background: "transparent",
                    border: 0,
                    textDecoration: "underline",
                    cursor: "pointer",
                  }}
                >
                  {t("step7Skip")}
                </button>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            padding: "12px 20px",
            borderTop: "1px solid var(--border-subtle)",
          }}
        >
          <button
            type="button"
            onClick={prev}
            disabled={step === 1}
            style={{
              fontSize: 12,
              padding: "6px 12px",
              background: "transparent",
              border: "1px solid var(--border-subtle)",
              borderRadius: 4,
              color: "var(--text-secondary)",
              cursor: step === 1 ? "not-allowed" : "pointer",
              opacity: step === 1 ? 0.4 : 1,
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            <ChevronLeft size={12} />
            {t("previous")}
          </button>
          {step < 6 && (
            <button
              type="button"
              onClick={next}
              style={{
                fontSize: 12,
                padding: "6px 12px",
                background: "var(--cyber-cyan)",
                color: "#001012",
                border: 0,
                borderRadius: 4,
                fontWeight: 600,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              {t("iAmDone")}
              <ChevronRight size={12} />
            </button>
          )}
          {step === 6 && (
            <button
              type="button"
              onClick={handleSaveCredentials}
              disabled={!clientId.trim() || !clientSecret.trim() || saving}
              style={{
                fontSize: 12,
                padding: "6px 12px",
                background: "var(--cyber-cyan)",
                color: "#001012",
                border: 0,
                borderRadius: 4,
                fontWeight: 600,
                cursor: saving ? "wait" : "pointer",
                opacity: !clientId.trim() || !clientSecret.trim() ? 0.4 : 1,
              }}
            >
              {saving ? t("step6Saving") : t("step6Save")}
            </button>
          )}
          {step === 7 && (
            <button
              type="button"
              onClick={() => {
                onComplete?.();
                onClose();
              }}
              style={{
                fontSize: 12,
                padding: "6px 12px",
                background: "var(--cyber-cyan)",
                color: "#001012",
                border: 0,
                borderRadius: 4,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {t("finish")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
