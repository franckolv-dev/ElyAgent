"use client";

import { Component, Suspense, type ReactNode } from "react";
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
export function CyberpunkAvatar({
  state = "idle",
  className = "",
  minimal = false,    // hides HUD overlays — use for logo / small thumbnails
}: {
  state?: AvatarState;
  className?: string;
  minimal?: boolean;
}) {
  const color = HUD_COLOR[state];

  return (
    <div
      className={`relative bg-[#060c16] overflow-hidden rounded-lg ${className}`}
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
            style={{ color, opacity: 0.45 }}
          >
            NEURAL:98.3%
            <br />
            SYNC:99.72
          </div>

          <div
            className="absolute top-2 right-2.5 text-right text-[9px] leading-tight"
            style={{ color, opacity: 0.45 }}
          >
            LAT:12ms
            <br />
            VER:3.0.0
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
            ELY :: {LABEL[state]}
          </div>
        </div>
      )}
    </div>
  );
}
