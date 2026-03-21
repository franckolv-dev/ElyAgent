"use client";

import { Suspense } from "react";
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
      {/* Three.js canvas */}
      <Suspense fallback={<div className="w-full h-full bg-[#060c16]" />}>
        <AvatarScene state={state} />
      </Suspense>

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
