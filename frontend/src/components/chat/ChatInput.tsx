"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/chat/ChatInput.tsx
 * @brief      Chat input bar — text, voice dictation, attachments
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

import { useState, useRef, useEffect, useCallback, useMemo, KeyboardEvent } from "react";
import { useTranslations } from "next-intl";
import { Send, Loader2, Mic, MicOff, Paperclip, X, FileText, Image, FileCode, Monitor, Square, Headphones } from "lucide-react";
import type { Attachment } from "@/lib/types";
import { getAccessToken } from "@/lib/auth";

interface ChatInputProps {
  onSend: (message: string, attachments?: Attachment[], screenCapture?: string) => void;
  onStop?: () => void;
  disabled?: boolean;
  isLoading?: boolean;
  prefill?: string;
  onPrefillConsumed?: () => void;
  onVoiceModeToggle?: () => void;
  isVoiceModeActive?: boolean;
}

// ── Attachment state (client-side, before/during upload) ─────────────────────
interface PendingAttachment {
  localId: string;       // temp client ID
  filename: string;
  size: number;
  uploading: boolean;
  error?: string;
  result?: Attachment;   // filled once upload succeeds
}

// Web Speech API types
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
  onresult: (e: SpeechRecognitionEvent) => void;
  onerror: (e: SpeechRecognitionErrorEvent) => void;
  onend: () => void;
  start(): void;
  stop(): void;
}
// SpeechRecognition is now in TypeScript's DOM lib — access via (window as any)
// to avoid duplicate declaration conflicts with newer TS versions.

// ── File icon helper ──────────────────────────────────────────────────────────
function FileIcon({ filename }: { filename: string }) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (["jpg", "jpeg", "png", "gif", "webp", "svg"].includes(ext))
    return <Image className="w-3 h-3 shrink-0" />;
  if (["py", "js", "ts", "html", "css", "json", "yaml", "toml", "sh"].includes(ext))
    return <FileCode className="w-3 h-3 shrink-0" />;
  return <FileText className="w-3 h-3 shrink-0" />;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
}

