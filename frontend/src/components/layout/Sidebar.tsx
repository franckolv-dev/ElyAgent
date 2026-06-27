"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/Sidebar.tsx
 * @brief      Sidebar — navigation menu and conversation history (refonte mai 2026)
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  MessageSquare, LayoutDashboard, Settings, Shield, ShieldCheck, LogOut,
  Plus, Clock, Search, MoreHorizontal, Pencil, Trash2,
  Download, X, ChevronDown, BookOpen, Target, Brain, Compass,
  Sparkles, ClipboardCheck, Stethoscope, Undo2, type LucideIcon,
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

type NavLeaf = { href: string; labelKey: string; icon: LucideIcon; admin?: boolean };
type NavGroup = { groupKey: string; labelKey: string; icon: LucideIcon; admin?: boolean; children: NavLeaf[] };
type NavEntry = NavLeaf | NavGroup;

const isGroup = (e: NavEntry): e is NavGroup => "children" in e;

// Sidebar nav (refonte 2026-06-04) — flat top-level + collapsible accordion
// groups, so the list stays short and "Admin" is reachable without scrolling.
// Arena dropped (unused). Candidates moved to /me/learning/* (was 404ing under
// the backend-owned /admin/learning/* namespace — see that page's header).
const NAV: NavEntry[] = [
  { href: "/chat",      labelKey: "navChat",      icon: MessageSquare },
  { href: "/missions",  labelKey: "navMissions",  icon: Target },
  { href: "/scheduled", labelKey: "navScheduled", icon: Clock },
  { href: "/knowledge", labelKey: "navKnowledge", icon: BookOpen },
  {
    groupKey: "skills", labelKey: "navGroupSkills", icon: Sparkles,
    children: [
      { href: "/me/learning",            labelKey: "navLearning",           icon: Brain },
      { href: "/me/learning/skills",     labelKey: "navLearningSkills",     icon: Sparkles },
      { href: "/me/learning/candidates", labelKey: "navLearningCandidates", icon: ClipboardCheck, admin: true },
      { href: "/me/learning/tool-gaps",  labelKey: "navLearningToolGaps",   icon: Search, admin: true },
      { href: "/me/learning/incidents",  labelKey: "navLearningIncidents",  icon: Stethoscope, admin: true },
    ],
  },
  {
    groupKey: "analysis", labelKey: "navGroupAnalysis", icon: LayoutDashboard,
    children: [
      { href: "/dashboard", labelKey: "navDashboard",  icon: LayoutDashboard },
      { href: "/me/state",  labelKey: "navUserState",  icon: Compass },
      { href: "/me/reversible-actions", labelKey: "navReversibleActions", icon: Undo2 },
    ],
  },
  { href: "/settings", labelKey: "navSettings", icon: Settings },
  {
    groupKey: "admin", labelKey: "navGroupAdmin", icon: Shield, admin: true,
    children: [
      { href: "/security", labelKey: "navSecurity", icon: ShieldCheck },
      { href: "/admin",    labelKey: "navAdmin",    icon: Shield },
    ],
  },
];

// Longest-prefix match so nested routes (e.g. /me/learning vs
// /me/learning/skills) highlight exactly one item.
function activeHrefFor(pathname: string, hrefs: string[]): string | null {
  let best: string | null = null;
  for (const h of hrefs) {
    if (pathname === h || pathname.startsWith(h + "/") || pathname.startsWith(h + "?")) {
      if (best === null || h.length > best.length) best = h;
    }
  }
  return best;
}

