/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/hooks/useVoiceConversation.ts
 * @brief      Voice conversation hook — STT/TTS conversation loop
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 */

import { useState, useRef, useCallback, useEffect } from "react";
import { getAccessToken } from "@/lib/auth";

// ── Web Speech API types (mirrors ChatInput.tsx) ─────────────────────────────

interface SpeechRecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface SpeechRecognitionResultList {
  length: number;
  [index: number]: SpeechRecognitionResult;
}
interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}
interface SpeechRecognitionErrorEvent extends Event {
  error: string;
}
interface SpeechRecognitionInstance extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: SpeechRecognitionEvent) => void) | null;
  onerror: ((e: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionInstance;
    webkitSpeechRecognition?: new () => SpeechRecognitionInstance;
  }
}

// ── Public types ─────────────────────────────────────────────────────────────

export interface VoiceConversationState {
  mode: "idle" | "listening" | "processing" | "speaking";
  transcript: string;
  lastResponse: string;
  isActive: boolean;
  error: string | null;
}

export interface UseVoiceConversationOptions {
  onSend: (message: string) => void;
  onResponse?: (response: string) => void;
  apiUrl: string;
  enabled: boolean;
}

// ── Stop commands ────────────────────────────────────────────────────────────

const STOP_COMMANDS = ["stop", "arrête", "arrete", "merci", "au revoir"];
const WAKE_WORDS = ["éli", "eli", "hey éli", "hey eli", "hé éli", "hé eli"];

function containsWakeWord(text: string): boolean {
  const lower = text.toLowerCase().trim();
  return WAKE_WORDS.some((w) => lower.includes(w));
}

function stripWakeWord(text: string): string {
  let lower = text.toLowerCase().trim();
  // Remove longest match first
  const sorted = [...WAKE_WORDS].sort((a, b) => b.length - a.length);
  for (const w of sorted) {
    const idx = lower.indexOf(w);
    if (idx !== -1) {
      // Remove the wake word from the original text preserving case
      const before = text.slice(0, idx);
      const after = text.slice(idx + w.length);
      text = (before + after).trim();
      lower = text.toLowerCase().trim();
    }
  }
  // Clean up leading/trailing punctuation and whitespace
  return text.replace(/^[\s,.:!?]+/, "").replace(/[\s,.:!?]+$/, "").trim();
}

