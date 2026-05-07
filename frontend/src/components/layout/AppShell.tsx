"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/AppShell.tsx
 * @brief      Shared layout shell — Header (full-width) + Sidebar + main slot
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
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
  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Header wsStatus={wsStatus}>{headerCenter}</Header>
      {/* Licence enforcement banner (Phase 1) — sits below the topbar so it's
          visible from every page that uses AppShell. */}
      <LicenceBanner />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto" style={{ background: "var(--bg-app)" }}>
          {children}
        </main>
      </div>
    </div>
  );
}