// ── Component ─────────────────────────────────────────────────────────────────
export function ChatInput({ onSend, onStop, disabled, isLoading, prefill, onPrefillConsumed, onVoiceModeToggle, isVoiceModeActive }: ChatInputProps) {
  const t = useTranslations("chatInput");
  const [value, setValue] = useState("");
  const [micError, setMicError] = useState("");
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<PendingAttachment[]>([]);
  const [screenCapture, setScreenCapture] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Voice recording state ─────────────────────────────────────────────────
  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef  = useRef<Blob[]>([]);
  const speechRecRef       = useRef<SpeechRecognitionInstance | null>(null);
  const finalTranscriptRef = useRef<string>("");

  // Effacer l'erreur micro après 4 secondes
  useEffect(() => {
    if (!micError) return;
    const t = setTimeout(() => setMicError(""), 4000);
    return () => clearTimeout(t);
  }, [micError]);

  // ── Web Speech API ────────────────────────────────────────────────────────
  const startSpeechRecognition = (): boolean => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SR: (new () => SpeechRecognitionInstance) | undefined =
      (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    if (!SR) return false;

    finalTranscriptRef.current = "";
    const rec = new SR();
    rec.lang = "fr-FR";
    rec.continuous = true;     // ← continue même après les silences
    rec.interimResults = true; // ← affiche les mots au fil de la dictée

    rec.onresult = (e: SpeechRecognitionEvent) => {
      // Rebuild the full transcript from ALL results on every event.
      // On mobile (Android Chrome), the recognition engine can re-emit
      // previously finalised results — if we only iterate from
      // e.resultIndex and append, the same text gets duplicated dozens
      // of times.  Iterating from 0 and overwriting the ref is the
      // pattern recommended by Google's Web Speech API docs.
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
      if (full) setValue(full);
    };

    rec.onerror = (e: SpeechRecognitionErrorEvent) => {
      if (e.error === "not-allowed") {
        setMicError("Permission micro refusée. Autorise le micro dans les paramètres du navigateur.");
      } else if (e.error !== "aborted") {
        setMicError(`Erreur micro : ${e.error}`);
      }
      setIsRecording(false);
    };

    rec.onend = () => {
      setValue((v) => v.trim());
      setIsRecording(false);
      setTimeout(() => textareaRef.current?.focus(), 0);
    };

    rec.start();
    speechRecRef.current = rec;
    setIsRecording(true);
    return true;
  };

  // ── MediaRecorder + Whisper ───────────────────────────────────────────────
  const startMediaRecorder = async (): Promise<boolean> => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      audioChunksRef.current = [];
      mr.ondataavailable = (e) => audioChunksRef.current.push(e.data);
      mr.onstop = async () => {
        setIsTranscribing(true);
        const blob  = new Blob(audioChunksRef.current, { type: "audio/webm" });
        const form  = new FormData();
        form.append("file", blob, "audio.webm");
        const token = getAccessToken();
        try {
          const res  = await fetch("/api/transcribe", {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
            body: form,
          });
          const data = await res.json();
          if (data.text) {
            setValue(data.text);
            setTimeout(() => textareaRef.current?.focus(), 0);
          } else {
            setMicError("Transcription vide — réessaie.");
          }
        } catch {
          setMicError("Erreur de transcription. Réessaie.");
        } finally {
          setIsTranscribing(false);
        }
        stream.getTracks().forEach((t) => t.stop());
      };
      mr.start();
      mediaRecorderRef.current = mr;
      setIsRecording(true);
      return true;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("Permission") || msg.includes("NotAllowed")) {
        setMicError("Permission micro refusée.");
      } else if (msg.includes("NotSupported") || msg.includes("https")) {
        setMicError("Le micro nécessite HTTPS ou localhost.");
      } else {
        setMicError(`Micro indisponible : ${msg}`);
      }
      return false;
    }
  };

  const startRecording = async () => {
    setMicError("");
    if (startSpeechRecognition()) return;
    await startMediaRecorder();
  };

  const stopRecording = useCallback(() => {
    if (speechRecRef.current) {
      speechRecRef.current.stop();
      speechRecRef.current = null;
    }
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
  }, []);

  // ── File attachment ───────────────────────────────────────────────────────
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    // Reset input so the same file can be re-selected
    e.target.value = "";

    const token = getAccessToken();

    for (const file of files) {
      const localId = `${Date.now()}-${Math.random()}`;

      // Add pending chip immediately
      setPendingFiles((prev) => [
        ...prev,
        { localId, filename: file.name, size: file.size, uploading: true },
      ]);

      // Upload in the background
      const form = new FormData();
      form.append("file", file, file.name);

      try {
        const res = await fetch("/api/upload", {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
          body: form,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail ?? `HTTP ${res.status}`);
        }
        const result: Attachment = await res.json();
        setPendingFiles((prev) =>
          prev.map((p) =>
            p.localId === localId ? { ...p, uploading: false, result } : p
          )
        );
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        setPendingFiles((prev) =>
          prev.map((p) =>
            p.localId === localId ? { ...p, uploading: false, error: msg } : p
          )
        );
      }
    }
  };

  const removeFile = useCallback((localId: string) => {
    setPendingFiles((prev) => prev.filter((p) => p.localId !== localId));
  }, []);

  // ── Screen capture ────────────────────────────────────────────────────────
  const captureScreen = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      const track = stream.getVideoTracks()[0];
      const imageCapture = new (window as unknown as { ImageCapture: new (t: MediaStreamTrack) => { grabFrame(): Promise<ImageBitmap> } }).ImageCapture(track);
      const bitmap = await imageCapture.grabFrame();

      const canvas = document.createElement("canvas");
      canvas.width  = bitmap.width;
      canvas.height = bitmap.height;
      canvas.getContext("2d")!.drawImage(bitmap, 0, 0);

      // Downscale if too large (> 1280 px wide) to keep WS message small
      const MAX_W = 1280;
      let finalB64: string;
      if (bitmap.width > MAX_W) {
        const scale = MAX_W / bitmap.width;
        const small = document.createElement("canvas");
        small.width  = MAX_W;
        small.height = Math.round(bitmap.height * scale);
        small.getContext("2d")!.drawImage(canvas, 0, 0, small.width, small.height);
        finalB64 = small.toDataURL("image/png").split(",")[1];
      } else {
        finalB64 = canvas.toDataURL("image/png").split(",")[1];
      }

      setScreenCapture(finalB64);
      track.stop();
      stream.getTracks().forEach((t) => t.stop());
      setTimeout(() => textareaRef.current?.focus(), 0);
    } catch (err: unknown) {
      // User cancelled the picker or permission denied — silently ignore
      if (err instanceof Error && err.name !== "NotAllowedError") {
        console.warn("captureScreen error:", err);
      }
    }
  }, []);

  // ── Prefill ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (prefill && prefill !== value) {
      setValue(prefill);
      onPrefillConsumed?.();
      setTimeout(() => textareaRef.current?.focus(), 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill]);

  // ── Send ──────────────────────────────────────────────────────────────────
  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    // Allow sending even with no text if there are attachments or screen capture
    if ((!trimmed && !pendingFiles.length && !screenCapture) || disabled || isLoading) return;
    // Only include successfully uploaded attachments
    const readyAttachments = pendingFiles
      .filter((p) => !p.uploading && !p.error && p.result)
      .map((p) => p.result!);
    onSend(
      trimmed,
      readyAttachments.length ? readyAttachments : undefined,
      screenCapture ?? undefined,
    );
    setValue("");
    setPendingFiles([]);
    setScreenCapture(null);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }, [value, pendingFiles, screenCapture, disabled, isLoading, onSend]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      // Hotfix 2026-05-23 : if `isLoading` is still true, do NOT send a
      // stop signal on Enter. Previous behaviour converted the keystroke
      // into `onStop()`, but React's state batching meant `isLoading` was
      // often stale (true) for a few ms after the agent's "message" event,
      // so the user pressing Enter to reply to the agent's question would
      // unintentionally stop the (already-finished) turn instead. The
      // backend would then silently ignore the stop (no agent running),
      // leaving the input visually locked. Now Enter during loading is a
      // no-op — the user must click the red square explicitly to abort.
      if (isLoading) {
        return;
      }
      handleSend();
    }
  }, [handleSend, isLoading]);

  const handleInput = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }
  }, []);

  const canSend = useMemo(
    () =>
      (value.trim().length > 0 ||
        pendingFiles.some((p) => !p.uploading && !p.error) ||
        !!screenCapture) &&
      !disabled &&
      !isLoading,
    [value, pendingFiles, screenCapture, disabled, isLoading]
  );
  const hasUploading = useMemo(() => pendingFiles.some((p) => p.uploading), [pendingFiles]);

  return (
    // Wrapper transparent : on veut que la zone sous le textarea ait la
    // même couleur que la zone chat au-dessus, pas un bandeau distinct.
    // Pas de border-top, pas de fond, juste un padding pour aérer.
    <div style={{ padding: "0", background: "transparent" }}>

      {/* ── Input dock — chips au-dessus du textarea, icon row dessous.
            Les chips d'attachements et de capture d'écran sont placés DANS
            le dock pour rester alignés avec la zone de saisie (même fond,
            même padding, mêmes coins arrondis). Avant ils étaient au-dessus
            du dock et flottaient bizarrement à gauche du conteneur. ── */}
      <div className="ely-input-dock">
        {/* ── Screen capture preview chip ── */}
        {screenCapture && (
          <div className="flex items-center gap-2">
            <div className="relative inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-cyber-cyan/40 bg-cyber-cyan/10 text-[11px] text-cyber-cyan">
              <Monitor className="w-3 h-3 shrink-0" />
              <span>Capture d&apos;écran prête</span>
              <button
                type="button"
                onClick={() => setScreenCapture(null)}
                className="ml-1 opacity-60 hover:opacity-100 transition-opacity"
                title={t("removeCapture")}
              >
                <X className="w-3 h-3" />
              </button>
            </div>
            {/* Miniature */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`data:image/png;base64,${screenCapture}`}
              alt={t("capturePreview")}
              className="h-10 rounded border border-cyber-cyan/30 object-cover cursor-pointer"
              title={t("screenshotPreview")}
            />
          </div>
        )}

        {/* ── Attachment chips ── */}
        {pendingFiles.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {pendingFiles.map((pf) => (
              <div
                key={pf.localId}
                className={`flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] max-w-[200px] ${
                  pf.error
                    ? "bg-red-500/10 border-red-500/30 text-red-300"
                    : pf.uploading
                    ? "bg-cyber-cyan/5 border-cyber-cyan/20 text-text-muted animate-pulse"
                    : "bg-cyber-cyan/10 border-cyber-cyan/30 text-cyber-cyan"
                }`}
              >
                {pf.uploading ? (
                  <Loader2 className="w-3 h-3 shrink-0 animate-spin" />
                ) : (
                  <FileIcon filename={pf.filename} />
                )}
                <span className="truncate flex-1">{pf.filename}</span>
                <span className="text-text-muted shrink-0">{formatSize(pf.size)}</span>
                {!pf.uploading && (
                  <button
                    type="button"
                    onClick={() => removeFile(pf.localId)}
                    className="shrink-0 opacity-60 hover:opacity-100 transition-opacity"
                    title={t("removeFile")}
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          placeholder={t("placeholder")}
          rows={1}
          disabled={disabled}
          className="ely-input-textarea"
        />

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.txt,.md,.csv,.json,.xml,.doc,.docx,.xls,.xlsx,.pptx,.jpg,.jpeg,.png,.gif,.webp,.py,.js,.ts,.html,.css,.yaml,.yml,.toml,.log,.zip"
          className="hidden"
          onChange={handleFileSelect}
          disabled={disabled}
        />

        <div className="ely-input-actions">
          <div className="ely-input-actions-left">
            {/* Paperclip */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={disabled}
              title={t("attachFile")}
              className="icon-btn"
            >
              {hasUploading ? <Loader2 size={15} className="animate-spin" /> : <Paperclip size={15} />}
            </button>

            {/* Screen capture */}
            <button
              type="button"
              onClick={captureScreen}
              disabled={disabled}
              title={t("shareScreen")}
              className={`icon-btn ${screenCapture ? "active" : ""}`}
            >
              <Monitor size={15} />
            </button>

            {/* Voice mode */}
            {onVoiceModeToggle && (
              <button
                type="button"
                onClick={onVoiceModeToggle}
                disabled={disabled}
                title={isVoiceModeActive ? "Quitter le mode vocal" : "Mode vocal"}
                className={`icon-btn ${isVoiceModeActive ? "active" : ""}`}
              >
                <Headphones size={15} />
              </button>
            )}

            {/* Mic */}
            <button
              type="button"
              onClick={isRecording ? stopRecording : startRecording}
              disabled={disabled}
              title={isRecording ? "Arrêter l'enregistrement" : "Dicter un message"}
              className={`icon-btn ${isRecording ? "active" : ""}`}
              style={isRecording ? { color: "var(--danger)", background: "var(--danger-soft)" } : undefined}
            >
              {isRecording ? <MicOff size={15} /> : <Mic size={15} />}
            </button>
          </div>

          {/* Send / Stop button */}
          {isLoading ? (
            <button
              onClick={onStop}
              title={t("stop")}
              className="icon-btn"
              style={{
                background: "var(--danger-soft)",
                color: "var(--danger)",
                border: "1px solid var(--danger)",
              }}
            >
              <Square size={14} className="fill-current" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!canSend}
              className="icon-btn"
              style={{
                background: canSend ? "var(--accent-soft)" : "transparent",
                color: canSend ? "var(--accent)" : "var(--text-muted)",
                border: canSend ? "1px solid var(--accent)" : "1px solid var(--border-subtle)",
              }}
            >
              <Send size={15} />
            </button>
          )}
        </div>
      </div>

      {/* ── Mic error panel ── */}
      {micError && (
        <div className="mt-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-300">
          <p className="font-semibold mb-1">🎤 Microphone bloqué</p>
          {micError.includes("HTTPS") ? (
            <p>Le micro nécessite une connexion sécurisée (HTTPS). Il fonctionnera une fois le projet déployé sur le VPS avec SSL.</p>
          ) : (
            <>
              <p className="mb-1">Le navigateur a refusé l&apos;accès au microphone. Pour l&apos;autoriser :</p>
              <ol className="list-decimal list-inside space-y-0.5 text-red-200">
                <li>Clique sur l&apos;icône 🔒 ou ℹ️ à gauche de l&apos;URL dans Chrome</li>
                <li>Cherche <strong>Microphone</strong> → change en <strong>Autoriser</strong></li>
                <li>Recharge la page (F5)</li>
              </ol>
              <p className="mt-1 text-red-400/70">
                Ou colle dans la barre d&apos;adresse :{" "}
                <span className="font-mono bg-red-900/40 px-1 rounded select-all">
                  chrome://settings/content/microphone
                </span>
                {" "}et autorise <em>localhost</em>.
              </p>
            </>
          )}
        </div>
      )}

      {/* ── Status line ── */}
      {!micError && !isTranscribing && (
        <p className="text-[10px] text-text-muted mt-1.5 text-center">
          {t("footerHelp")}
          {pendingFiles.length > 0 && !hasUploading && (
            <> · {t("attachedFiles", { count: pendingFiles.filter(p => !p.error).length })}</>
          )}
        </p>
      )}
      {isTranscribing && (
        <p className="text-[10px] text-cyber-cyan mt-1.5 text-center animate-pulse">{t("transcribing")}</p>
      )}
    </div>
  );
}
