/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/offline/page.tsx
 * @brief      Offline page — PWA fallback when network is unavailable
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 */
import { WifiOff } from "lucide-react";

export const metadata = {
  title: "Hors-ligne - ELY",
};

export default function OfflinePage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg-primary text-text-primary p-6">
      <div className="max-w-md text-center">
        <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-cyber-cyan/10 border border-cyber-cyan/30 flex items-center justify-center">
          <WifiOff className="w-8 h-8 text-cyber-cyan" />
        </div>
        <h1 className="text-2xl font-bold text-cyber-cyan glow-cyan-text mb-3">
          Hors-ligne
        </h1>
        <p className="text-sm text-text-secondary mb-6">
          Eli n&apos;est pas joignable pour le moment. Verifie ta connexion reseau,
          puis reessaie. Les conversations en cache restent accessibles une fois
          que tu seras reconnecte.
        </p>
        <a
          href="/chat"
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/30 hover:bg-cyber-cyan/20 transition-all"
        >
          Reessayer
        </a>
      </div>
    </div>
  );
}
