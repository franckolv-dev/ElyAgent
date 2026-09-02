"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/browser/LiveBrowserPanel.tsx
 * @brief      Live browser panel — embedded browser for agent tasks
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *            https://www.elastic.co/licensing/elastic-license
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */

import { useCallback } from "react";
import type { BrowserFrame } from "@/lib/types";

interface LiveBrowserPanelProps {
  frame: BrowserFrame | null;
  onClose: () => void;
}

/**
 * Live Browser Copilot panel — shows real-time screenshots of the headless
 * Chromium instance as Ély navigates the web on behalf of the user.
 *
 * Appears automatically when the agent uses browser tools (navigate / click /
 * fill) and can be dismissed manually.
 */
export function LiveBrowserPanel({ frame, onClose }: LiveBrowserPanelProps) {
  // ⚠️ CE QUE ÇA CORRIGE (02/09) : ce `useCallback` etait appele APRES le
  // `if (!frame) return null` ci-dessous. React identifie les hooks par leur
  // RANG d'appel : le rendu ou `frame` valait null n'en appelait aucun, celui
  // d'apres en appelait un — l'etat interne du composant se decalait d'un cran
  // (« Rendered more hooks than during the previous render »). Le panneau
  // apparait justement quand une image arrive apres avoir ete absente : le
  // chemin fautif etait le chemin nominal. Tout hook doit rester au-dessus de
  // tout retour anticipe.
  const handleClose = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onClose();
    },
    [onClose]
  );

  if (!frame) return null;

  // Shorten URL for display (strip protocol + strip long paths)
  const displayUrl = (() => {
    try {
      const u = new URL(frame.url);
      const host = u.hostname.replace(/^www\./, "");
      const path = u.pathname.length > 30 ? u.pathname.slice(0, 28) + "…" : u.pathname;
      return `${host}${path === "/" ? "" : path}`;
    } catch {
      return frame.url;
    }
  })();

  return (
    <div className="mt-3 rounded-xl overflow-hidden border border-cyber-cyan/30 bg-bg-secondary/80 shadow-lg shadow-cyber-cyan/10 transition-all">
      {/* ── Toolbar ── */}
      <div className="flex items-center gap-2 px-3 py-2 bg-bg-secondary border-b border-cyber-cyan/20">
        {/* Browser chrome dots */}
        <div className="flex gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-red-500/70" />
          <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/70" />
          <div className="w-2.5 h-2.5 rounded-full bg-green-500/70" />
        </div>

        {/* URL bar */}
        <div className="flex-1 flex items-center gap-1.5 bg-bg-primary/60 rounded-md px-2 py-1 min-w-0">
          <svg
            className="w-3 h-3 text-cyber-cyan/60 shrink-0"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          <span className="text-xs text-text-muted truncate font-mono">
            {displayUrl}
          </span>
        </div>

        {/* Live indicator */}
        <div className="flex items-center gap-1 text-xs text-cyber-cyan/70">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyber-cyan opacity-50" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-cyber-cyan" />
          </span>
          <span className="hidden sm:inline">Live</span>
        </div>

        {/* Close button */}
        <button
          onClick={handleClose}
          className="ml-1 text-text-muted hover:text-text-primary transition-colors rounded p-0.5"
          title="Fermer le panneau navigateur"
          aria-label="Fermer"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* ── Screenshot ── */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`data:image/png;base64,${frame.data}`}
        alt={frame.title || "Capture navigateur"}
        className="w-full object-cover max-h-80"
        style={{ display: "block" }}
      />

      {/* ── Page title ── */}
      {frame.title && (
        <div className="px-3 py-1.5 border-t border-cyber-cyan/10">
          <p className="text-xs text-text-muted truncate">{frame.title}</p>
        </div>
      )}
    </div>
  );
}
