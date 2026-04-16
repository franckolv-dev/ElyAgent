"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/AuthGuard.tsx
 * @brief      Auth guard — route protection for authenticated users
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
