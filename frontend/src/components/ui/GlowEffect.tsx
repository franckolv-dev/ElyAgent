"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/ui/GlowEffect.tsx
 * @brief      Glow effect — cyberpunk neon glow UI decoration
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

import { motion } from "framer-motion";

export function GlowOrb({ className = "" }: { className?: string }) {
  return (
    <motion.div
      className={`absolute rounded-full blur-3xl opacity-20 ${className}`}
      animate={{
        scale: [1, 1.2, 1],
        opacity: [0.15, 0.25, 0.15],
      }}
      transition={{
        duration: 4,
        repeat: Infinity,
        ease: "easeInOut",
      }}
    />
  );
}

export function CyberBorder({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`relative p-[1px] rounded-lg overflow-hidden ${className}`}>
      <div className="absolute inset-0 bg-gradient-to-r from-cyber-cyan/20 via-cyber-blue/20 to-cyber-cyan/20 rounded-lg" />
      <div className="relative bg-bg-card rounded-lg">{children}</div>
    </div>
  );
}
