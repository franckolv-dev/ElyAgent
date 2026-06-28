"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/AuthGuard.tsx
 * @brief      Auth guard — route protection for authenticated users
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *            https://www.elastic.co/licensing/elastic-license
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { isAuthenticated, isAdmin } from "@/lib/auth";

function Checking() {
  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="text-cyber-cyan animate-pulse-slow text-sm">Verifying access...</div>
    </div>
  );
}

/** Redirige vers /login si non authentifié. */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
    } else {
      setChecked(true);
    }
  }, [router]);

  if (!checked) return <Checking />;
  return <>{children}</>;
}

/** Redirige vers /chat si non authentifié ou non admin. */
export function AdminGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
    } else if (!isAdmin()) {
      router.replace("/chat");
    } else {
      setChecked(true);
    }
  }, [router]);

  if (!checked) return <Checking />;
  return <>{children}</>;
}
