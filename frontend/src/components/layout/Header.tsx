"use client";

import { useEffect, useState } from "react";
import { Circle, Wifi, WifiOff } from "lucide-react";
import type { User } from "@/lib/types";
import { api } from "@/lib/api";

interface HeaderProps {
  wsStatus?: "connected" | "disconnected" | "connecting";
}

export function Header({ wsStatus = "disconnected" }: HeaderProps) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api.getMe().then(setUser).catch(() => {});
  }, []);

  const statusColors = {
    connected: "text-cyber-green",
    disconnected: "text-cyber-red",
    connecting: "text-cyber-yellow",
  };

  const StatusIcon = wsStatus === "connected" ? Wifi : WifiOff;

  return (
    <header className="h-12 bg-bg-secondary/80 backdrop-blur-sm border-b border-border-dim flex items-center justify-between px-4">
      <div className="flex items-center gap-2">
        <StatusIcon className={`w-3.5 h-3.5 ${statusColors[wsStatus]}`} />
        <span className="text-xs text-text-muted uppercase tracking-wider">
          {wsStatus}
        </span>
      </div>

      {user && (
        <div className="flex items-center gap-2">
          <Circle className="w-2 h-2 fill-cyber-green text-cyber-green" />
          <span className="text-xs text-text-secondary">{user.username}</span>
          {user.role === "admin" && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyber-purple/10 text-cyber-purple border border-cyber-purple/20">
              ADMIN
            </span>
          )}
        </div>
      )}
    </header>
  );
}
