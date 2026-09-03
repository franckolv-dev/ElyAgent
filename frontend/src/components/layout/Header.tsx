"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/Header.tsx
 * @brief      Entête — état + langue/thème + bloc utilisateur (refonte 09/2026)
 *
 * La marque est passée en tête de sidebar : depuis la refonte, la sidebar
 * monte sur toute la hauteur et cette entête ne couvre que la colonne de
 * droite. Cf. AppShell.tsx et Sidebar.tsx.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 */

import { useEffect, useState } from "react";
import { Menu, Wifi, WifiOff } from "lucide-react";
import HitlBell from "./HitlBell";
import type { User } from "@/lib/types";
import { api } from "@/lib/api";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { LangSwitcher } from "@/components/layout/LangSwitcher";
import { useTranslations } from "next-intl";

interface HeaderProps {
  wsStatus?: "connected" | "disconnected" | "connecting";
  children?: React.ReactNode;
}

export function Header({ wsStatus, children }: HeaderProps) {
  const t = useTranslations("common");
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api.getMe().then(setUser).catch(() => {});
  }, []);

  return (
    <header className="topbar">
      {/* Hamburger — mobile only, opens the sidebar drawer */}
      <button
        type="button"
        className="mobile-nav-toggle"
        aria-label="Open menu"
        onClick={() =>
          window.dispatchEvent(new CustomEvent("ely-toggle-mobile-nav"))
        }
      >
        <Menu size={18} />
      </button>

      {/* La marque a quitté l'entête : elle vit en tête de sidebar depuis la
          refonte 09/2026, et l'entête commence directement par l'état. */}

      {/* Left: status pill (only when a connection status is provided) */}
      <div className="topbar-center">
        {wsStatus === "connected" && (
          <span className="status-pill">
            <span className="status-dot" />
            {t("connected")}
          </span>
        )}
        {wsStatus === "disconnected" && (
          <span
            className="status-pill"
            style={{ color: "var(--danger)", background: "var(--danger-soft)" }}
          >
            <span className="status-dot" />
            <WifiOff size={11} /> {t("disconnected")}
          </span>
        )}
        {wsStatus === "connecting" && (
          <span
            className="status-pill"
            style={{ color: "var(--warning)", background: "var(--warning-soft)" }}
          >
            <span className="status-dot" />
            <Wifi size={11} /> {t("connecting")}
          </span>
        )}
        {/* Custom children (e.g. conversation title editor on /chat) */}
        {children}
      </div>

      {/* Right: notif / lang / theme / user chip */}
      <div className="topbar-right">
        <HitlBell />
        <LangSwitcher />
        <ThemeToggle />

        {user && (
          <div className="user-chip">
            <div className="user-avatar-chip">
              {user.username?.[0]?.toUpperCase() || "?"}
            </div>
            <span className="user-name">{user.username}</span>
            {user.role === "admin" && <span className="user-role">ADMIN</span>}
          </div>
        )}
      </div>
    </header>
  );
}
