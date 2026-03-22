"use client";

import { useEffect, useRef, useState } from "react";
import { Volume2, VolumeX, ShieldAlert, Shield } from "lucide-react";
import { CyberpunkAvatar, AvatarState } from "./CyberpunkAvatar";
import { TTSPlayer } from "@/lib/tts";
import type { WSMessage } from "@/lib/types";

interface AvatarPanelProps {
  wsMessage: WSMessage | null;
  isLoading: boolean;
}

export function AvatarPanel({ wsMessage, isLoading }: AvatarPanelProps) {
  const [avatarState, setAvatarState] = useState<AvatarState>("idle");
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [hitlAction, setHitlAction] = useState<{ id: string; description: string } | null>(null);
  const ttsRef = useRef<TTSPlayer | null>(null);

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
      setHitlAction(null);
      if (ttsEnabled && wsMessage.content) ttsRef.current?.speak(wsMessage.content);
      else setAvatarState("idle");
    }
    if (wsMessage.type === "error") setAvatarState("idle");
  }, [wsMessage, ttsEnabled]);

  return (
    <div className="flex flex-col items-center gap-3 w-full">
      {/* Avatar canvas — fills available width */}
      <div className="w-full" style={{ aspectRatio: "5/6" }}>
        <CyberpunkAvatar state={avatarState} className="w-full h-full" />
      </div>

      {/* HITL notification */}
      {hitlAction && (
        <div className="w-full rounded-lg border border-cyber-red/40 bg-cyber-red/5 p-3 text-xs space-y-2">
          <div className="flex items-center gap-1.5 text-cyber-red font-bold">
            <ShieldAlert className="w-3.5 h-3.5" />
            VALIDATION REQUISE
          </div>
          <p className="text-text-secondary leading-relaxed line-clamp-4">
            {hitlAction.description}
          </p>
          <p className="text-text-muted text-[10px]">
            Réponds via l'app Android pour continuer.
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
        {ttsEnabled ? "Voix active" : "Voix muette"}
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
