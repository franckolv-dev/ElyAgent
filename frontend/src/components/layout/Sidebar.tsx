"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/Sidebar.tsx
 * @brief      Sidebar — navigation menu and conversation history
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
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

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  MessageSquare, LayoutDashboard, Settings, Shield, ShieldCheck, LogOut,
  Cpu, Plus, Clock, Search, MoreHorizontal, Pencil, Trash2,
  Download, X, ChevronDown, Swords, BookOpen, Target,
} from "lucide-react";
import { logout, isAdmin } from "@/lib/auth";
import { api } from "@/lib/api";
import { useTranslations } from "next-intl";

interface RecentConv {
  id: string;
  title: string;
  created_at: string | null;
}

const PAGE_SIZE = 50;

// Nav entries — `labelKey` is resolved at render time via t(labelKey) so
// the sidebar follows the user's locale automatically.
const BASE_NAV = [
  { href: "/chat",      labelKey: "navChat",        icon: MessageSquare },
  { href: "/missions",  labelKey: "navMissions",    icon: Target        },
  { href: "/knowledge", labelKey: "navKnowledge",   icon: BookOpen      },
  { href: "/arena",     labelKey: "navArena",       icon: Swords        },
  { href: "/settings",  labelKey: "navSettings",    icon: Settings      },
];

const ADMIN_NAV = [
  { href: "/dashboard", labelKey: "navDashboard", icon: LayoutDashboard },
  { href: "/security",  labelKey: "navSecurity",  icon: ShieldCheck     },
  { href: "/admin",     labelKey: "navAdmin",     icon: Shield          },
];

