"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/avatar/CyberpunkAvatar.tsx
 * @brief      Cyberpunk avatar — animated 3D character mesh
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
 *   - AUTORISÉ : Modification et redistribution avec attribution.
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */

import { Component, Suspense, useEffect, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";

export type AvatarState = "idle" | "thinking" | "speaking" | "alert" | "listening";

// ── Dynamic import of Three.js scene (no SSR) ──────────────────────────────
const AvatarScene = dynamic(
  () => import("./AvatarScene").then((m) => m.AvatarScene),
  { ssr: false, loading: () => <div className="w-full h-full bg-[#060c16]" /> },
);

// ── Color palette for HUD elements ─────────────────────────────────────────
const HUD_COLOR: Record<AvatarState, string> = {
  idle:      "#00d2ff",
  thinking:  "#aa00ff",
  speaking:  "#00ff5a",
  alert:     "#ff1e37",
  listening: "#ffd200",
};

const LABEL: Record<AvatarState, string> = {
  idle:      "IDLE",
  thinking:  "PROCESSING",
  speaking:  "SPEAKING",
  alert:     "ALERT",
  listening: "LISTENING",
};

// ── WebGL error boundary — shows a CSS fallback when GPU is unavailable ─────
class WebGLErrorBoundary extends Component<
  { color: string; label: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }

  render() {
    if (this.state.failed) {
      const { color, label } = this.props;
      return (
        <div className="w-full h-full flex flex-col items-center justify-center bg-[#060c16]">
          {/* CSS wireframe fallback — concentric hexagons */}
          <div className="relative w-24 h-24 mb-3">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="absolute inset-0 rounded-full border animate-pulse"
                style={{
                  borderColor: `${color}${["66", "44", "22"][i]}`,
                  transform: `scale(${1 - i * 0.22})`,
                  animationDelay: `${i * 0.4}s`,
                }}
              />
            ))}
            <div
              className="absolute inset-0 flex items-center justify-center text-[10px] font-mono"
              style={{ color }}
            >
              ELY
            </div>
          </div>
          <p className="text-[9px] font-mono opacity-40" style={{ color }}>
            WebGL indisponible
          </p>
          <p className="text-[8px] font-mono opacity-25 mt-0.5" style={{ color }}>
            {label}
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── Main exported component ─────────────────────────────────────────────────
interface CyberpunkAvatarProps {
  state?: AvatarState;
  className?: string;
  minimal?: boolean;
  latencyMs?: number;       // real WebSocket latency (ms), undefined before first response
  syncPercent?: number;     // success rate over last 10 messages (0-100)
  neuralScore?: number;     // model capability tier (0-100), undefined before first model known
  version?: string;         // backend version from /health
}

// ── Tagline cycling for idle state ─────────────────────────────────────────
const IDLE_LABELS = ["IDLE", "EXACTLY LIKE YOU"];
const IDLE_CYCLE_MS = 3200;

export function CyberpunkAvatar({
  state = "idle",
  className = "",
  minimal = false,
  latencyMs,
  syncPercent,
  neuralScore,
  version,
}: CyberpunkAvatarProps) {
  const color = HUD_COLOR[state];

  // Cycle the bottom label between "IDLE" and "EXACTLY LIKE YOU" when idle
  const [idleLabelIdx, setIdleLabelIdx] = useState(0);
  useEffect(() => {
    if (state !== "idle") return;
    const timer = setInterval(
      () => setIdleLabelIdx((i) => (i + 1) % IDLE_LABELS.length),
      IDLE_CYCLE_MS,
    );
    return () => clearInterval(timer);
  }, [state]);

  return (
    <div
      className={`relative bg-[#060c16] border border-cyber-cyan/10 overflow-hidden rounded-lg shadow-[0_0_24px_rgba(0,210,255,0.08)] ${className}`}
      style={{ minHeight: minimal ? 0 : 280 }}
    >
      {/* Three.js canvas — with WebGL error boundary */}
      <WebGLErrorBoundary color={color} label={LABEL[state]}>
        <Suspense fallback={<div className="w-full h-full bg-[#060c16]" />}>
          <AvatarScene state={state} />
        </Suspense>
      </WebGLErrorBoundary>

      {/* HUD overlay — hidden in minimal mode */}
      {!minimal && (
        <div
          className="absolute inset-0 pointer-events-none select-none"
          style={{ fontFamily: "monospace" }}
        >
          <div
            className="absolute top-2 left-2.5 text-[9px] leading-tight"
            style={{ color, opacity: 0.75, textShadow: `0 0 8px ${color}88` }}
          >
            NEURAL:{neuralScore !== undefined ? `${neuralScore.toFixed(1)}%` : "—"}
            <br />
            SYNC:{syncPercent !== undefined ? `${syncPercent.toFixed(1)}%` : "—"}
          </div>

          <div
            className="absolute top-2 right-2.5 text-right text-[9px] leading-tight"
            style={{ color, opacity: 0.75, textShadow: `0 0 8px ${color}88` }}
          >
            LAT:{latencyMs !== undefined ? `${latencyMs}ms` : "—"}
            <br />
            VER:{version ?? "…"}
          </div>

          <div
            className="absolute bottom-2.5 left-1/2 -translate-x-1/2 px-5 py-1 text-center text-[10px] tracking-wider border rounded-sm"
            style={{
              borderColor: `${color}55`,
              color,
              opacity: 0.9,
              background: "rgba(6,12,22,0.85)",
            }}
          >
            ELY :: {state === "idle" ? IDLE_LABELS[idleLabelIdx] : LABEL[state]}
          </div>
        </div>
      )}
    </div>
  );
}
