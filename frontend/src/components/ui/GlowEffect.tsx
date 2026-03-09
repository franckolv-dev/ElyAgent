"use client";

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
      <div className="absolute inset-0 bg-gradient-to-r from-cyber-green/20 via-cyber-cyan/20 to-cyber-green/20 rounded-lg" />
      <div className="relative bg-bg-card rounded-lg">{children}</div>
    </div>
  );
}
