"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/Header.tsx
 * @brief      Header — top navigation bar and status indicators
 *
 * @author     Franck OLLIVIER <franck.olv@gmail.com>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 *             https://polyformproject.org/licenses/strict/1.0.0/
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
 *   - INTERDIT : Toute utilisation commerciale sans accord préalable.
 *   - INTERDIT : Redistribution de versions modifiées de ce code.
 */

import { useEffect, useState } from "react";
import { Circle, Wifi, WifiOff } from "lucide-react";
import type { User } from "@/lib/types";
import { api } from "@/lib/api";
import { ThemeToggle } from "@/components/ui/ThemeToggle";

interface HeaderProps {
  wsStatus?: "connected" | "disconnected" | "connecting";
  children?: React.ReactNode;
}

export function Header({ wsStatus, children }: HeaderProps) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api.getMe().then(setUser).catch(() => {});
  }, []);

  const statusColors = {
    connected:    "text-cyber-cyan",
    disconnected: "text-cyber-red",
    connecting:   "text-cyber-yellow",
  };

  const StatusIcon = wsStatus === "connected" ? Wifi : WifiOff;

  return (
    <header className="h-12 bg-bg-secondary/80 backdrop-blur-sm border-b border-border-dim flex items-center justify-between px-4">
      <div className="flex items-center gap-2">
        {wsStatus && (
          <>
            <StatusIcon className={`w-3.5 h-3.5 ${statusColors[wsStatus]}`} />
            <span className="text-xs text-text-muted uppercase tracking-wider">
              {wsStatus}
            </span>
          </>
        )}
      </div>

      <div className="flex items-center gap-3">
        {children}
        <ThemeToggle />

        {user && (
          <div className="flex items-center gap-2">
            <Circle className="w-2 h-2 fill-cyber-cyan text-cyber-cyan" />
            <span className="text-xs text-text-secondary">{user.username}</span>
            {user.role === "admin" && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyber-purple/10 text-cyber-purple border border-cyber-purple/20">
                ADMIN
              </span>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
