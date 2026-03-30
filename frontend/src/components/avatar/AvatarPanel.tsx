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

import { useEffect, useRef, useState } from "react";
import { Volume2, VolumeX, ShieldAlert, Shield } from "lucide-react";
import { CyberpunkAvatar, AvatarState } from "./CyberpunkAvatar";
import { TTSPlayer } from "@/lib/tts";
import type { WSMessage } from "@/lib/types";
import { useTranslations } from "next-intl";

interface AvatarPanelProps {
  wsMessage: WSMessage | null;
  isLoading: boolean;
}

// ── NEURAL score per model ──────────────────────────────────────────────────
// Reflects the capability tier of the active LLM (0-100 scale).
// Higher = more capable / larger model.
function neuralScoreForModel(modelUsed: string): number {
  const m = modelUsed.toLowerCase();
  // Anthropic
  if (m.includes("opus"))                           return 99 + Math.random() * 0.9;
  if (m.includes("sonnet"))                         return 94 + Math.random() * 3;
  if (m.includes("haiku"))                          return 83 + Math.random() * 4;
  // DeepSeek
  if (m.includes("reasoner"))                       return 93 + Math.random() * 3;
  if (m.includes("deepseek-chat"))                  return 81 + Math.random() * 3;
  // Gemini
  if (m.includes("1.5-pro") || m.includes("2.0"))  return 89 + Math.random() * 4;
  if (m.includes("flash"))                          return 79 + Math.random() * 4;
  // Mistral — Magistral (raisonnement)
  if (m.includes("magistral-medium"))               return 93 + Math.random() * 3;
  if (m.includes("magistral-small"))                return 88 + Math.random() * 3;
  // Mistral — classiques
  if (m.includes("mistral-large"))                  return 87 + Math.random() * 3;
  if (m.includes("mistral-medium"))                 return 81 + Math.random() * 3;
  if (m.includes("mistral-small"))                  return 76 + Math.random() * 3;
  // Mistral — Ministral (léger)
  if (m.includes("ministral-14b"))                  return 74 + Math.random() * 3;
  if (m.includes("ministral-8b"))                   return 68 + Math.random() * 3;
  // Ollama / local
  if (m.includes("qwen") || m.includes("llama") || m.includes("ollama")) return 68 + Math.random() * 4;
  return 85 + Math.random() * 5; // unknown model
}

export function AvatarPanel({ wsMessage, isLoading }: AvatarPanelProps) {
  const t = useTranslations("avatar");
  const [avatarState, setAvatarState] = useState<AvatarState>("idle");
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [hitlAction, setHitlAction] = useState<{ id: string; description: string } | null>(null);
  const ttsRef = useRef<TTSPlayer | null>(null);

  // HUD metrics
  const [latencyMs,   setLatencyMs]   = useState<number | undefined>(undefined); // undefined → "—" before first response
  const [syncPercent, setSyncPercent] = useState<number>(100);
  const [neuralScore, setNeuralScore] = useState<number | undefined>(undefined); // undefined until first model known
  const [version,     setVersion]     = useState<string>("…");

  // SYNC = rolling success rate over last 10 messages (1=success, 0=error)
  const recentOutcomes = useRef<number[]>([]);
  const messageStartTime = useRef<number>(0);

  // Fetch backend version once on mount
  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_URL ?? "";
    fetch(`${base}/health`)
      .then((r) => r.json())
      .then((d) => setVersion(d.version ?? "1.0.0"))
      .catch(() => setVersion("1.0.0"));
  }, []);

  useEffect(() => {
    ttsRef.current = new TTSPlayer((s) => {
      if (s === "playing")      setAvatarState("speaking");
      else if (s === "loading") setAvatarState("thinking");
      else                      setAvatarState("idle");
    });
    return () => ttsRef.current?.stop();
  }, []);

  useEffect(() => {
    ttsRef.current?.setEnabled(ttsEnabled);
  }, [ttsEnabled]);

  useEffect(() => {
    if (!wsMessage) return;

    if (wsMessage.type === "start") {
      messageStartTime.current = performance.now();
      setAvatarState("thinking");
      return;
    }
    if (wsMessage.type === "hitl_pending") {
      setAvatarState("alert");
      setHitlAction({ id: wsMessage.action_id ?? "", description: wsMessage.description ?? "" });
      return;
    }
    if (wsMessage.type === "hitl_resolved") {
      setHitlAction(null);
      setAvatarState("idle");
      return;
    }
    if (wsMessage.type === "message" && wsMessage.role === "assistant") {
      // LAT — real end-to-end response time
      const lat = Math.round(performance.now() - messageStartTime.current);
      setLatencyMs(lat);

      // SYNC — rolling success rate over last 10 exchanges
      recentOutcomes.current = [...recentOutcomes.current.slice(-9), 1];
      const rate = recentOutcomes.current.reduce((a, b) => a + b, 0) / recentOutcomes.current.length;
      setSyncPercent(parseFloat((rate * 100).toFixed(1)));

      // NEURAL — capability tier of the active model
      const modelUsed = wsMessage.model_used ?? "";
      if (modelUsed) setNeuralScore(neuralScoreForModel(modelUsed));

      setHitlAction(null);
      if (ttsEnabled && wsMessage.content) ttsRef.current?.speak(wsMessage.content);
      else setAvatarState("idle");
    }
    if (wsMessage.type === "error") {
      // Count errors in SYNC rate
      recentOutcomes.current = [...recentOutcomes.current.slice(-9), 0];
      const rate = recentOutcomes.current.reduce((a, b) => a + b, 0) / recentOutcomes.current.length;
      setSyncPercent(parseFloat((rate * 100).toFixed(1)));
      setAvatarState("idle");
    }
  }, [wsMessage, ttsEnabled]);

  return (
    <div className="flex flex-col items-center gap-3 w-full">
      {/* Avatar canvas — fills available width */}
      <div className="w-full" style={{ aspectRatio: "5/6" }}>
        <CyberpunkAvatar state={avatarState} className="w-full h-full" latencyMs={latencyMs} syncPercent={syncPercent} neuralScore={neuralScore} version={version} />
      </div>

      {/* HITL notification */}
      {hitlAction && (
        <div className="w-full rounded-lg border border-cyber-red/40 bg-cyber-red/5 p-3 text-xs space-y-2">
          <div className="flex items-center gap-1.5 text-cyber-red font-bold">
            <ShieldAlert className="w-3.5 h-3.5" />
            {t("validationRequired")}
          </div>
          <p className="text-text-secondary leading-relaxed line-clamp-4">
            {hitlAction.description}
          </p>
          <p className="text-text-muted text-[10px]">
            {t("replyViaApp")}
          </p>
        </div>
      )}

      {/* TTS toggle */}
      <button
        onClick={() => setTtsEnabled((v) => !v)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs border transition-all ${
          ttsEnabled
            ? "border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5"
            : "border-border-dim text-text-muted hover:border-cyber-cyan/20"
        }`}
      >
        {ttsEnabled ? <Volume2 className="w-3 h-3" /> : <VolumeX className="w-3 h-3" />}
        {ttsEnabled ? t("voiceActive") : t("voiceMuted")}
      </button>

      {/* State label */}
      <div className="flex items-center gap-1.5">
        <Shield className="w-3 h-3 text-cyber-cyan" />
        <span className="text-[10px] text-text-muted uppercase tracking-widest">
          {avatarState}
        </span>
      </div>
    </div>
  );
}
