"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/Header.tsx
 * @brief      Topbar — brand + status + lang/theme + user chip (refonte mai 2026)
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 */

import { useEffect, useState } from "react";
import { Bell, Wifi, WifiOff, Zap } from "lucide-react";
import type { User } from "@/lib/types";
import { api } from "@/lib/api";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { LangSwitcher } from "@/components/layout/LangSwitcher";

interface HeaderProps {
  wsStatus?: "connected" | "disconnected" | "connecting";
  children?: React.ReactNode;
}

export function Header({ wsStatus, children }: HeaderProps) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api.getMe().then(setUser).catch(() => {});
  }, []);

  return (
    <header className="topbar">
      {/* Brand (left, 240px wide, matches sidebar width) */}
      <div className="brand">
        <div className="brand-logo">
          <Zap size={16} />
        </div>
        <span className="brand-name">ELY AGENT</span>
      </div>

      {/* Center: status pill (only when connected status is provided) */}
      <div className="topbar-center">
        {wsStatus === "connected" && (
          <span className="status-pill">
            <span className="status-dot" />
            <Wifi size={11} /> CONNECTED
          </span>
        )}
        {wsStatus === "disconnected" && (
          <span className="status-pill" style={{ color: "var(--danger)" }}>
            <span
              className="status-dot"
              style={{ background: "var(--danger)", boxShadow: "0 0 8px var(--danger)" }}
            />
            <WifiOff size={11} /> DISCONNECTED
          </span>
        )}
        {wsStatus === "connecting" && (
          <span className="status-pill" style={{ color: "var(--warning)" }}>
            <span
              className="status-dot"
              style={{ background: "var(--warning)", boxShadow: "0 0 8px var(--warning)" }}
            />
            <Wifi size={11} /> CONNECTING…
          </span>
        )}
        {/* Custom children (e.g. conversation title editor on /chat) */}
        {children}
      </div>

      {/* Right: notif / lang / theme / user chip */}
      <div className="topbar-right">
        <button className="icon-btn" title="Notifications">
          <Bell size={15} />
        </button>
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
