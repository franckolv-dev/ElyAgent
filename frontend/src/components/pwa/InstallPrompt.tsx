"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/pwa/InstallPrompt.tsx
 * @brief      PWA install prompt — deferred add-to-home-screen banner
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

import { useEffect, useState } from "react";
import { Download, X } from "lucide-react";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

const DISMISS_KEY = "ely-pwa-install-dismissed";
const SHOW_DELAY_MS = 30_000;

export function InstallPrompt() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;

    // Respect prior dismissal for 7 days
    try {
      const dismissedAt = localStorage.getItem(DISMISS_KEY);
      if (dismissedAt) {
        const age = Date.now() - parseInt(dismissedAt, 10);
        if (age < 7 * 24 * 60 * 60 * 1000) return;
        localStorage.removeItem(DISMISS_KEY);
      }
    } catch {
      // localStorage unavailable
    }

    const handler = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
      // Give the user time to try the app before nagging them
      window.setTimeout(() => setVisible(true), SHOW_DELAY_MS);
    };

    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  const install = async () => {
    if (!deferred) return;
    await deferred.prompt();
    await deferred.userChoice;
    setDeferred(null);
    setVisible(false);
  };

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      // ignore
    }
    setVisible(false);
  };

  if (!visible || !deferred) return null;

  return (
    <div
      role="dialog"
      aria-label="Installer ELY"
      className="fixed bottom-4 right-4 z-50 max-w-sm bg-bg-secondary border border-cyber-cyan/30 rounded-lg shadow-lg p-4 flex items-start gap-3"
    >
      <div className="w-9 h-9 shrink-0 rounded bg-cyber-cyan/10 border border-cyber-cyan/30 flex items-center justify-center">
        <Download className="w-4 h-4 text-cyber-cyan" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-text-primary">Installer ELY</p>
        <p className="text-xs text-text-secondary mt-1">
          Ajoute Eli a ton ecran d&apos;accueil pour y acceder plus vite, meme hors-ligne.
        </p>
        <div className="flex gap-2 mt-3">
          <button
            onClick={install}
            className="px-3 py-1.5 text-xs rounded bg-cyber-cyan/20 text-cyber-cyan border border-cyber-cyan/40 hover:bg-cyber-cyan/30 transition-colors"
          >
            Installer
          </button>
          <button
            onClick={dismiss}
            className="px-3 py-1.5 text-xs rounded text-text-muted hover:text-text-primary transition-colors"
          >
            Plus tard
          </button>
        </div>
      </div>
      <button
        onClick={dismiss}
        aria-label="Fermer"
        className="shrink-0 text-text-muted hover:text-text-primary"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
