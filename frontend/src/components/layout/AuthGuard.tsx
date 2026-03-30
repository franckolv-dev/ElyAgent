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
