"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/settings/LicenceSection.tsx
 * @brief      Licence information panel — Elastic License v2
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *             https://www.elastic.co/licensing/elastic-license
 *
 * @summary
 *   - Allowed   : personal use + internal business use (any org size)
 *   - Allowed   : modify and redistribute (keeping notices)
 *   - Forbidden : resell as a hosted / managed service (no SaaS)
 *   - Forbidden : remove or obscure copyright / licence notices
 *
 * Simplified 2026-05-28 — Franck's licence pivot of 22 May 2026: ELY moved
 * from PolyForm Strict + paid tiers (Pro €490/yr, Business €1,990/yr,
 * Enterprise on quote) to a single Elastic License v2 with no tiers and
 * no activation. The panel is now a static read-only info card that
 * mirrors agent-ely.fr/pricing.html. The whole tier/key activation flow
 * has been removed from the backend (see commit "chore: harmonise repo
 * with site").
 */
import { ShieldCheck, ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

export function LicenceSection() {
  // Translations are nested under settings.licence.panel. We only need a
  // small subset; fallbacks below cover environments where the locale
  // hasn't been refreshed yet.
  const t = useTranslations("settings.licence.panel");

  // Defensive fallback wrapper — older locale files may not have all
  // the new keys yet. Returns the raw key (matching i18n's default) if
  // translation is unavailable, which is acceptable for an info panel.
  const safe = (key: string, fallback: string): string => {
    try {
      const v = t(key);
      if (!v || v === key) return fallback;
      return v;
    } catch {
      return fallback;
    }
  };

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <ShieldCheck className="w-4 h-4 text-cyber-cyan" />
        <h2 className="text-sm font-medium text-text-primary">
          {safe("title", "Licence")}
        </h2>
      </div>

      <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3 text-xs">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-text-muted">
            {safe("licenseLabel", "Licence")}
          </span>
          <a
            href="https://www.elastic.co/licensing/elastic-license"
            target="_blank"
            rel="noopener noreferrer"
            className="text-text-primary font-medium hover:text-cyber-cyan inline-flex items-center gap-1"
          >
            Elastic License v2
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>

        <p className="text-text-secondary leading-relaxed">
          {safe(
            "summary",
            "ELY est gratuit pour tout usage personnel et professionnel interne. " +
            "Modification et redistribution autorisées. Revente comme service " +
            "hébergé (SaaS) à des tiers interdite."
          )}
        </p>

        <ul className="space-y-1 text-text-muted">
          <li>
            <span className="text-cyber-green">✓</span>{" "}
            {safe(
              "allowPersonal",
              "Usage personnel et familial — sans limite"
            )}
          </li>
          <li>
            <span className="text-cyber-green">✓</span>{" "}
            {safe(
              "allowBusiness",
              "Usage professionnel interne — quelle que soit la taille de l'organisation"
            )}
          </li>
          <li>
            <span className="text-cyber-green">✓</span>{" "}
            {safe(
              "allowModify",
              "Modification du code, redistribution (en gardant les notices)"
            )}
          </li>
          <li>
            <span className="text-cyber-red">✗</span>{" "}
            {safe(
              "forbidSaas",
              "Revente comme SaaS ou service managé à des tiers"
            )}
          </li>
          <li>
            <span className="text-cyber-red">✗</span>{" "}
            {safe(
              "forbidNotice",
              "Suppression des notices de copyright ou de licence"
            )}
          </li>
        </ul>

        <div className="pt-3 border-t border-border-dim flex flex-wrap items-center gap-3 text-[11px]">
          <a
            href="https://agent-ely.fr/pricing.html"
            target="_blank"
            rel="noopener noreferrer"
            className="text-cyber-cyan hover:underline inline-flex items-center gap-1"
          >
            {safe("officialPage", "Page officielle")}
            <ExternalLink className="w-3 h-3" />
          </a>
          <span className="text-text-muted">·</span>
          <a
            href="https://github.com/franckolv-dev/ElyAgent/blob/main/LICENSE"
            target="_blank"
            rel="noopener noreferrer"
            className="text-cyber-cyan hover:underline inline-flex items-center gap-1"
          >
            {safe("fullText", "Texte intégral (GitHub)")}
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      </div>
    </section>
  );
}
