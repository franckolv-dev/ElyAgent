"use client";
// -----------------------------------------------------------------------------
// Copyright (c) 2024 Franck OLLIVIER
// Tous droits réservés.
//
// Ce logiciel est mis à disposition sous les termes de la licence
// PolyForm Strict License 1.0.0.
//
// RÉSUMÉ DES CONDITIONS :
// - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
// - INTERDIT : Toute utilisation commerciale sans accord préalable.
// - INTERDIT : Redistribution de versions modifiées de ce code.
//
// Pour consulter le texte intégral de la licence, veuillez vous référer au
// fichier LICENSE à la racine du projet ou visiter :
// https://polyformproject.org/licenses/strict/1.0.0/
// -----------------------------------------------------------------------------

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { MessageSquare, LayoutDashboard, Settings, Shield, ShieldCheck, LogOut, Cpu, Plus, Clock } from "lucide-react";
import { logout, isAdmin } from "@/lib/auth";
import { api } from "@/lib/api";
import { useTranslations } from "next-intl";

interface RecentConv {
  id: string;
  title: string;
  created_at: string | null;
}

const BASE_NAV = [
  { href: "/chat",     label: "Chat",     icon: MessageSquare },
  { href: "/settings", label: "Settings", icon: Settings      },
];

const ADMIN_NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/security",  label: "Securite",  icon: ShieldCheck     },
  { href: "/admin",     label: "Admin",     icon: Shield          },
];

export function Sidebar() {
  const t        = useTranslations("sidebar");
  const pathname = usePathname();
  const router   = useRouter();
  const admin    = isAdmin();
  const [conversations, setConversations] = useState<RecentConv[]>([]);
  const [expanded, setExpanded] = useState(false);

  const navItems = admin ? [...BASE_NAV, ...ADMIN_NAV] : BASE_NAV;

  useEffect(() => {
    api.getConversations(15).then(setConversations).catch(() => {});
  }, [pathname]); // refresh when navigating

  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

  return (
    <aside className="w-16 lg:w-56 h-screen bg-bg-secondary border-r border-border-dim flex flex-col shrink-0 overflow-hidden">
      {/* Logo */}
      <div className="p-4 border-b border-border-dim shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-cyber-cyan/10 border border-cyber-cyan/30 flex items-center justify-center shrink-0">
            <Cpu className="w-4 h-4 text-cyber-cyan" />
          </div>
          <span className="hidden lg:block text-sm font-bold text-cyber-cyan glow-cyan-text tracking-wider">
            ELY AGENT
          </span>
        </div>
      </div>

      {/* Main nav + new conversation */}
      <nav className="p-2 space-y-1 shrink-0">
        {navItems.map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href || pathname.startsWith(href + "?");
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-all ${
                isActive
                  ? "bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/20"
                  : "text-text-secondary hover:text-text-primary hover:bg-bg-tertiary"
              }`}
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span className="hidden lg:block">{label}</span>
            </Link>
          );
        })}

        {/* New conversation button — always force a fresh /chat page */}
        <button
          onClick={() => router.push("/chat?new=" + Date.now())}
          className="hidden lg:flex items-center gap-3 px-3 py-2 rounded-md text-xs text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/5 border border-dashed border-border-dim hover:border-cyber-cyan/30 transition-all mt-1 w-full"
        >
          <Plus className="w-3.5 h-3.5 shrink-0" />
          <span>{t("newConversation")}</span>
        </button>
      </nav>

      {/* Recent conversations */}
      {conversations.length > 0 && (
        <div className="hidden lg:flex flex-col flex-1 min-h-0 mt-1">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-2 px-3 py-1.5 text-[10px] text-text-muted uppercase tracking-wider hover:text-text-secondary transition-colors shrink-0"
          >
            <Clock className="w-3 h-3" />
            <span>{t("recent")}</span>
            <span className="ml-auto text-[9px]">{expanded ? "▲" : "▼"}</span>
          </button>

          {expanded && (
            <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0">
              {conversations.map((conv) => {
                const isActive = pathname === `/chat` && typeof window !== "undefined" &&
                  new URLSearchParams(window.location.search).get("c") === conv.id;
                return (
                  <Link
                    key={conv.id}
                    href={`/chat?c=${conv.id}`}
                    className={`block px-2 py-1.5 text-xs truncate transition-all border-y ${
                      isActive
                        ? "bg-cyber-cyan/10 text-cyber-cyan border-cyber-cyan/20"
                        : "text-text-muted border-transparent hover:text-cyber-cyan hover:bg-cyber-cyan/10 hover:border-cyber-cyan/20"
                    }`}
                    title={conv.title}
                  >
                    {conv.title}
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Logout */}
      <div className="p-2 border-t border-border-dim shrink-0 mt-auto">
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-text-secondary hover:text-cyber-red hover:bg-cyber-red/5 transition-all w-full"
        >
          <LogOut className="w-4 h-4 shrink-0" />
          <span className="hidden lg:block">Logout</span>
        </button>
      </div>
    </aside>
  );
}
