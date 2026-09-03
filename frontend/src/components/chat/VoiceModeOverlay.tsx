"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/chat/VoiceModeOverlay.tsx
 * @brief      Voice mode overlay — full-screen voice interaction UI
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 */

import { useEffect, useCallback } from "react";
import { Mic, Volume2, X, Loader2 } from "lucide-react";
import type { VoiceConversationState } from "@/hooks/useVoiceConversation";

interface VoiceModeOverlayProps {
  state: VoiceConversationState;
  onClose: () => void;
}

export function VoiceModeOverlay({ state, onClose }: VoiceModeOverlayProps) {
  // ── Escape to close ──────────────────────────────────────────────────────
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    },
    [onClose],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  // ── Mode-specific visuals ────────────────────────────────────────────────
  const modeConfig = {
    idle: {
      ringClass: "border-border-dim opacity-40",
      animClass: "",
      icon: <Mic className="w-10 h-10 text-text-muted" />,
      label: "Dis 'Eli' pour commencer",
      labelClass: "text-text-muted",
    },
    listening: {
      ringClass: "border-cyber-cyan shadow-[0_0_30px_rgba(0,229,255,0.3)]",
      animClass: "animate-voice-pulse",
      icon: <Mic className="w-10 h-10 text-cyber-cyan" />,
      label: "Ecoute...",
      labelClass: "text-cyber-cyan",
    },
    processing: {
      ringClass: "border-amber-400 shadow-[0_0_30px_rgba(251,191,36,0.3)]",
      animClass: "animate-voice-rotate",
      icon: <Loader2 className="w-10 h-10 text-amber-400 animate-spin" />,
      label: "Traitement...",
      labelClass: "text-amber-400",
    },
    speaking: {
      ringClass: "border-emerald-400 shadow-[0_0_30px_rgba(52,211,153,0.3)]",
      animClass: "animate-voice-pulse",
      icon: <Volume2 className="w-10 h-10 text-emerald-400" />,
      label: "Eli parle...",
      labelClass: "text-emerald-400",
    },
  };

  const config = modeConfig[state.mode];

  return (
    <div
      className="fixed inset-0 z-50 bg-black/90 backdrop-blur-sm flex flex-col items-center justify-center"
      role="dialog"
      aria-label="Mode vocal"
      aria-modal="true"
    >
      {/* Close button */}
      <button
        onClick={onClose}
        className="absolute top-6 right-6 w-10 h-10 rounded-full border border-border-dim bg-bg-secondary/60 flex items-center justify-center text-text-muted hover:text-text-primary hover:border-cyber-cyan/40 transition-all"
        title="Fermer le mode vocal (Echap)"
        aria-label="Fermer le mode vocal"
      >
        <X className="w-5 h-5" />
      </button>

      {/* Keyboard hint */}
      <div className="absolute top-6 left-6 text-[10px] text-text-muted/50 uppercase tracking-wider">
        Echap pour quitter
      </div>

      {/* Central ring + icon */}
      <div className="relative flex items-center justify-center mb-8">
        {/* Outer animated ring */}
        <div
          className={`absolute w-44 h-44 rounded-full border-2 ${config.ringClass} ${config.animClass}`}
        />
        {/* Inner secondary ring (listening only) */}
        {state.mode === "listening" && (
          <div
            className="absolute w-52 h-52 rounded-full border border-cyber-cyan/20 animate-voice-pulse-slow"
          />
        )}
        {/* Speaking wave rings */}
        {state.mode === "speaking" && (
          <>
            <div className="absolute w-52 h-52 rounded-full border border-emerald-400/15 animate-voice-pulse-slow" />
            <div className="absolute w-60 h-60 rounded-full border border-emerald-400/10 animate-voice-pulse-slower" />
          </>
        )}
        {/* Processing dashed ring */}
        {state.mode === "processing" && (
          <div
            className="absolute w-52 h-52 rounded-full border border-dashed border-amber-400/20 animate-voice-rotate-slow"
          />
        )}
        {/* Icon */}
        <div className="relative z-10">
          {config.icon}
        </div>
      </div>

      {/* Status label */}
      <p className={`text-sm font-medium tracking-wide mb-6 ${config.labelClass}`}>
        {config.label}
      </p>

      {/* Current transcript */}
      {state.transcript && (
        <div className="max-w-lg px-6 mb-4 animate-fade-in">
          <p className="text-center text-text-primary text-lg leading-relaxed">
            {state.transcript}
          </p>
        </div>
      )}

      {/* Last response */}
      {state.lastResponse && state.mode !== "idle" && (
        <div className="max-w-lg px-6 mt-2 animate-fade-in">
          <p className="text-center text-text-muted text-sm leading-relaxed line-clamp-4">
            {state.lastResponse}
          </p>
        </div>
      )}

      {/* Error display */}
      {state.error && (
        <div className="max-w-md px-4 py-3 mt-6 rounded-lg border border-red-500/30 bg-red-500/10">
          <p className="text-sm text-red-300 text-center">{state.error}</p>
        </div>
      )}

      {/* Inline styles for custom animations */}
      <style jsx>{`
        @keyframes voice-pulse {
          0% {
            transform: scale(0.95);
            opacity: 0.7;
          }
          50% {
            transform: scale(1.05);
            opacity: 1;
          }
          100% {
            transform: scale(0.95);
            opacity: 0.7;
          }
        }
        @keyframes voice-pulse-slow {
          0% {
            transform: scale(0.97);
            opacity: 0.4;
          }
          50% {
            transform: scale(1.03);
            opacity: 0.7;
          }
          100% {
            transform: scale(0.97);
            opacity: 0.4;
          }
        }
        @keyframes voice-pulse-slower {
          0% {
            transform: scale(0.98);
            opacity: 0.2;
          }
          50% {
            transform: scale(1.02);
            opacity: 0.5;
          }
          100% {
            transform: scale(0.98);
            opacity: 0.2;
          }
        }
        @keyframes voice-rotate {
          0% {
            transform: rotate(0deg);
          }
          100% {
            transform: rotate(360deg);
          }
        }
        @keyframes voice-rotate-slow {
          0% {
            transform: rotate(0deg);
          }
          100% {
            transform: rotate(360deg);
          }
        }
        @keyframes fade-in {
          0% {
            opacity: 0;
            transform: translateY(8px);
          }
          100% {
            opacity: 1;
            transform: translateY(0);
          }
        }
        :global(.animate-voice-pulse) {
          animation: voice-pulse 2s ease-in-out infinite;
        }
        :global(.animate-voice-pulse-slow) {
          animation: voice-pulse-slow 3s ease-in-out infinite;
        }
        :global(.animate-voice-pulse-slower) {
          animation: voice-pulse-slower 4s ease-in-out infinite;
        }
        :global(.animate-voice-rotate) {
          animation: voice-rotate 2s linear infinite;
        }
        :global(.animate-voice-rotate-slow) {
          animation: voice-rotate-slow 8s linear infinite;
        }
        :global(.animate-fade-in) {
          animation: fade-in 0.3s ease-out;
        }
      `}</style>
    </div>
  );
}