export function Sidebar() {
  const t        = useTranslations("sidebar");
  const pathname = usePathname();
  const router   = useRouter();
  const admin    = isAdmin();

  const [conversations, setConversations] = useState<RecentConv[]>([]);
  const [totalCount, setTotalCount]       = useState(0);
  const [expanded, setExpanded]           = useState(false);
  const [searchQuery, setSearchQuery]     = useState("");

  const [menuConvId, setMenuConvId]   = useState<string | null>(null);
  const [menuPos, setMenuPos]         = useState({ x: 0, y: 0 });
  const menuRef = useRef<HTMLDivElement>(null);

  const [renamingId, setRenamingId]       = useState<string | null>(null);
  const [renameValue, setRenameValue]     = useState("");
  const renameInputRef = useRef<HTMLInputElement>(null);

  const [deletingId, setDeletingId] = useState<string | null>(null);

  // ── Mobile drawer state ──
  // Synced with Header via window CustomEvents (zero-dependency cross-component messaging).
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(() => {
    const toggle = () => setMobileOpen((v) => !v);
    const close = () => setMobileOpen(false);
    window.addEventListener("ely-toggle-mobile-nav", toggle);
    window.addEventListener("ely-close-mobile-nav", close);
    return () => {
      window.removeEventListener("ely-toggle-mobile-nav", toggle);
      window.removeEventListener("ely-close-mobile-nav", close);
    };
  }, []);
  // Close the drawer whenever the route changes — so tapping a nav item
  // navigates AND collapses the sidebar in a single user action.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Accordion open-state: undefined = follow the active child (auto-open the
  // group you're currently in); true/false = explicit user toggle.
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  const allHrefs = NAV.flatMap((e) => (isGroup(e) ? e.children.map((c) => c.href) : [e.href]));
  const activeHref = activeHrefFor(pathname, allHrefs);

  // ── Conversations fetching ──
  const fetchConversations = useCallback(async (opts: { offset?: number; query?: string; reset?: boolean } = {}) => {
    const offset = opts.offset ?? 0;
    const query = opts.query ?? searchQuery;
    try {
      const data = (await api.getConversations({
        limit: PAGE_SIZE, offset, q: query,
      })) as { conversations: RecentConv[]; total_count: number };
      const items = data.conversations || [];
      setTotalCount(data.total_count || 0);
      setConversations((prev) =>
        opts.reset || offset === 0 ? items : [...prev, ...items]
      );
    } catch {
      // silent — keep existing list
    }
  }, [searchQuery]);

  useEffect(() => { fetchConversations({ offset: 0, reset: true }); }, [fetchConversations]);

  const hasMore = conversations.length < totalCount;
  const loadMore = () => fetchConversations({ offset: conversations.length });

  const handleSearchChange = (val: string) => {
    setSearchQuery(val);
    fetchConversations({ offset: 0, query: val, reset: true });
  };

  // ── Context menu ──
  const openMenu = (e: React.MouseEvent, convId: string) => {
    e.preventDefault();
    setMenuConvId(convId);
    setMenuPos({ x: e.clientX, y: e.clientY });
  };

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuConvId(null);
    };
    if (menuConvId) document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuConvId]);

  // ── Rename ──
  const startRename = (conv: RecentConv) => {
    setMenuConvId(null);
    setRenamingId(conv.id);
    setRenameValue(conv.title);
    setTimeout(() => renameInputRef.current?.focus(), 50);
  };

  const commitRename = async () => {
    if (!renamingId) return;
    const newTitle = renameValue.trim();
    if (!newTitle) { setRenamingId(null); return; }
    try {
      await api.renameConversation(renamingId, newTitle);
      setConversations((cs) =>
        cs.map((c) => (c.id === renamingId ? { ...c, title: newTitle } : c))
      );
    } catch {
      // silent
    }
    setRenamingId(null);
  };

  // ── Delete ──
  const startDelete = (convId: string) => {
    setMenuConvId(null);
    setDeletingId(convId);
  };

  const confirmDelete = async () => {
    if (!deletingId) return;
    try {
      await api.deleteConversation(deletingId);
      setConversations((cs) => cs.filter((c) => c.id !== deletingId));
      setTotalCount((n) => Math.max(0, n - 1));
    } catch {
      // silent
    }
    setDeletingId(null);
  };

  // ── Export ──
  const handleExport = async (convId: string) => {
    setMenuConvId(null);
    try {
      const blob = await api.exportConversation(convId);
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
    <>
      {/* Mobile backdrop — clic anywhere to close the drawer */}
      <div
        className={`mobile-nav-backdrop ${mobileOpen ? "visible" : ""}`}
        onClick={() => setMobileOpen(false)}
        aria-hidden="true"
      />
      <aside className={`sidebar ${mobileOpen ? "mobile-open" : ""}`}>
      {/* Main nav — flat items + collapsible accordion groups */}
      <nav className="nav">
        {NAV.map((entry) => {
          // ── Accordion group ──
          if (isGroup(entry)) {
            if (entry.admin && !admin) return null;
            const children = entry.children.filter((c) => !c.admin || admin);
            if (children.length === 0) return null;
            const hasActive = children.some((c) => c.href === activeHref);
            const open = openGroups[entry.groupKey] ?? hasActive;
            const GIcon = entry.icon;
            return (
              <div key={entry.groupKey}>
                <button
                  type="button"
                  className={`nav-item ${hasActive ? "active" : ""}`}
                  style={{ width: "100%" }}
                  aria-expanded={open}
                  onClick={() =>
                    setOpenGroups((s) => ({ ...s, [entry.groupKey]: !open }))
                  }
                >
                  <span className="nav-icon"><GIcon size={15} /></span>
                  <span style={{ flex: 1, textAlign: "left" }}>{t(entry.labelKey)}</span>
                  <ChevronDown
                    size={13}
                    style={{
                      transform: open ? "rotate(180deg)" : "none",
                      transition: "transform .15s",
                      opacity: 0.6,
                    }}
                  />
                </button>
                {open &&
                  children.map((c) => {
                    const CIcon = c.icon;
                    return (
                      <Link
                        key={c.href}
                        href={c.href}
                        className={`nav-item ${c.href === activeHref ? "active" : ""}`}
                        style={{ paddingLeft: 30 }}
                      >
                        <span className="nav-icon"><CIcon size={14} /></span>
                        <span>{t(c.labelKey)}</span>
                      </Link>
                    );
                  })}
              </div>
            );
          }
          // ── Flat leaf ──
          if (entry.admin && !admin) return null;
          const Icon = entry.icon;
          return (
            <Link
              key={entry.href}
              href={entry.href}
              className={`nav-item ${entry.href === activeHref ? "active" : ""}`}
            >
              <span className="nav-icon"><Icon size={15} /></span>
              <span>{t(entry.labelKey)}</span>
            </Link>
          );
        })}
      </nav>

      {/* New conversation CTA */}
      <button
        onClick={() => router.push("/chat?new=" + Date.now())}
        className="nav-cta"
      >
        <Plus size={14} />
        <span>{t("newConversation")}</span>
      </button>

      {/* Recent conversations section */}
      <div className="nav-section-label">
        <button
          onClick={() => setExpanded((v) => !v)}
          style={{ display: "flex", alignItems: "center", gap: 6, background: "transparent", border: "none", padding: 0, color: "inherit", font: "inherit", cursor: "pointer" }}
          title={t("recent")}
        >
          <Clock size={11} />
          <span>{t("recent")}</span>
        </button>
        <span style={{ opacity: 0.6 }}>{totalCount}</span>
      </div>

      {/* Search bar (only when expanded) */}
      {expanded && (
        <div style={{ padding: "0 12px 8px" }}>
          <div style={{ position: "relative" }}>
            <Search size={11} style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)", pointerEvents: "none" }} />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder={t("searchPlaceholder")}
              style={{
                width: "100%",
                paddingLeft: 26,
                paddingRight: 26,
                paddingTop: 5,
                paddingBottom: 5,
                fontSize: 11,
                background: "var(--bg-surface-2)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text-primary)",
                outline: "none",
              }}
            />
            {searchQuery && (
              <button
                onClick={() => { setSearchQuery(""); fetchConversations({ query: "", reset: true }); }}
                style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)", background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: 0 }}
              >
                <X size={11} />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Recent conversation list */}
      <div className="recent-list" style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {conversations.length === 0 && expanded && (
          <p style={{ fontSize: 10, color: "var(--text-muted)", padding: "12px", textAlign: "center" }}>
            {t("noResults")}
          </p>
        )}

        {conversations.slice(0, expanded ? conversations.length : 5).map((conv) => {
          const isActive = pathname === `/chat` && typeof window !== "undefined" &&
            new URLSearchParams(window.location.search).get("c") === conv.id;

          if (renamingId === conv.id) {
            return (
              <div key={conv.id} style={{ padding: "2px 8px" }}>
                <input
                  ref={renameInputRef}
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onBlur={commitRename}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitRename();
                    if (e.key === "Escape") setRenamingId(null);
                  }}
                  style={{
                    width: "100%",
                    padding: "4px 8px",
                    fontSize: 11,
                    background: "var(--bg-surface-2)",
                    border: "1px solid var(--accent)",
                    borderRadius: "var(--radius-sm)",
                    color: "var(--text-primary)",
                    outline: "none",
                  }}
                  autoFocus
                />
              </div>
            );
          }

          return (
            <div
              key={conv.id}
              className={`recent-item ${isActive ? "active" : ""}`}
              onContextMenu={(e) => openMenu(e, conv.id)}
              style={{ display: "flex", alignItems: "center", gap: 4, paddingRight: 4 }}
            >
              <Link
                href={`/chat?c=${conv.id}`}
                style={{ flex: 1, color: "inherit", textDecoration: "none", overflow: "hidden", textOverflow: "ellipsis" }}
                title={conv.title}
              >
                {conv.title}
              </Link>
              <button
                onClick={(e) => openMenu(e, conv.id)}
                className="icon-btn"
                style={{ width: 22, height: 22, opacity: 0.5 }}
                title={t("rename")}
              >
                <MoreHorizontal size={12} />
              </button>
            </div>
          );
        })}

        {expanded && hasMore && (
          <button
            onClick={loadMore}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 4,
              width: "100%",
              padding: "6px 12px",
              fontSize: 10,
              color: "var(--text-muted)",
              background: "transparent",
              border: "none",
              cursor: "pointer",
            }}
          >
            <ChevronDown size={11} />
            <span>{t("loadMore")}</span>
          </button>
        )}
      </div>

      {/* Context menu */}
      {menuConvId && (
        <div
          ref={menuRef}
          style={{
            position: "fixed",
            zIndex: 50,
            background: "var(--bg-surface)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--radius-md)",
            boxShadow: "var(--shadow-lg)",
            padding: "4px 0",
            minWidth: 140,
            left: menuPos.x,
            top: menuPos.y,
          }}
        >
          <button
            onClick={() => startRename(conversations.find((c) => c.id === menuConvId)!)}
            style={ctxBtnStyle}
          >
            <Pencil size={12} />
            {t("rename")}
          </button>
          <button onClick={() => handleExport(menuConvId!)} style={ctxBtnStyle}>
            <Download size={12} />
            {t("export")}
          </button>
          <button
            onClick={() => startDelete(menuConvId!)}
            style={{ ...ctxBtnStyle, color: "var(--danger)" }}
          >
            <Trash2 size={12} />
            {t("delete")}
          </button>
        </div>
      )}

      {/* Delete confirmation modal */}
      {deletingId && (
        <div
          style={{
            position: "fixed", inset: 0, zIndex: 50,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: "rgba(0,0,0,0.5)",
          }}
        >
          <div
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--radius-lg)",
              padding: 16,
              maxWidth: 320,
              boxShadow: "var(--shadow-lg)",
            }}
          >
            <p style={{ fontSize: 13, color: "var(--text-primary)", margin: 0, marginBottom: 16 }}>
              {t("confirmDelete")}
            </p>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button onClick={() => setDeletingId(null)} className="btn ghost">
                Annuler
              </button>
              <button onClick={confirmDelete} className="btn danger">
                {t("delete")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Footer logout */}
      <div className="sidebar-footer">
        <button onClick={handleLogout} className="logout-btn">
          <LogOut size={13} />
          <span>{t("logout")}</span>
        </button>
      </div>
    </aside>
    </>
  );
}

const ctxBtnStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  width: "100%",
  padding: "6px 12px",
  fontSize: 12,
  color: "var(--text-secondary)",
  background: "transparent",
  border: "none",
  cursor: "pointer",
  textAlign: "left",
};
