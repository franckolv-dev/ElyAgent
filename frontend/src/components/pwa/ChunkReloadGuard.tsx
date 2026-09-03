"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/pwa/ChunkReloadGuard.tsx
 * @brief      Auto-récupération après déploiement : recharge UNE fois sur une
 *             erreur de chargement de chunk JS.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 *
 * Pourquoi : après un rebuild du frontend, un onglet déjà ouvert garde l'ancien
 * JS en mémoire. Une navigation client-side vers une route dont le hash de chunk
 * a changé déclenche un ChunkLoadError (« This page couldn't load »). Le service
 * worker ayant purgé les anciens chunks, un simple Reload ne suffit pas toujours.
 * Ce garde intercepte ces erreurs (rendu React ET imports dynamiques pendant la
 * navigation) et force UN rechargement dur pour récupérer le shell + les chunks
 * frais. Un drapeau sessionStorage empêche toute boucle si le problème persiste.
 */
import { useEffect } from "react";

import { hardRecoverAndReload } from "@/lib/recover";

const RELOAD_FLAG = "ely-chunk-reloaded";

function isChunkError(message: string): boolean {
  return /ChunkLoadError|Loading chunk [\w-]+ failed|Loading CSS chunk|(?:dynamically )?imported module|Importing a module script failed|error loading dynamically imported/i.test(
    message,
  );
}

export function ChunkReloadGuard() {
  useEffect(() => {
    // Un chargement « propre » a réussi → on lève le drapeau après un court
    // délai, pour qu'un futur déploiement puisse à nouveau recharger.
    const clear = window.setTimeout(() => {
      try {
        sessionStorage.removeItem(RELOAD_FLAG);
      } catch {
        /* sessionStorage indispo (mode privé strict) — sans gravité */
      }
    }, 8000);

    const reloadOnce = (message: string) => {
      if (!isChunkError(message)) return;
      try {
        if (sessionStorage.getItem(RELOAD_FLAG)) return; // déjà rechargé une fois
        sessionStorage.setItem(RELOAD_FLAG, "1");
      } catch {
        /* pas de garde anti-boucle dispo → on recharge quand même une fois */
      }
      void hardRecoverAndReload();
    };

    const onError = (e: ErrorEvent) =>
      reloadOnce(e.message || String(e.error?.message ?? ""));
    const onRejection = (e: PromiseRejectionEvent) =>
      reloadOnce(String(e.reason?.message ?? e.reason ?? ""));

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.clearTimeout(clear);
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  return null;
}
