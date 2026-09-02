/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/nav.ts
 * @brief      Inventaire des liens de la barre laterale.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 */

/**
 * ⚠️ POURQUOI CE FICHIER (02/09/2026) : la liste vivait dans `Sidebar.tsx`, un
 * composant client qui tire next/navigation, next-intl et les helpers d'auth.
 * Impossible de la relire dans un test sans monter tout ce decor, donc rien ne
 * verifiait qu'une page livree y figure. Deux routes (`/arena`, `/avatar-test`)
 * ont derive hors de la navigation sans que rien ne le signale. La nav est une
 * DONNEE : elle est sortie ici pour etre lisible par `__tests__/nav.test.ts`.
 */
import {
  MessageSquare, LayoutDashboard, Settings, Shield, ShieldCheck,
  Clock, Search, BookOpen, Target, Brain, Compass,
  Sparkles, ClipboardCheck, Stethoscope, Undo2, BrainCircuit, Swords, Eye,
  type LucideIcon,
} from "lucide-react";

export type NavLeaf = { href: string; labelKey: string; icon: LucideIcon; admin?: boolean };
export type NavGroup = { groupKey: string; labelKey: string; icon: LucideIcon; admin?: boolean; children: NavLeaf[] };
export type NavEntry = NavLeaf | NavGroup;

export const isGroup = (e: NavEntry): e is NavGroup => "children" in e;

// Sidebar nav (refonte 2026-06-04) — flat top-level + collapsible accordion
// groups, so the list stays short and "Admin" is reachable without scrolling.
// Candidates moved to /me/learning/* (was 404ing under the backend-owned
// /admin/learning/* namespace — see that page's header).
// Arena rebranchee le 02/09/2026 : retiree en juin comme « inutilisee » alors
// qu'elle fonctionnait (6 matchs et 3 lignes de classement en base). La page et
// sa cle `navArena` etaient restees, sans aucun lien pour y mener.
// Elle est HORS du groupe Admin, et c'est volontaire : `routers/arena.py` ne
// demande qu'un utilisateur connecte sur ses cinq routes, le match part du
// prompt de l'appelant, `record_vote` refuse le vote d'un tiers (403) et
// l'historique est filtre par `user_id`. Aucune route ne change un reglage
// d'instance, et le classement ELO n'est lu nulle part ailleurs dans le
// backend. C'est un outil PERSONNEL : le mettre sous Admin le laissait
// injoignable pour tout le monde sauf l'administrateur — le defaut d'origine a
// moitie corrige (relecture 02/09/2026).
export const NAV: NavEntry[] = [
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
      { href: "/me/memories", labelKey: "navMemories", icon: BrainCircuit },
      { href: "/me/reversible-actions", labelKey: "navReversibleActions", icon: Undo2 },
      // Contrat visible + registre de sortie (02/09/2026). HORS du groupe
      // ADMINISTRATEUR, et c'est le point : `routers/transparency.py` ne
      // demande qu'un utilisateur connecte, tout y est scope a l'appelant, et
      // c'est A LUI que la question s'adresse — « qu'est-ce qu'Ely a le droit
      // de faire POUR MOI ». Sous Admin, la reponse serait injoignable par
      // celui qui la pose.
      { href: "/transparence", labelKey: "navTransparency", icon: Eye },
      { href: "/arena",     labelKey: "navArena",     icon: Swords },
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
