"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/security/page.tsx
 * @brief      Security page — audit logs and access management
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */

import { useEffect, useState, useCallback } from "react";
import { useTranslations } from "next-intl";
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
} from "lucide-react";
import { motion } from "framer-motion";

// -- Types -------------------------------------------------------------------

interface SecurityFeature {
  id: string;
  titleKey: string;
  descriptionKey: string;
  icon: React.ComponentType<{ className?: string }>;
  liveStatus?: boolean; // whether to fetch real-time status
}

interface VaultStatus {
  locked: boolean;
}

// -- Security features definition --------------------------------------------

const SECURITY_FEATURES: SecurityFeature[] = [
  { id: "hitl",   titleKey: "features.hitlTitle",   descriptionKey: "features.hitlDescription",   icon: UserCheck,   liveStatus: true },
  { id: "vault",  titleKey: "features.vaultTitle",  descriptionKey: "features.vaultDescription",  icon: Lock,        liveStatus: true },
  { id: "pii",    titleKey: "features.piiTitle",    descriptionKey: "features.piiDescription",    icon: EyeOff },
  { id: "docker", titleKey: "features.dockerTitle", descriptionKey: "features.dockerDescription", icon: Container },
  { id: "ssh",    titleKey: "features.sshTitle",    descriptionKey: "features.sshDescription",    icon: Terminal },
  { id: "jwt",    titleKey: "features.jwtTitle",    descriptionKey: "features.jwtDescription",    icon: KeyRound },
  { id: "rate",   titleKey: "features.rateTitle",   descriptionKey: "features.rateDescription",   icon: Gauge },
  { id: "audit",  titleKey: "features.auditTitle",  descriptionKey: "features.auditDescription",  icon: FileSearch },
  { id: "pkce",   titleKey: "features.pkceTitle",   descriptionKey: "features.pkceDescription",   icon: ShieldCheck },
  { id: "upload", titleKey: "features.uploadTitle", descriptionKey: "features.uploadDescription", icon: Upload },
];

// -- Main page ---------------------------------------------------------------

export default function SecurityPage() {
  const t = useTranslations("security");
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
        label: hitlActive ? t("statusActive") : t("statusInactive"),
        color: hitlActive ? "text-emerald-400" : "text-amber-400",
        bgColor: hitlActive ? "bg-emerald-400/10" : "bg-amber-400/10",
      };
    }
    if (id === "vault") {
      if (vaultStatus === null && loading) return null;
      if (vaultStatus === null) {
        return {
          label: t("statusActive"),
          color: "text-emerald-400",
          bgColor: "bg-emerald-400/10",
        };
      }
      return {
        label: vaultStatus.locked ? t("statusLocked") : t("statusUnlocked"),
        color: vaultStatus.locked ? "text-emerald-400" : "text-amber-400",
        bgColor: vaultStatus.locked
          ? "bg-emerald-400/10"
          : "bg-amber-400/10",
      };
    }
    // Static features always active
    return {
      label: t("statusActive"),
      color: "text-emerald-400",
      bgColor: "bg-emerald-400/10",
    };
  }

  return (
    <AdminGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto p-6 space-y-6" style={{ background: "var(--bg-app)" }}>
            {/* Page header */}
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-cyber-cyan/10 border border-cyber-cyan/30 flex items-center justify-center">
                <Shield className="w-5 h-5 text-cyber-cyan" />
              </div>
              <div>
                <h1 className="text-lg font-medium text-text-primary">
                  {t("pageTitle")}
                </h1>
                <p className="text-xs text-text-muted">
                  {t("subtitle")}
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
                        {t(feature.titleKey)}
                      </h3>
                      <p className="text-xs text-text-muted leading-relaxed">
                        {t(feature.descriptionKey)}
                      </p>
                    </div>
                  </motion.div>
                );
              })}
            </div>

          </main>
        </div>
        </div>
      </div>
    </AdminGuard>
  );
}
