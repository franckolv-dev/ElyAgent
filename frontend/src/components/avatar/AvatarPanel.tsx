"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/avatar/AvatarPanel.tsx
 * @brief      Avatar panel — side panel wrapping the 3D avatar scene
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
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */

import { useEffect, useRef, useState } from "react";
import { Volume2, VolumeX, ShieldAlert, Shield, Check, X, Ban } from "lucide-react";
import { CyberpunkAvatar, AvatarState } from "./CyberpunkAvatar";
import { TTSPlayer } from "@/lib/tts";
import type { WSMessage } from "@/lib/types";
import { useTranslations } from "next-intl";
import { authFetch } from "@/lib/auth";
import { api } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface AvatarPanelProps {
  wsMessage: WSMessage | null;
  isLoading: boolean;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return String(n);
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
  // ttsEnabled persists per user (mai 2026 — was previously local state
  // that reverted to true on every page reload). The TTS player itself is
  // not engaged until prefsLoaded becomes true, to avoid speaking the
  // first message of a session before we know the user's choice.
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [prefsLoaded, setPrefsLoaded] = useState(false);
  const [hitlAction, setHitlAction] = useState<{ id: string; description: string } | null>(null);
  const [hitlPending, setHitlPending] = useState<
    "allow" | "allow_for_task" | "allow_always" | "deny" | "ban" | null
  >(null);
  const [hitlError, setHitlError] = useState<string | null>(null);
  const ttsRef = useRef<TTSPlayer | null>(null);

  // ── Resolve HITL via web — hits the same endpoint as the Android app ──
  const resolveHitl = async (
    decision: "allow" | "allow_for_task" | "allow_always" | "deny" | "ban",
  ) => {
    if (!hitlAction || hitlPending) return;
    setHitlPending(decision);
    setHitlError(null);
    try {
      // Validation endpoints are exposed under `/api/validation/*` via the
      // backend so they traverse the Cloudflare Tunnel → nginx path (nginx
      // only proxies `/api/*` to the backend). The legacy `/validation/*`
      // alias still exists for the Android app which talks directly to
      // the backend without nginx.
      const res = await authFetch(
        `${API_BASE}/api/validation/${hitlAction.id}/${decision}`,
        { method: "POST" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // Success — the backend will push `hitl_resolved` via WebSocket,
      // which clears `hitlAction` in the effect below. Leave the spinner
      // visible until that happens, to avoid a flash of "no action".
    } catch (e) {
      setHitlError(e instanceof Error ? e.message : "error");
      setHitlPending(null);
    }
  };

  // HUD metrics
  const [latencyMs,   setLatencyMs]   = useState<number | undefined>(undefined); // undefined → "—" before first response
  const [syncPercent, setSyncPercent] = useState<number>(100);
  const [neuralScore, setNeuralScore] = useState<number | undefined>(undefined); // undefined until first model known
  const [version,     setVersion]     = useState<string>("…");
  // Last known model — persisted across WS messages so SESSION panel keeps
  // the value visible after the streaming ends (wsMessage drops to null).
  const [lastModel,   setLastModel]   = useState<string>("");
  const [tokensUsed,  setTokensUsed]  = useState<{ input: number; output: number }>({ input: 0, output: 0 });
  // Les serveurs locaux ne renvoient pas toujours d'`usage_metadata` : le
  // backend estime alors, et le dit. Cf. `estimate_tokens_if_missing`.
  const [tokensEstimated, setTokensEstimated] = useState(false);

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

  // Load persisted TTS preference once at mount (fire-and-forget).
  // If the user is not logged in or the API fails, we fall back to the
  // default (enabled) — same behaviour as before this preference existed.
  useEffect(() => {
    let cancelled = false;
    api
      .voicePrefsGet()
      .then((p) => {
        if (!cancelled) setTtsEnabled(p.tts_auto_enabled);
      })
      .catch(() => {
        // Auth not ready / network blip — keep default `true`.
      })
      .finally(() => {
        if (!cancelled) setPrefsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Toggle handler — flips local state immediately for snappy UI, then
  // persists in background. On API failure we revert so the UI stays
  // truthful about the actual stored preference.
  const toggleTts = () => {
    const next = !ttsEnabled;
    setTtsEnabled(next);
    api.voicePrefsPatch({ tts_auto_enabled: next }).catch(() => {
      setTtsEnabled(!next); // revert on failure
    });
  };

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
      setHitlPending(null);
      setHitlError(null);
      return;
    }
    if (wsMessage.type === "hitl_resolved") {
      setHitlAction(null);
      setHitlPending(null);
      setHitlError(null);
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
      if (modelUsed) {
        setNeuralScore(neuralScoreForModel(modelUsed));
        setLastModel(modelUsed);
      }
      // Tokens cumulés sur la session (incrément par message).
      // Le `as unknown as {…}` qui vivait ici a été retiré le 21/08 : les
      // champs sont déclarés dans `WSMessage`. Il masquait le vrai défaut —
      // le backend ne les émettait pas, et un cast ne peut pas s'en plaindre.
      if (wsMessage.input_tokens || wsMessage.output_tokens) {
        setTokensUsed((prev) => ({
          input:  prev.input  + (wsMessage.input_tokens  || 0),
          output: prev.output + (wsMessage.output_tokens || 0),
        }));
        // Une session reste marquée « estimée » dès qu'un seul de ses tours
        // l'était : le total affiché n'est alors plus une mesure.
        if (wsMessage.tokens_estimated) setTokensEstimated(true);
      }

      setHitlAction(null);
      if (ttsEnabled && prefsLoaded && wsMessage.content) ttsRef.current?.speak(wsMessage.content);
      else setAvatarState("idle");
    }
    if (wsMessage.type === "error") {
      // Count errors in SYNC rate
      recentOutcomes.current = [...recentOutcomes.current.slice(-9), 0];
      const rate = recentOutcomes.current.reduce((a, b) => a + b, 0) / recentOutcomes.current.length;
      setSyncPercent(parseFloat((rate * 100).toFixed(1)));
      setAvatarState("idle");
    }
  }, [wsMessage, ttsEnabled, prefsLoaded]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-3)", width: "100%" }}>
      {/* ── Avatar wireframe stage : grille + halo + tête 3D ── */}
      <div className="avatar-stage" style={{ height: "auto", aspectRatio: "1 / 1" }}>
        {/* Corners HUD */}
        <div className="avatar-corner tl">
          NEURAL:{neuralScore !== undefined ? neuralScore.toFixed(1) : "—"}
        </div>
        <div className="avatar-corner tr">
          LAT:{latencyMs !== undefined ? `${latencyMs}ms` : "—"}
        </div>
        <div className="avatar-corner bl">SYNC:{syncPercent.toFixed(1)}%</div>
        <div className="avatar-corner br">VER:{version}</div>

        {/* Halo de fond derrière la tête */}
        <div
          aria-hidden
          style={{
            position: "absolute",
            inset: 0,
            background:
              "radial-gradient(circle at 50% 45%, var(--accent-glow) 0%, transparent 55%)",
            pointerEvents: "none",
          }}
        />

        {/* Tête 3D Cyberpunk — composant existant, intacte */}
        <div style={{ position: "absolute", inset: 0 }}>
          <CyberpunkAvatar
            state={avatarState}
            className="w-full h-full"
            latencyMs={latencyMs}
            syncPercent={syncPercent}
            neuralScore={neuralScore}
            version={version}
          />
        </div>
      </div>

      {/* ── Actions (TTS + état) ── */}
      <div className="avatar-actions">
        <button
          onClick={toggleTts}
          className={`avatar-action ${ttsEnabled ? "primary" : ""}`}
        >
          {ttsEnabled ? <Volume2 size={13} /> : <VolumeX size={13} />}
          {ttsEnabled ? t("voiceActive") : t("voiceMuted")}
        </button>
        <div className="avatar-action ghost">
          <Shield size={11} /> ELY :: {avatarState.toUpperCase()}
        </div>
      </div>

      {/* ── HITL — Approve / Deny / Ban ── */}
      {hitlAction && (
        <div
          className="card"
          style={{
            borderColor: "var(--danger)",
            background: "var(--danger-soft)",
            padding: "var(--sp-3)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              color: "var(--danger)",
              fontWeight: 600,
              fontSize: 12,
              marginBottom: 8,
            }}
          >
            <ShieldAlert size={13} />
            {t("validationRequired")}
          </div>
          <p
            style={{
              fontSize: 11,
              color: "var(--text-secondary)",
              lineHeight: 1.5,
              margin: "0 0 8px",
              maxHeight: 80,
              overflow: "hidden",
              display: "-webkit-box",
              WebkitLineClamp: 4,
              WebkitBoxOrient: "vertical",
            }}
          >
            {hitlAction.description}
          </p>

          {/*
            2×2 grid (2026-05-23 redesign — was 3 columns which caused the
            "Toujours interdire" button to overflow the danger card on
            narrow avatar panels). Row 1 = positive decisions, row 2 =
            negative decisions. Mobile-friendly : each button gets half
            the panel width.
          */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            <button
              onClick={() => resolveHitl("allow")}
              disabled={hitlPending !== null}
              className="btn primary"
              style={{ justifyContent: "center", padding: "5px 8px", fontSize: 11 }}
              title={t("hitlApprove")}
            >
              <Check size={11} />
              {hitlPending === "allow" ? t("hitlSending") : t("hitlApprove")}
            </button>
            <button
              onClick={() => resolveHitl("allow_for_task")}
              disabled={hitlPending !== null}
              className="btn primary"
              style={{ justifyContent: "center", padding: "5px 8px", fontSize: 11 }}
              title={t("hitlAllowForTaskTitle")}
            >
              <Check size={11} />
              {hitlPending === "allow_for_task"
                ? t("hitlSending")
                : t("hitlAllowForTask")}
            </button>
            <button
              onClick={() => resolveHitl("allow_always")}
              disabled={hitlPending !== null}
              className="btn primary"
              style={{ justifyContent: "center", padding: "5px 8px", fontSize: 11 }}
              title={t("hitlAllowAlways")}
            >
              <Check size={11} />
              {hitlPending === "allow_always"
                ? t("hitlSending")
                : t("hitlAllowAlways")}
            </button>
            <button
              onClick={() => resolveHitl("deny")}
              disabled={hitlPending !== null}
              className="btn"
              style={{ justifyContent: "center", padding: "5px 8px", fontSize: 11 }}
              title={t("hitlDeny")}
            >
              <X size={11} />
              {hitlPending === "deny" ? t("hitlSending") : t("hitlDeny")}
            </button>
            <button
              onClick={() => resolveHitl("ban")}
              disabled={hitlPending !== null}
              className="btn danger"
              style={{ justifyContent: "center", padding: "5px 8px", fontSize: 11 }}
              title={t("hitlBan")}
            >
              <Ban size={11} />
              {hitlPending === "ban" ? t("hitlSending") : t("hitlBan")}
            </button>
          </div>

          {hitlError && (
            <p style={{ color: "var(--danger)", fontSize: 10, marginTop: 6 }}>
              {t("hitlFailed")} — {hitlError}
            </p>
          )}
        </div>
      )}

      {/* ── Panneau SESSION ── */}
      <div className="avatar-info">
        <h4>SESSION</h4>
        <div className="kv">
          <span className="k">MODEL</span>
          <span className="v" style={{ fontSize: 10, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {lastModel ? lastModel.replace(/^(llm|slm):/, "").split("+")[0].split("/").pop() : "—"}
          </span>
        </div>
        <div className="kv">
          <span className="k">LATENCY</span>
          <span className="v">
            {latencyMs !== undefined ? `${latencyMs}ms` : "—"}
          </span>
        </div>
        <div className="kv">
          <span className="k">TOKENS</span>
          <span className="v">
            {tokensUsed.input + tokensUsed.output > 0
              ? `${tokensEstimated ? "~" : ""}${formatTokens(tokensUsed.input + tokensUsed.output)}`
              : "—"}
          </span>
        </div>
        <div className="kv">
          <span className="k">NEURAL</span>
          <span className="v">
            {neuralScore !== undefined ? neuralScore.toFixed(1) : "—"}
          </span>
        </div>
        <div className="kv">
          <span className="k">SYNC</span>
          <span className="v">{syncPercent.toFixed(1)}%</span>
        </div>
      </div>

      {/* ── Panneau CANAUX ACTIFS ── */}
      <ChannelsPanel />
    </div>
  );
}

// ── Channels panel — état des bots configurés sur le backend ──
//
// Affiche pour chaque canal :
//   ON   = configuré sur le backend (token présent ou bot tournant)
//   LINK = configuré + ce user a lié son compte (Telegram /link, etc.)
//   OFF  = pas configuré
//
// Refresh toutes les 60s pour suivre les hot-restart admin.
interface ChannelStatus {
  configured: boolean;
  running: boolean;
  linked: boolean;
}
interface ActiveChannelsResponse {
  telegram: ChannelStatus;
  discord: ChannelStatus;
  slack: ChannelStatus;
  whatsapp: ChannelStatus;
  ely_android: ChannelStatus;
  ntfy: ChannelStatus;
}

function ChannelsPanel() {
  const [data, setData] = useState<ActiveChannelsResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const r = await authFetch(`${API_BASE}/api/channels/active`);
        if (!r.ok) return;
        const json = await r.json();
        if (!cancelled) setData(json);
      } catch {
        // silent
      }
    };
    fetchOnce();
    const interval = setInterval(fetchOnce, 60_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const Row = ({ label, status }: { label: string; status: ChannelStatus | undefined }) => {
    const on = !!status?.configured;
    const linked = !!status?.linked;
    let badge = "OFF";
    let color = "var(--text-muted)";
    if (on && linked) { badge = "LINK"; color = "var(--success)"; }
    else if (on) { badge = "ON"; color = "var(--info)"; }
    return (
      <div className="kv">
        <span className="k">{label}</span>
        <span
          className="v"
          style={{ color, display: "flex", alignItems: "center", gap: 4 }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: 999,
              background: color,
              boxShadow: on ? `0 0 6px ${color}` : "none",
            }}
          />
          {badge}
        </span>
      </div>
    );
  };

  return (
    <div className="avatar-info">
      <h4>CANAUX ACTIFS</h4>
      <Row label="ANDROID"  status={data?.ely_android} />
      <Row label="TELEGRAM" status={data?.telegram} />
      <Row label="WHATSAPP" status={data?.whatsapp} />
      <Row label="DISCORD"  status={data?.discord} />
      <Row label="SLACK"    status={data?.slack} />
      <Row label="NTFY"     status={data?.ntfy} />
    </div>
  );
}
