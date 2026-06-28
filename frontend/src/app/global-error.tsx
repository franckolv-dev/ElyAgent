"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/global-error.tsx
 * @brief      Frontière d'erreur racine — auto-récupération sur ChunkLoadError.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *
 * Remplace l'écran par défaut de Next.js (« This page couldn't load », en
 * anglais) : si l'erreur est un chunk périmé après déploiement, on recharge
 * automatiquement une fois (drapeau anti-boucle) ; sinon on affiche un message
 * français avec un bouton « Recharger » qui force un rechargement dur.
 */
import { useEffect } from "react";

import { hardRecoverAndReload } from "@/lib/recover";

const RELOAD_FLAG = "ely-chunk-reloaded";

function isChunkError(message: string): boolean {
  return /ChunkLoadError|Loading chunk [\w-]+ failed|Loading CSS chunk|(?:dynamically )?imported module|Importing a module script failed/i.test(
    message,
  );
}

export default function GlobalError({
  error,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (!isChunkError(error?.message || "")) return;
    try {
      if (sessionStorage.getItem(RELOAD_FLAG)) return; // déjà rechargé → éviter la boucle
      sessionStorage.setItem(RELOAD_FLAG, "1");
    } catch {
      /* sessionStorage indispo — on recharge quand même une fois */
    }
    void hardRecoverAndReload();
  }, [error]);

  return (
    <html lang="fr">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0a0a0f",
          color: "#e5e7eb",
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        <div style={{ textAlign: "center", padding: 24, maxWidth: 420 }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>⚠️</div>
          <h1 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px" }}>
            La page n'a pas pu se charger
          </h1>
          <p style={{ fontSize: 14, color: "#9ca3af", margin: "0 0 20px" }}>
            Une nouvelle version d'Ely vient peut-être d'être déployée. Recharge
            la page pour récupérer la dernière version.
          </p>
          <button
            type="button"
            onClick={() => void hardRecoverAndReload()}
            style={{
              padding: "10px 20px",
              borderRadius: 8,
              border: "none",
              background: "#22d3ee",
              color: "#06151a",
              fontWeight: 600,
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            Recharger
          </button>
        </div>
      </body>
    </html>
  );
}