function isStopCommand(text: string): boolean {
  const lower = text.toLowerCase().trim();
  return STOP_COMMANDS.some((cmd) => lower === cmd || lower.endsWith(cmd));
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useVoiceConversation(options: UseVoiceConversationOptions) {
  const { onSend, onResponse, apiUrl, enabled } = options;

  const [state, setState] = useState<VoiceConversationState>({
    mode: "idle",
    transcript: "",
    lastResponse: "",
    isActive: false,
    error: null,
  });

  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const wakeRecognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const blobUrlRef = useRef<string | null>(null);
  const finalTranscriptRef = useRef<string>("");
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isActiveRef = useRef(false);
  const modeRef = useRef<VoiceConversationState["mode"]>("idle");

  // Keep refs in sync with state
  useEffect(() => {
    isActiveRef.current = state.isActive;
  }, [state.isActive]);
  useEffect(() => {
    modeRef.current = state.mode;
  }, [state.mode]);

  // ── Helpers ──────────────────────────────────────────────────────────────

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const stopRecognition = useCallback(() => {
    clearSilenceTimer();
    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort();
      } catch {
        // ignore
      }
      recognitionRef.current = null;
    }
  }, [clearSilenceTimer]);

  const stopWakeRecognition = useCallback(() => {
    if (wakeRecognitionRef.current) {
      try {
        wakeRecognitionRef.current.abort();
      } catch {
        // ignore
      }
      wakeRecognitionRef.current = null;
    }
  }, []);

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current);
      blobUrlRef.current = null;
    }
  }, []);

  // ── TTS playback ─────────────────────────────────────────────────────────

  const playTTS = useCallback(
    async (text: string): Promise<void> => {
      if (!text.trim()) return;

      setState((s) => ({ ...s, mode: "speaking" }));

      try {
        const token = getAccessToken();
        const res = await fetch(`${apiUrl}/tts/speak`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ text }),
        });

        if (!res.ok) throw new Error(`TTS ${res.status}`);

        const blob = await res.blob();
        blobUrlRef.current = URL.createObjectURL(blob);

        const audio = new Audio(blobUrlRef.current);
        audioRef.current = audio;

        return new Promise<void>((resolve) => {
          audio.onended = () => {
            stopAudio();
            resolve();
          };
          audio.onerror = () => {
            stopAudio();
            resolve();
          };
          audio.play().catch(() => {
            stopAudio();
            resolve();
          });
        });
      } catch {
        stopAudio();
        setState((s) => ({ ...s, mode: "idle" }));
      }
    },
    [apiUrl, stopAudio],
  );

  // ── Start active listening ───────────────────────────────────────────────

  const startListening = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setState((s) => ({
        ...s,
        error: "Web Speech API non disponible dans ce navigateur.",
      }));
      return;
    }

    stopRecognition();
    finalTranscriptRef.current = "";

    const rec = new SR();
    rec.lang = "fr-FR";
    rec.continuous = true;
    rec.interimResults = true;

    rec.onresult = (e: SpeechRecognitionEvent) => {
      // Rebuild from ALL results (index 0) and overwrite the ref.
      // On mobile Chrome the engine re-emits finalised segments;
      // using e.resultIndex + append causes massive duplication.
      let final = "";
      let interim = "";
      for (let i = 0; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) {
          final += t + " ";
        } else {
          interim += t;
        }
      }
      finalTranscriptRef.current = final;          // overwrite, never append
      const full = (final + interim).trim();
      setState((s) => ({ ...s, transcript: full }));

      // Reset silence timer on each result
      clearSilenceTimer();
      silenceTimerRef.current = setTimeout(() => {
        // End of speech detected via silence — stop recognition to process
        if (recognitionRef.current) {
          try {
            recognitionRef.current.stop();
          } catch {
            // ignore
          }
        }
      }, 2000); // 2 seconds of silence → auto-send
    };

    rec.onerror = (e: SpeechRecognitionErrorEvent) => {
      if (e.error === "not-allowed") {
        setState((s) => ({
          ...s,
          error: "Permission micro refusee. Autorise le micro dans les parametres du navigateur.",
          mode: "idle",
          isActive: false,
        }));
        stopRecognition();
        return;
      }
      if (e.error !== "aborted" && e.error !== "no-speech") {
        setState((s) => ({
          ...s,
          error: `Erreur reconnaissance vocale : ${e.error}`,
        }));
      }
    };

    rec.onend = () => {
      clearSilenceTimer();
      const transcript = finalTranscriptRef.current.trim();

      if (!isActiveRef.current) return;

      if (!transcript) {
        // No speech detected — restart listening if still active
        if (isActiveRef.current && modeRef.current === "listening") {
          setTimeout(() => {
            if (isActiveRef.current) startListening();
          }, 300);
        }
        return;
      }

      // Check for stop commands
      if (isStopCommand(transcript)) {
        setState((s) => ({
          ...s,
          mode: "idle",
          isActive: false,
          transcript: "",
        }));
        stopWakeRecognition();
        return;
      }

      // Send the transcribed message
      setState((s) => ({ ...s, mode: "processing", transcript }));
      onSend(transcript);
    };

    rec.start();
    recognitionRef.current = rec;
    setState((s) => ({ ...s, mode: "listening", transcript: "", error: null }));
  }, [stopRecognition, clearSilenceTimer, onSend, stopWakeRecognition]);

  // ── Wake word detection ──────────────────────────────────────────────────

  const startWakeWordDetection = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;

    stopWakeRecognition();

    const rec = new SR();
    rec.lang = "fr-FR";
    rec.continuous = true;
    rec.interimResults = true;

    rec.onresult = (e: SpeechRecognitionEvent) => {
      // Iterate from 0 (not e.resultIndex) to avoid mobile duplication
      let interim = "";
      let finalText = "";
      for (let i = 0; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) {
          finalText += t + " ";
        } else {
          interim += t;
        }
      }
      const full = (finalText + interim).trim();

      if (containsWakeWord(full)) {
        // Wake word detected — stop wake detection
        stopWakeRecognition();

        const cleanedText = stripWakeWord(full);

        setState((s) => ({
          ...s,
          isActive: true,
          mode: "listening",
          transcript: cleanedText,
          error: null,
        }));

        // If there is leftover text after stripping the wake word, seed it
        finalTranscriptRef.current = cleanedText ? cleanedText + " " : "";

        // Start active listening
        setTimeout(() => startListening(), 100);
      }
    };

    rec.onerror = (e: SpeechRecognitionErrorEvent) => {
      if (e.error === "not-allowed") {
        setState((s) => ({
          ...s,
          error: "Permission micro refusee.",
        }));
        return;
      }
      // For non-critical errors, try to restart
      if (e.error !== "aborted") {
        setTimeout(() => {
          if (!isActiveRef.current) startWakeWordDetection();
        }, 1000);
      }
    };

    rec.onend = () => {
      // Restart wake word detection unless voice mode became active
      if (!isActiveRef.current) {
        setTimeout(() => startWakeWordDetection(), 300);
      }
    };

    rec.start();
    wakeRecognitionRef.current = rec;
  }, [stopWakeRecognition, startListening]);

  // ── Response handler (called by parent when agent responds) ──────────────

  const responseComplete = useCallback(
    async (text: string) => {
      if (!isActiveRef.current) return;

      setState((s) => ({ ...s, lastResponse: text }));
      onResponse?.(text);

      // Play TTS
      await playTTS(text);

      // After TTS finishes, resume listening if still active
      if (isActiveRef.current) {
        startListening();
      }
    },
    [playTTS, startListening, onResponse],
  );

  // ── Public controls ──────────────────────────────────────────────────────

  const start = useCallback(() => {
    stopWakeRecognition();
    stopAudio();
    setState({
      mode: "listening",
      transcript: "",
      lastResponse: "",
      isActive: true,
      error: null,
    });
    startListening();
  }, [stopWakeRecognition, stopAudio, startListening]);

  const stop = useCallback(() => {
    stopRecognition();
    stopWakeRecognition();
    stopAudio();
    clearSilenceTimer();
    setState({
      mode: "idle",
      transcript: "",
      lastResponse: "",
      isActive: false,
      error: null,
    });
  }, [stopRecognition, stopWakeRecognition, stopAudio, clearSilenceTimer]);

  const toggleVoiceMode = useCallback(() => {
    if (isActiveRef.current) {
      stop();
    } else {
      start();
    }
  }, [start, stop]);

  // ── Enable/disable wake word detection based on `enabled` prop ───────────

  useEffect(() => {
    if (enabled && !isActiveRef.current) {
      // Start wake word detection in the background
      startWakeWordDetection();
    } else if (!enabled) {
      stopWakeRecognition();
      if (isActiveRef.current) {
        stop();
      }
    }

    return () => {
      stopWakeRecognition();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  // ── Cleanup on unmount ───────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      stopRecognition();
      stopWakeRecognition();
      stopAudio();
      clearSilenceTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    state,
    start,
    stop,
    toggleVoiceMode,
    responseComplete,
  };
}
