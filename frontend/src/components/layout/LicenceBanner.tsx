"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/LicenceBanner.tsx
 * @brief      Global banner shown below the topbar for licence problems.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 *
 * Visibility states (priority order — only one shown at a time) :
 *   1. No active licence  → BLOCKING, non-dismissible.
 *   2. At max user count  → BLOCKING, non-dismissible.
 *
 * (Demo / trial flow has been intentionally removed — the free tier
 * with 4 users is the evaluation path.)
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Clock, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";

const SESSION_DISMISS_KEY = "ely.licence.banner.dismissed";

type Severity = "blocking" | "warning";

interface BannerState {
  severity: Severity;
  message: string;
  cta: { href: string; label: string };
}

function pickBanner(
  s: Awaited<ReturnType<typeof api.licenceStatus>>,
  t: ReturnType<typeof useTranslations>,
): BannerState | null {
  if (!s.is_provisioned) {
    return {
      severity: "blocking",
      message: t("needsActivation"),
      cta: { href: "/settings?tab=licence", label: t("ctaActivate") },
    };
  }
  if (s.max_users !== null && s.current_users >= s.max_users) {
    return {
      severity: "blocking",
      message: t("atMaxUsers", { current: s.current_users, max: s.max_users }),
      cta: { href: "https://agent-ely.fr/pricing", label: t("ctaSeeTiers") },
    };
  }
  return null;
}

export function LicenceBanner() {
  const t = useTranslations("settings.licence.banner");
  const [banner, setBanner] = useState<BannerState | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .licenceStatus()
      .then((s) => {
        if (cancelled) return;
        setBanner(pickBanner(s, t));
      })
      .catch(() => {
        // Silent fail — banner is best-effort, never block the app.
      });
    if (typeof window !== "undefined") {
      setDismissed(sessionStorage.getItem(SESSION_DISMISS_KEY) === "1");
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!banner) return null;
  if (banner.severity === "warning" && dismissed) return null;

  const isBlocking = banner.severity === "blocking";
  const Icon = isBlocking ? AlertTriangle : Clock;

  const isExternal = banner.cta.href.startsWith("http");

  return (
    <div
      role={isBlocking ? "alert" : "status"}
      style={{
        background: isBlocking ? "var(--danger-bg, rgba(239,68,68,0.10))" : "var(--warning-bg, rgba(245,158,11,0.10))",
        borderBottom: `1px solid ${isBlocking ? "var(--danger, #ef4444)" : "var(--warning, #f59e0b)"}`,
        color: isBlocking ? "var(--danger, #ef4444)" : "var(--warning, #f59e0b)",
        padding: "8px 16px",
        fontSize: 12,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <Icon size={14} style={{ flexShrink: 0 }} />
      <span style={{ flex: 1 }}>{banner.message}</span>
      {isExternal ? (
        <a
          href={banner.cta.href}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            fontWeight: 600,
            textDecoration: "underline",
            color: "inherit",
          }}
        >
          {banner.cta.label}
        </a>
      ) : (
        <Link
          href={banner.cta.href}
          style={{
            fontWeight: 600,
            textDecoration: "underline",
            color: "inherit",
          }}
        >
          {banner.cta.label}
        </Link>
      )}
      {!isBlocking && (
        <button
          type="button"
          onClick={() => {
            sessionStorage.setItem(SESSION_DISMISS_KEY, "1");
            setDismissed(true);
          }}
          aria-label={t("dismissAria")}
          style={{
            background: "transparent",
            border: "none",
            color: "inherit",
            cursor: "pointer",
            padding: 2,
            display: "inline-flex",
          }}
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
}
