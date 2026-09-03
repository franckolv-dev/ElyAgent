"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/AppShell.tsx
 * @brief      Shared layout shell — Sidebar (pleine hauteur) + Header + main
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *
 * Use everywhere except /chat (which has its own custom shell with avatar
 * panel + ChatInput dock). Wrap your page content like :
 *
 *   <AppShell>
 *     <PageHeader title="..." />
 *     ...
 *   </AppShell>
 */

import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { LicenceBanner } from "./LicenceBanner";

interface AppShellProps {
  children: React.ReactNode;
  wsStatus?: "connected" | "disconnected" | "connecting";
  /** Optional content slot inside the topbar center (e.g. page title). */
  headerCenter?: React.ReactNode;
}

export function AppShell({ children, wsStatus, headerCenter }: AppShellProps) {
  // Refonte 09/2026 : la sidebar monte sur toute la hauteur et porte la
  // marque ; l'entête ne couvre plus que la colonne de droite. L'ordre des
  // deux blocs s'inverse donc par rapport à la version précédente.
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header wsStatus={wsStatus}>{headerCenter}</Header>
        {/* Licence enforcement banner (Phase 1) — sits below the topbar so
            it's visible from every page that uses AppShell. */}
        <LicenceBanner />
        <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg-app)" }}>
          {children}
        </main>
      </div>
    </div>
  );
}