export function Sidebar() {
  const t        = useTranslations("sidebar");
  const pathname = usePathname();
  const router   = useRouter();
  const admin    = isAdmin();

  const [conversations, setConversations] = useState<RecentConv[]>([]);
  const [totalCount, setTotalCount]       = useState(0);
  const [expanded, setExpanded]           = useState(false);
  const [searchQuery, setSearchQuery]     = useState("");

  // Context menu
  const [menuConvId, setMenuConvId]   = useState<string | null>(null);
  const [menuPos, setMenuPos]         = useState({ x: 0, y: 0 });
  const menuRef = useRef<HTMLDivElement>(null);

  // Inline rename
  const [renamingId, setRenamingId]       = useState<string | null>(null);
  const [renameValue, setRenameValue]     = useState("");
  const renameInputRef = useRef<HTMLInputElement>(null);

  // Delete confirmation
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const navItems = admin ? [...BASE_NAV, ...ADMIN_NAV] : BASE_NAV;

  // -- Fetch conversations ---------------------------------------------------
  const fetchConversations = useCallback(
    async (opts?: { offset?: number; query?: string; append?: boolean }) => {
      const offset = opts?.offset ?? 0;
      const q = opts?.query ?? searchQuery;
      try {
        const data = await api.getConversations({ limit: PAGE_SIZE, offset, q: q || undefined });
        const items: RecentConv[] = data.conversations ?? data;
        if (opts?.append) {
          setConversations((prev) => [...prev, ...items]);
        } else {
          setConversations(items);
        }
        setTotalCount(data.total_count ?? items.length);
      } catch {
        // silent
      }
    },
    [searchQuery],
  );

  // Reload on navigation
  useEffect(() => {
    fetchConversations({ query: searchQuery });
  }, [pathname, fetchConversations, searchQuery]);

  // -- Debounced search -------------------------------------------------------
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetchConversations({ query: value });
    }, 300);
  };

  // -- Load more --------------------------------------------------------------
  const hasMore = conversations.length < totalCount;
  const loadMore = () => {
    fetchConversations({ offset: conversations.length, append: true });
  };

  // -- Context menu handlers --------------------------------------------------
  const openMenu = (e: React.MouseEvent, convId: string) => {
    e.preventDefault();
    e.stopPropagation();
    setMenuConvId(convId);
    setMenuPos({ x: e.clientX, y: e.clientY });
  };

  // Close menu on outside click
  useEffect(() => {
    if (!menuConvId) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuConvId(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuConvId]);

  // -- Rename -----------------------------------------------------------------
  const startRename = (conv: RecentConv) => {
    setMenuConvId(null);
    setRenamingId(conv.id);
    setRenameValue(conv.title);
    setTimeout(() => renameInputRef.current?.select(), 50);
  };

  const commitRename = async () => {
    if (!renamingId || !renameValue.trim()) {
      setRenamingId(null);
      return;
    }
    try {
      await api.renameConversation(renamingId, renameValue.trim());
      setConversations((prev) =>
        prev.map((c) => (c.id === renamingId ? { ...c, title: renameValue.trim() } : c)),
      );
    } catch {
      // silent
    }
    setRenamingId(null);
  };

  // -- Delete -----------------------------------------------------------------
  const startDelete = (convId: string) => {
    setMenuConvId(null);
    setDeletingId(convId);
  };

  const confirmDelete = async () => {
    if (!deletingId) return;
    try {
      await api.deleteConversation(deletingId);
      setConversations((prev) => prev.filter((c) => c.id !== deletingId));
      setTotalCount((n) => n - 1);
      // If viewing the deleted conversation, redirect
      if (typeof window !== "undefined") {
        const currentConvId = new URLSearchParams(window.location.search).get("c");
        if (currentConvId === deletingId) {
          router.push("/chat?new=" + Date.now());
        }
      }
    } catch {
      // silent
    }
    setDeletingId(null);
  };

  // -- Export -----------------------------------------------------------------
  const handleExport = async (convId: string) => {
    setMenuConvId(null);
    try {
      const data = await api.exportConversation(convId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `conversation-${convId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // silent
    }
  };

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
        {navItems.map(({ href, labelKey, icon: Icon }) => {
          // Active when current path equals href OR is a sub-route (e.g.
          // /missions/<id> should highlight the "Missions" entry).
          // Use "/" as boundary to avoid /chat-foo matching /chat.
          const isActive =
            pathname === href ||
            pathname.startsWith(href + "/") ||
            pathname.startsWith(href + "?");
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
              <span className="hidden lg:block">{t(labelKey)}</span>
            </Link>
          );
        })}

        {/* New conversation button */}
        <button
          onClick={() => router.push("/chat?new=" + Date.now())}
          className="hidden lg:flex items-center gap-3 px-3 py-2 rounded-md text-xs text-text-muted hover:text-cyber-cyan hover:bg-cyber-cyan/5 border border-dashed border-border-dim hover:border-cyber-cyan/30 transition-all mt-1 w-full"
        >
          <Plus className="w-3.5 h-3.5 shrink-0" />
          <span>{t("newConversation")}</span>
        </button>
      </nav>

      {/* Recent conversations */}
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
          <>
            {/* Search bar */}
            <div className="px-2 pb-1 shrink-0">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-text-muted pointer-events-none" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => handleSearchChange(e.target.value)}
                  placeholder={t("searchPlaceholder")}
                  className="w-full pl-7 pr-7 py-1 text-xs bg-bg-tertiary border border-border-dim rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/30 transition-colors"
                />
                {searchQuery && (
                  <button
                    onClick={() => { setSearchQuery(""); fetchConversations({ query: "" }); }}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            </div>

            {/* Conversation list */}
            <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0">
              {conversations.length === 0 && (
                <p className="text-[10px] text-text-muted px-2 py-3 text-center">{t("noResults")}</p>
              )}

              {conversations.map((conv) => {
                const isActive = pathname === `/chat` && typeof window !== "undefined" &&
                  new URLSearchParams(window.location.search).get("c") === conv.id;

                // Inline rename mode
                if (renamingId === conv.id) {
                  return (
                    <div key={conv.id} className="px-1 py-1">
                      <input
                        ref={renameInputRef}
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onBlur={commitRename}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitRename();
                          if (e.key === "Escape") setRenamingId(null);
                        }}
                        className="w-full px-2 py-1 text-xs bg-bg-tertiary border border-cyber-cyan/30 rounded text-text-primary focus:outline-none"
                        autoFocus
                      />
                    </div>
                  );
                }

                return (
                  <div
                    key={conv.id}
                    className={`group flex items-center gap-1 px-2 py-1.5 text-xs transition-all border-y ${
                      isActive
                        ? "bg-cyber-cyan/10 text-cyber-cyan border-cyber-cyan/20"
                        : "text-text-muted border-transparent hover:text-cyber-cyan hover:bg-cyber-cyan/10 hover:border-cyber-cyan/20"
                    }`}
                    onContextMenu={(e) => openMenu(e, conv.id)}
                  >
                    <Link
                      href={`/chat?c=${conv.id}`}
                      className="flex-1 truncate"
                      title={conv.title}
                    >
                      {conv.title}
                    </Link>
                    <button
                      onClick={(e) => openMenu(e, conv.id)}
                      className="shrink-0 opacity-0 group-hover:opacity-100 text-text-muted hover:text-text-secondary transition-opacity"
                    >
                      <MoreHorizontal className="w-3.5 h-3.5" />
                    </button>
                  </div>
                );
              })}

              {/* Load more */}
              {hasMore && (
                <button
                  onClick={loadMore}
                  className="flex items-center justify-center gap-1 w-full px-2 py-1.5 text-[10px] text-text-muted hover:text-cyber-cyan transition-colors"
                >
                  <ChevronDown className="w-3 h-3" />
                  <span>{t("loadMore")}</span>
                </button>
              )}
            </div>
          </>
        )}
      </div>

      {/* Context menu (floating) */}
      {menuConvId && (
        <div
          ref={menuRef}
          className="fixed z-50 bg-bg-secondary border border-border-dim rounded-md shadow-lg py-1 min-w-[140px]"
          style={{ left: menuPos.x, top: menuPos.y }}
        >
          <button
            onClick={() => startRename(conversations.find((c) => c.id === menuConvId)!)}
            className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-tertiary hover:text-text-primary transition-colors"
          >
            <Pencil className="w-3 h-3" />
            {t("rename")}
          </button>
          <button
            onClick={() => handleExport(menuConvId!)}
            className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-tertiary hover:text-text-primary transition-colors"
          >
            <Download className="w-3 h-3" />
            {t("export")}
          </button>
          <button
            onClick={() => startDelete(menuConvId!)}
            className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-cyber-red hover:bg-cyber-red/5 transition-colors"
          >
            <Trash2 className="w-3 h-3" />
            {t("delete")}
          </button>
        </div>
      )}

      {/* Delete confirmation modal */}
      {deletingId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 max-w-xs shadow-xl">
            <p className="text-sm text-text-primary mb-4">{t("confirmDelete")}</p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setDeletingId(null)}
                className="px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary bg-bg-tertiary rounded transition-colors"
              >
                Annuler
              </button>
              <button
                onClick={confirmDelete}
                className="px-3 py-1.5 text-xs text-white bg-cyber-red/80 hover:bg-cyber-red rounded transition-colors"
              >
                {t("delete")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Logout */}
      <div className="p-2 border-t border-border-dim shrink-0 mt-auto">
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-text-secondary hover:text-cyber-red hover:bg-cyber-red/5 transition-all w-full"
        >
          <LogOut className="w-4 h-4 shrink-0" />
          <span className="hidden lg:block">{t("logout")}</span>
        </button>
      </div>
    </aside>
  );
}
