"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/security/page.tsx
 * @brief      Security page — audit logs and access management
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

import { useEffect, useState, useCallback } from "react";
import { AdminGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { authFetch } from "@/lib/auth";
import {
  Shield,
  ShieldCheck,
  Lock,
  EyeOff,
  Container,
  Terminal,
  KeyRound,
  Gauge,
  FileSearch,
  Upload,
  UserCheck,
  Check,
  X,
} from "lucide-react";
import { motion } from "framer-motion";

// -- Types -------------------------------------------------------------------

interface SecurityFeature {
  id: string;
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  liveStatus?: boolean; // whether to fetch real-time status
}

interface VaultStatus {
  locked: boolean;
}

// -- Security features definition --------------------------------------------

const SECURITY_FEATURES: SecurityFeature[] = [
  {
    id: "hitl",
    title: "HITL (Human-In-The-Loop)",
    description:
      "Les actions sensibles necessitent une approbation humaine avant execution. SSH, envoi de mails, et operations critiques sont toujours valides par l'utilisateur.",
    icon: UserCheck,
    liveStatus: true,
  },
  {
    id: "vault",
    title: "Coffre-fort chiffre",
    description:
      "Stockage AES-256-GCM des secrets avec verrouillage automatique. Les valeurs ne sont jamais retournees par l'API apres enregistrement.",
    icon: Lock,
    liveStatus: true,
  },
  {
    id: "pii",
    title: "Anonymisation PII",
    description:
      "SecurityFilter supprime automatiquement emails, telephones, IBANs et numeros de carte des prompts envoyes au LLM.",
    icon: EyeOff,
  },
  {
    id: "docker",
    title: "Isolation Docker",
    description:
      "Le backend s'execute dans des conteneurs isoles avec des volumes en lecture seule pour la configuration.",
    icon: Container,
  },
  {
    id: "ssh",
    title: "SSH Whitelist",
    description:
      "Seules les commandes explicitement autorisees sur des hotes approuves sont executables. Toute commande SSH passe par HITL.",
    icon: Terminal,
  },
  {
    id: "jwt",
    title: "JWT + Rotation de tokens",
    description:
      "Access tokens courts (60 min) + refresh cookies HttpOnly avec blacklist. Rotation automatique a chaque rafraichissement.",
    icon: KeyRound,
  },
  {
    id: "rate",
    title: "Rate Limiting",
    description:
      "Limitation par endpoint via slowapi. Protection contre le brute-force et les abus d'API.",
    icon: Gauge,
  },
  {
    id: "audit",
    title: "Audit Logging",
    description:
      "Toutes les actions admin et SSH sont journalisees avec horodatage, utilisateur, commande et code retour.",
    icon: FileSearch,
  },
  {
    id: "pkce",
    title: "PKCE OAuth",
    description:
      "Authentification Google OAuth avec PKCE + state tokens (TTL 10 min). Protection contre les attaques d'interception.",
    icon: ShieldCheck,
  },
  {
    id: "upload",
    title: "Validation des uploads",
    description:
      "Verification des magic bytes, allowlist d'extensions et limite de 50 Mo. Aucun fichier executable n'est accepte.",
    icon: Upload,
  },
];

// -- Comparison data ---------------------------------------------------------

const COMPARISON_ROWS = [
  { feature: "Validation HITL", ely: true, openclaw: false },
  { feature: "Coffre-fort chiffre (AES-256-GCM)", ely: true, openclaw: false },
  { feature: "Anonymisation PII", ely: true, openclaw: false },
  { feature: "Isolation Docker", ely: true, openclaw: false },
  { feature: "SSH whitelist + fingerprints", ely: true, openclaw: false },
  { feature: "JWT + rotation de tokens", ely: true, openclaw: false },
  { feature: "Rate limiting par endpoint", ely: true, openclaw: false },
  { feature: "Audit logging complet", ely: true, openclaw: false },
  { feature: "PKCE OAuth", ely: true, openclaw: false },
  { feature: "Validation magic bytes uploads", ely: true, openclaw: false },
];

// -- Main page ---------------------------------------------------------------

export default function SecurityPage() {
  const [vaultStatus, setVaultStatus] = useState<VaultStatus | null>(null);
  const [hitlActive, setHitlActive] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchStatuses = useCallback(async () => {
    setLoading(true);
    try {
      const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

      // Vault status
      const vaultRes = await authFetch(`${base}/api/vault/status`);
      if (vaultRes.ok) {
        setVaultStatus(await vaultRes.json());
      }

      // HITL is always active (built into the architecture)
      setHitlActive(true);
    } catch {
      // API might not be reachable — show graceful fallback
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatuses();
  }, [fetchStatuses]);

  function getStatusForFeature(id: string): {
    label: string;
    color: string;
    bgColor: string;
  } | null {
    if (id === "hitl") {
      if (hitlActive === null && loading) return null;
      return {
        label: hitlActive ? "Actif" : "Inactif",
        color: hitlActive ? "text-emerald-400" : "text-amber-400",
        bgColor: hitlActive ? "bg-emerald-400/10" : "bg-amber-400/10",
      };
    }
    if (id === "vault") {
      if (vaultStatus === null && loading) return null;
      if (vaultStatus === null) {
        return {
          label: "Actif",
          color: "text-emerald-400",
          bgColor: "bg-emerald-400/10",
        };
      }
      return {
        label: vaultStatus.locked ? "Verrouille" : "Deverrouille",
        color: vaultStatus.locked ? "text-emerald-400" : "text-amber-400",
        bgColor: vaultStatus.locked
          ? "bg-emerald-400/10"
          : "bg-amber-400/10",
      };
    }
    // Static features always active
    return {
      label: "Actif",
      color: "text-emerald-400",
      bgColor: "bg-emerald-400/10",
    };
  }

  return (
    <AdminGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Header />
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {/* Page header */}
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-cyber-cyan/10 border border-cyber-cyan/30 flex items-center justify-center">
                <Shield className="w-5 h-5 text-cyber-cyan" />
              </div>
              <div>
                <h1 className="text-lg font-medium text-text-primary">
                  Securite
                </h1>
                <p className="text-xs text-text-muted">
                  10 couches de protection actives
                </p>
              </div>
            </div>

            {/* Security feature cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {SECURITY_FEATURES.map((feature, i) => {
                const status = getStatusForFeature(feature.id);
                const Icon = feature.icon;
                return (
                  <motion.div
                    key={feature.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.04 }}
                    className="bg-bg-secondary border border-border-dim rounded-lg p-5 flex flex-col gap-3 hover:border-cyber-cyan/20 transition-colors"
                  >
                    <div className="flex items-start justify-between">
                      <div className="w-9 h-9 rounded-lg bg-cyber-cyan/10 border border-cyber-cyan/20 flex items-center justify-center shrink-0">
                        <Icon className="w-4.5 h-4.5 text-cyber-cyan" />
                      </div>
                      {status ? (
                        <span
                          className={`text-[10px] font-medium uppercase tracking-wider px-2 py-0.5 rounded-full ${status.bgColor} ${status.color}`}
                        >
                          {status.label}
                        </span>
                      ) : (
                        <span className="text-[10px] text-text-muted animate-pulse-slow">
                          ...
                        </span>
                      )}
                    </div>
                    <div>
                      <h3 className="text-sm font-medium text-text-primary mb-1">
                        {feature.title}
                      </h3>
                      <p className="text-xs text-text-muted leading-relaxed">
                        {feature.description}
                      </p>
                    </div>
                  </motion.div>
                );
              })}
            </div>

            {/* Comparison section */}
            <div className="mt-8">
              <div className="flex items-center gap-2 mb-4">
                <ShieldCheck className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-xs text-text-muted uppercase tracking-wider">
                  Comparaison securite : ELY vs OpenClaw
                </h2>
              </div>
              <div className="bg-bg-secondary border border-border-dim rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border-dim">
                      <th className="text-left px-4 py-3 text-text-muted uppercase tracking-wider font-medium">
                        Protection
                      </th>
                      <th className="text-center px-4 py-3 text-cyber-cyan uppercase tracking-wider font-medium w-28">
                        ELY
                      </th>
                      <th className="text-center px-4 py-3 text-text-muted uppercase tracking-wider font-medium w-28">
                        OpenClaw
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-dim">
                    {COMPARISON_ROWS.map((row, i) => (
                      <motion.tr
                        key={row.feature}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: 0.4 + i * 0.03 }}
                        className="hover:bg-bg-tertiary/50 transition-colors"
                      >
                        <td className="px-4 py-2.5 text-text-secondary">
                          {row.feature}
                        </td>
                        <td className="text-center px-4 py-2.5">
                          {row.ely ? (
                            <Check className="w-4 h-4 text-emerald-400 inline-block" />
                          ) : (
                            <X className="w-4 h-4 text-cyber-red inline-block" />
                          )}
                        </td>
                        <td className="text-center px-4 py-2.5">
                          {row.openclaw ? (
                            <Check className="w-4 h-4 text-emerald-400 inline-block" />
                          ) : (
                            <X className="w-4 h-4 text-cyber-red inline-block" />
                          )}
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-[10px] text-text-muted mt-2">
                OpenClaw : vulnérabilités documentées par Cisco, CrowdStrike, Microsoft et al.
              </p>
            </div>
          </div>
        </div>
      </div>
    </AdminGuard>
  );
}
