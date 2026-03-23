"use client";

import { useState, useRef, KeyboardEvent } from "react";
import { Send, Loader2, Mic, MicOff } from "lucide-react";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  isLoading?: boolean;
  prefill?: string;
  onPrefillConsumed?: () => void;
}

export function ChatInput({ onSend, disabled, isLoading, prefill, onPrefillConsumed }: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // ── Voice recording state ────────────────────────────────────────────────
  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      audioChunksRef.current = [];
      mr.ondataavailable = (e) => audioChunksRef.current.push(e.data);
      mr.onstop = async () => {
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        const form = new FormData();
        form.append("file", blob, "audio.webm");
        const token = localStorage.getItem("access_token");
        try {
          const res = await fetch("/api/transcribe", {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
            body: form,
          });
          const data = await res.json();
          if (data.text) {
            setValue(data.text);
            setTimeout(() => textareaRef.current?.focus(), 0);
          }
        } catch {
          // Transcription failed silently — user can retry
        }
        stream.getTracks().forEach((t) => t.stop());
      };
      mr.start();
      mediaRecorderRef.current = mr;
      setIsRecording(true);
    } catch {
      // Microphone access denied or unavailable
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
  };

  // Accept suggestion from ChatWindow
  if (prefill && prefill !== value) {
    setValue(prefill);
    onPrefillConsumed?.();
    setTimeout(() => textareaRef.current?.focus(), 0);
  }

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || isLoading) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }
  };

  return (
    <div className="border-t border-border-dim bg-bg-secondary/80 backdrop-blur-sm p-4">
      <div className="flex items-end gap-3 bg-bg-primary border border-border-dim rounded-lg px-4 py-3 focus-within:border-cyber-cyan/30 focus-within:shadow-[0_0_12px_#00e5ff11] transition-all">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          placeholder="Envoyer un message… (Entrée pour envoyer, Maj+Entrée pour nouvelle ligne)"
          rows={1}
          disabled={disabled}
          className="flex-1 bg-transparent text-sm text-text-primary placeholder-text-muted resize-none focus:outline-none max-h-[200px] min-h-[24px] leading-6"
        />
        <button
          type="button"
          onClick={isRecording ? stopRecording : startRecording}
          disabled={disabled}
          title={isRecording ? "Arrêter l'enregistrement" : "Dicter un message"}
          className={`w-8 h-8 rounded-md border flex items-center justify-center transition-all shrink-0 disabled:opacity-30 disabled:cursor-not-allowed ${
            isRecording
              ? "bg-red-500/20 border-red-500/50 text-red-500 animate-pulse"
              : "bg-cyber-cyan/10 border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/20"
          }`}
        >
          {isRecording ? (
            <MicOff className="w-3.5 h-3.5" />
          ) : (
            <Mic className="w-3.5 h-3.5" />
          )}
        </button>
        <button
          onClick={handleSend}
          disabled={!value.trim() || disabled || isLoading}
          className="w-8 h-8 rounded-md bg-cyber-cyan/10 border border-cyber-cyan/30 flex items-center justify-center text-cyber-cyan hover:bg-cyber-cyan/20 transition-all disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
        >
          {isLoading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Send className="w-3.5 h-3.5" />
          )}
        </button>
      </div>
      <p className="text-[10px] text-text-muted mt-1.5 text-center">
        Entrée ↵ envoyer · Maj+Entrée nouvelle ligne
      </p>
    </div>
  );
}
