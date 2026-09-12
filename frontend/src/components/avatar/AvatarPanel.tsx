"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/avatar/AvatarPanel.tsx
 * @brief      Avatar panel — side panel wrapping the 3D avatar scene
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 */

import { useEffect, useRef, useState } from "react";
import { Volume2, VolumeX, ShieldAlert, Check, X, Ban } from "lucide-react";
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
  voiceConversationActive?: boolean;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

export function AvatarPanel({ wsMessage, isLoading, voiceConversationActive = false }: AvatarPanelProps) {
  const t = useTranslations("avatar");
  const [avatarState, setAvatarState] = useState<AvatarState>("idle");
  // ttsEnabled persists per user (mai 2026 — was previously local state
  // that reverted to true on every page reload). The TTS player itself is
  // not engaged until prefsLoaded becomes true, to avoid speaking the
  // first message of a session before we know the user's choice.
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [prefsLoaded, setPrefsLoaded] = useState(false);
  const [voiceError, setVoiceError] = useState(false);
  const [hitlAction, setHitlAction] = useState<{ id: string; description: string } | null>(null);
  const [hitlPending, setHitlPending] = useState<
    "allow" | "allow_for_task" | "allow_always" | "deny" | "ban" | null
  >(null);
  const [hitlError, setHitlError] = useState<string | null>(null);
  const ttsRef = useRef<TTSPlayer | null>(null);
  const lastProcessedMessage = useRef<WSMessage | null>(null);

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
  // Last known model — persisted across WS messages so SESSION panel keeps
  // the value visible after the streaming ends (wsMessage drops to null).
  const [lastModel,   setLastModel]   = useState<string>("");
  // ⚠️ TOUR EN COURS (24/08). Sans lui, MODEL et LATENCY affichent les chiffres
  // du tour PRÉCÉDENT pendant qu'un nouveau tourne — avec la même assurance
  // que s'ils décrivaient celui-ci. Franck a lu « gemma / 25 325 ms » pendant
  // qu'un tour cloud de plusieurs minutes travaillait, et en a conclu que seul
  // le local répondait. Le panneau ne mentait pas : il était en retard, et rien
  // ne le disait.
  //
  // ⚠️ `avatarState` ne pouvait pas servir : la synthèse vocale le met aussi à
  // « thinking » quand elle charge son audio. Il faut un signal qui ne décrive
  // QUE le tour.
  const [enVol,       setEnVol]       = useState<boolean>(false);
  const [tokensUsed,  setTokensUsed]  = useState<{ input: number; output: number }>({ input: 0, output: 0 });
  // Les serveurs locaux ne renvoient pas toujours d'`usage_metadata` : le
  // backend estime alors, et le dit. Cf. `estimate_tokens_if_missing`.
  const [tokensEstimated, setTokensEstimated] = useState(false);

  const messageStartTime = useRef<number>(0);

  useEffect(() => {
    ttsRef.current = new TTSPlayer((s) => {
      setVoiceError(s === "error");
      if (s === "playing")      setAvatarState("speaking");
      else if (s === "loading") setAvatarState("thinking");
      else                      setAvatarState("idle");
    });
    return () => ttsRef.current?.stop();
  }, []);

  useEffect(() => {
    ttsRef.current?.setEnabled(ttsEnabled && !voiceConversationActive);
  }, [ttsEnabled, voiceConversationActive]);

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
    if (!wsMessage || lastProcessedMessage.current === wsMessage) return;
    // Keep the answer pending until the preference is known. Otherwise a
    // fast response during startup is marked processed and never spoken.
    if (wsMessage.type === "message" && !prefsLoaded) return;
    lastProcessedMessage.current = wsMessage;

    if (wsMessage.type === "start") {
      ttsRef.current?.stop();
      messageStartTime.current = performance.now();
      setEnVol(true);
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
      setEnVol(false);
      setLatencyMs(lat);

      const modelUsed = wsMessage.model_used ?? "";
      setLastModel(modelUsed);
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
      if (ttsEnabled && !voiceConversationActive && wsMessage.content) ttsRef.current?.speak(wsMessage.content);
      else setAvatarState("idle");
    }
    if (wsMessage.type === "error" || wsMessage.type === "stopped") {
      // Un tour qui échoue est un tour TERMINÉ : sans ça le panneau resterait
      // en attente jusqu'au prochain message, donc muet sur le tour d'avant.
      setEnVol(false);
      ttsRef.current?.stop();
      setAvatarState("idle");
    }
  }, [wsMessage, ttsEnabled, prefsLoaded, voiceConversationActive]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-3)", width: "100%" }}>
      <div className="presence-heading">
        <strong>ELY<span className="presence-spark">✦</span></strong>
        <span role="status"><i />{t(`states.${avatarState}`)}</span>
      </div>
      <div className="avatar-card">
        <div className="avatar-stage">
          <CyberpunkAvatar state={avatarState} minimal className="w-full h-full" />
        </div>
        <span className="presence-caption">EXACTLY LIKE YOU</span>
        <div className="avatar-actions">
          <button onClick={toggleTts} aria-pressed={ttsEnabled}
            disabled={!prefsLoaded}
            className={`avatar-action ${ttsEnabled ? "primary" : ""}`}>
            {ttsEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
            {ttsEnabled ? t("voiceActive") : t("enableVoice")}
          </button>
        </div>
      </div>

      {voiceError && <p role="status" style={{ color: "var(--warning)", fontSize: 12 }}>{t("voiceUnavailable")}</p>}

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
        <h4>{t("sessionTitle")}</h4>
        <div className="kv">
          <span className="k">{t("model")}</span>
          <span className="v" style={{ fontSize: 10, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {enVol || !lastModel
              ? "—"
              : lastModel.replace(/^(llm|slm):/, "").split("+")[0].split("/").pop()}
          </span>
        </div>
        <div className="kv">
          <span className="k">{t("latency")}</span>
          <span className="v">
            {enVol || latencyMs === undefined ? "—" : `${latencyMs}ms`}
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
// Refresh toutes les 10s et au retour dans la fenêtre.
interface ChannelStatus {
  configured: boolean;
  running: boolean;
  linked: boolean;
}
interface ActiveChannelsResponse {
  telegram: ChannelStatus;
  ely_android: ChannelStatus;
  ntfy: ChannelStatus;
  chrome?: { connected: boolean };
  system?: { connected: boolean };
}

function ChannelsPanel() {
  const [data, setData] = useState<ActiveChannelsResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const r = await authFetch(`${API_BASE}/api/channels/active`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const json = await r.json();
        if (!cancelled) setData(json);
      } catch {
        // A failed refresh is unknown, not a stale "connected" badge.
        if (!cancelled) setData(null);
      }
    };
    fetchOnce();
    const interval = setInterval(fetchOnce, 10_000);
    window.addEventListener("focus", fetchOnce);
    return () => {
      cancelled = true;
      clearInterval(interval);
      window.removeEventListener("focus", fetchOnce);
    };
  }, []);

  return (
    <div className="avatar-info">
      <h4>Connexions</h4>
      <ConnectionRow label="Chrome" connected={data?.chrome?.connected} />
      <ConnectionRow label="Système" connected={data?.system?.connected} />
      <ChannelRow label="Android"  status={data?.ely_android} />
      <ChannelRow label="Telegram" status={data?.telegram} />
      <ChannelRow label="Notifications"     status={data?.ntfy} />
    </div>
  );
}

function ConnectionRow({ label, connected }: { label: string; connected: boolean | undefined }) {
  const color = connected ? "var(--accent)" : "var(--dot-off)";
  return (
    <div className="kv">
      <span className="k">{label}</span>
      <span className="v" style={{ color, display: "flex", alignItems: "center", gap: 4 }}>
        <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: "50%", background: color }} />
        {connected === undefined ? "—" : connected ? "Connecté" : "Déconnecté"}
      </span>
    </div>
  );
}

function ChannelRow({ label, status }: { label: string; status: ChannelStatus | undefined }) {
  const on = !!status?.configured;
  const linked = !!status?.linked;
  let badge = status ? "Inactif" : "—";
  // `--dot-off` et non `--text-muted` : la maquette du 21/08 donne les deux
  // séparément, et à 6 px un point d'état a besoin de plus de présence
  // qu'une étiquette. Le muted est descendu à #6c6f73 dans la même
  // révision — le point y aurait disparu.
  let color = "var(--dot-off)";
  if (on && linked) { badge = "Lié"; color = "var(--success)"; }
  else if (on) { badge = "Configuré"; color = "var(--info)"; }
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
}
