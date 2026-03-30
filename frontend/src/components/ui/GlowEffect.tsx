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
