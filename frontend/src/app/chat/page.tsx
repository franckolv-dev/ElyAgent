"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/chat/page.tsx
 * @brief      Chat page — main conversation interface with Eli
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

import { useState, useEffect, useCallback, useRef, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Pencil, Check, X, Mic } from "lucide-react";
import { AuthGuard }          from "@/components/layout/AuthGuard";
import { Sidebar }             from "@/components/layout/Sidebar";
import { Header }              from "@/components/layout/Header";
import { ChatWindow }          from "@/components/chat/ChatWindow";
import { ChatInput }           from "@/components/chat/ChatInput";
import { OnboardingFlow }      from "@/components/chat/OnboardingFlow";
import { AvatarPanel }         from "@/components/avatar/AvatarPanel";
import { LiveBrowserPanel }    from "@/components/browser/LiveBrowserPanel";
import { VoiceModeOverlay }    from "@/components/chat/VoiceModeOverlay";
import { AgentWebSocket }      from "@/lib/websocket";
import { api }                 from "@/lib/api";
import { authFetch }           from "@/lib/auth";
import { useVoiceConversation } from "@/hooks/useVoiceConversation";
import type { Attachment, BrowserFrame, ChatMessage, ToolImage, WSMessage } from "@/lib/types";
import { useTranslations } from "next-intl";

const API_URL_CHAT = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Resizable avatar-panel hook ───────────────────────────────────────────
const PANEL_MIN  = 220;
const PANEL_MAX  = 640;
const PANEL_KEY  = "ely-avatar-width";
const PANEL_DEFAULT = 320;   // ~33 % wider than the old 256 px

function usePanelResize() {
  const [width, setWidth] = useState<number>(PANEL_DEFAULT);

  // Hydrate from localStorage once mounted
  useEffect(() => {
    const saved = localStorage.getItem(PANEL_KEY);
    if (saved) setWidth(Math.max(PANEL_MIN, Math.min(PANEL_MAX, parseInt(saved, 10))));
  }, []);

  const isDragging  = useRef(false);
  const startX      = useRef(0);
  const startWidth  = useRef(0);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      // Dragging the LEFT edge of the panel: moving mouse left → panel wider
      const delta   = startX.current - e.clientX;
      const newW    = Math.max(PANEL_MIN, Math.min(PANEL_MAX, startWidth.current + delta));
      setWidth(newW);
    };

    const onUp = () => {
      if (!isDragging.current) return;
      isDragging.current           = false;
      document.body.style.cursor      = "";
      document.body.style.userSelect  = "";
      // Persist after release (read latest via functional update)
      setWidth((w) => { localStorage.setItem(PANEL_KEY, String(w)); return w; });
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup",   onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup",   onUp);
    };
  }, []);

  const onHandleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current          = true;
    startX.current              = e.clientX;
    startWidth.current          = width;
    document.body.style.cursor     = "col-resize";
    document.body.style.userSelect = "none";
  }, [width]);

  return { width, onHandleMouseDown };
}

// ── Page (inner — needs Suspense for useSearchParams) ────────────────────
function ChatPageInner() {
  const t = useTranslations("chat");
  // Onboarding overlay : at first /chat visit we check the user's status
  // and either show the conversational onboarding OR the regular chat.
  // null = not yet checked (initial loading), true = show onboarding,
  // false = show normal chat.
  const [showOnboarding, setShowOnboarding] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await api.getOnboardingStatus();
        if (!cancelled) setShowOnboarding(status.should_show);
      } catch {
        // If the endpoint fails (e.g. before backend deploy), fall back to chat
        if (!cancelled) setShowOnboarding(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const [messages,        setMessages]        = useState<ChatMessage[]>([]);
  const [isLoading,       setIsLoading]       = useState(false);
  const [wsStatus,        setWsStatus]        = useState<"connected" | "disconnected" | "connecting">("disconnected");
  const [conversationId,  setConversationId]  = useState<string | undefined>();
  const [lastWsMessage,   setLastWsMessage]   = useState<WSMessage | null>(null);
  const [suggestion,      setSuggestion]      = useState<string>("");
  const [streamingContent,setStreamingContent]= useState<string>("");
  const [browserFrame,    setBrowserFrame]    = useState<BrowserFrame | null>(null);
  const [activeTool,      setActiveTool]      = useState<string | null>(null);
  const [convTitle,       setConvTitle]       = useState<string>("");
  const [editingTitle,    setEditingTitle]    = useState(false);
  const [editTitleValue,  setEditTitleValue]  = useState("");
  const titleInputRef = useRef<HTMLInputElement>(null);
  const [voiceModeEnabled, setVoiceModeEnabled] = useState(false);
  const pendingToolImages = useRef<ToolImage[]>([]);
  const wsRef = useRef<AgentWebSocket | null>(null);
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const router = useRouter();
  // Hermes Chantier 4 — discreet toast triggered by `provider.switched`
  // events emitted by the backend FallbackManager when it bascules from
  // the configured primary to a fallback (rate limit, h1_hallucination,
  // billing, etc.). Visible 6 seconds then auto-dismissed.
  const [providerToast, setProviderToast] = useState<{
    from: string;
    to: string;
    reason: string;
  } | null>(null);
  const providerToastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── First-launch redirect: if no LLM is configured, redirect to setup ──
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (localStorage.getItem("ely_setup_completed")) return;
    authFetch(`${API_URL_CHAT}/api/setup/status`)
      .then((r) => r.json())
      .then((d: { is_first_launch: boolean }) => {
        if (d.is_first_launch) {
          router.replace("/setup");
        }
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { width: avatarWidth, onHandleMouseDown } = usePanelResize();

  // Reactive URL params via Next.js hook.
  // For « new conversation » we read the timestamp value (not just .has)
  // so consecutive clicks on the « Nouvelle conversation » button — each
  // pushing /chat?new=<Date.now()> with a different number — are seen as
  // distinct param changes by React. A boolean .has() flag would stay
  // `true` between the two clicks and the reset useEffect would never
  // re-run (bug surfaced 2026-05-09: 2nd click did nothing, the WS stayed
  // on the previous conv and the next message hit a 504 gateway timeout).
  const searchParams  = useSearchParams();
  const urlConvId     = searchParams.get("c") ?? undefined;
  const newConvToken  = searchParams.get("new"); // string | null — the timestamp
  const isNewConv     = newConvToken !== null;

  useEffect(() => {
    const ws = new AgentWebSocket();
    wsRef.current = ws;

    ws.onStatus(setWsStatus);

    // ── Watchdog: auto-unblock the UI if no WS event arrives within 150s ──
    // The backend can legitimately be slow (qwen inference + fallback
    // chain can take ~60s). But a truly stuck request (disconnected WS,
    // HITL timeout race, etc.) would leave isLoading=true forever. The
    // watchdog is reset on every incoming message and fires only when
    // nothing has happened for 150s.
    const armWatchdog = () => {
      if (watchdogRef.current) clearTimeout(watchdogRef.current);
      watchdogRef.current = setTimeout(() => {
        setIsLoading(false);
        setActiveTool(null);
        setStreamingContent((partial) => {
          if (partial) {
            setMessages((prev) => [...prev, {
              role: "assistant",
              content: partial + "\n\n_(réponse interrompue — pas de nouvelles du backend depuis 150s)_",
              created_at: new Date().toISOString(),
            }]);
          }
          return "";
        });
      }, 150_000);
    };
    const disarmWatchdog = () => {
      if (watchdogRef.current) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
    };

    ws.onMessage((msg: WSMessage) => {
      setLastWsMessage(msg);
      // Every incoming event is a sign of life — reset the idle watchdog.
      armWatchdog();

      if (msg.type === "start") {
        setConversationId(msg.conversation_id);
        setIsLoading(true);
        setStreamingContent("");
        setActiveTool(null);
        pendingToolImages.current = [];
      } else if (msg.type === "tool_start") {
        setActiveTool(msg.tool ?? null);
        // Le texte streamé avant un appel d'outil est un préambule (raisonnement
        // / script orchestrate de GPT-5.5), redondant avec l'indicateur d'outil.
        // On le purge pour n'afficher que la réponse finale (après le dernier
        // outil). Le backend fait de même côté message persisté.
        setStreamingContent("");
      } else if (msg.type === "tool_end") {
        setActiveTool(null);
        if (msg.image) pendingToolImages.current.push(msg.image);
      } else if (msg.type === "token") {
        setActiveTool(null);
        setStreamingContent((prev) => prev + (msg.content ?? ""));
      } else if (msg.type === "message" && msg.role === "assistant") {
        const imgs = pendingToolImages.current.splice(0);
        setMessages((prev) => [...prev, {
          role: "assistant",
          content: msg.content ?? "",
          model_used: msg.model_used,
          routing_score: msg.routing_score,
          // Use backend-provided timestamp (reflects real response time) if available,
          // fallback to now() for backward compat if server hasn't been updated yet.
          created_at: msg.created_at ?? new Date().toISOString(),
          ...(imgs.length > 0 ? { toolImages: imgs } : {}),
          // Attachments from MEDIA: sentinels parsed by media_router.py
          ...(msg.attachments ? { attachments: msg.attachments } : {}),
        }]);
        setStreamingContent("");
        setActiveTool(null);
        setIsLoading(false);
        disarmWatchdog();
      } else if (msg.type === "stopped") {
        // Agent was interrupted — finalize any partial content already streamed
        setStreamingContent((partial) => {
          if (partial) {
            setMessages((prev) => [...prev, {
              role: "assistant",
              content: partial,
              created_at: new Date().toISOString(),
            }]);
          }
          return "";
        });
        setActiveTool(null);
        setIsLoading(false);
        disarmWatchdog();
      } else if (msg.type === "done") {
        // Explicit turn-end event from the backend. Pairs with the "message"
        // / "stopped" events to guarantee `isLoading` flips to false even
        // when React's batched state update was delayed. Without this,
        // clicking Enter just after the agent finished could be interpreted
        // as `onStop()` (handleKeyDown sees stale isLoading=true), sending
        // a stop signal that the backend then silently ignored — leaving
        // the input visually locked until a page refresh.
        setActiveTool(null);
        setIsLoading(false);
        disarmWatchdog();
      } else if (msg.type === "hitl_pending") {
        // HITL blocks the backend up to 120s waiting for approval.
        // Free the input immediately so the user can type follow-ups,
        // use the stop button, or simply see that the UI is alive —
        // approval happens via the dedicated buttons in the avatar panel.
        setActiveTool(null);
        setIsLoading(false);
      } else if (msg.type === "hitl_resolved") {
        // Mark loading true again — the tool will now run and produce a
        // response that will flip isLoading back to false on "message".
        setIsLoading(true);
      } else if (msg.type === "error") {
        setMessages((prev) => [...prev, { role: "assistant", content: t("error", { message: msg.content ?? "" }) }]);
        setStreamingContent("");
        setActiveTool(null);
        setIsLoading(false);
        disarmWatchdog();
      } else if (msg.type === "browser_frame" && msg.data) {
        setBrowserFrame({ data: msg.data, url: msg.url ?? "", title: msg.title ?? "" });
      } else if (msg.type === "slm.fallback") {
        // Le modèle LOCAL n'a pas pu répondre — le tour est reparti sur le
        // cloud. Ce repli n'était que journalisé : Franck a passé une journée
        // (21/08) à se demander pourquoi GPT-5.6 répondait à « bonjour »
        // alors que son modèle local était chargé. Un repli doit se voir.
        if (providerToastTimer.current) clearTimeout(providerToastTimer.current);
        setProviderToast({
          from: msg.model ?? "modèle local",
          to: "modèle distant",
          reason: msg.reason ?? "le modèle local n'a pas répondu",
        });
        providerToastTimer.current = setTimeout(() => {
          setProviderToast(null);
        }, 6000);
      } else if (msg.type === "provider.switched") {
        // Backend swapped LLM provider mid-conversation. Show a discreet
        // toast so the user understands why latency / wording may shift.
        if (providerToastTimer.current) clearTimeout(providerToastTimer.current);
        setProviderToast({
          from: msg.from ?? "?",
          to: msg.to ?? "?",
          reason: msg.reason ?? "fallback",
        });
        providerToastTimer.current = setTimeout(() => {
          setProviderToast(null);
        }, 6000);
      }
    });

    ws.connect();

    return () => {
      disarmWatchdog();
      if (providerToastTimer.current) {
        clearTimeout(providerToastTimer.current);
        providerToastTimer.current = null;
      }
      ws.disconnect();
    };
  }, []); // WebSocket lifecycle: mount once, disconnect on unmount

  // React to URL param changes (new conv or load history).
  // `newConvToken` (the ?new=<ts> value, not just its existence) is in
  // the dep array so each click on « Nouvelle conversation » is seen as
  // a distinct change even when the previous URL was already on /chat
  // with a ?new=… param. This was the « 2nd click does nothing » bug.
  useEffect(() => {
    if (isNewConv) {
      setMessages([]);
      setConversationId(undefined);
      setConvTitle("");
      setEditingTitle(false);
    } else if (urlConvId) {
      setConversationId(urlConvId);
      api.getConversationMessages(urlConvId)
        .then((data: { title?: string; messages: Array<{role: string; content: string}> }) => {
          setConvTitle(data.title || "");
          setMessages(data.messages.map((m: { role: string; content: string; created_at?: string }) => ({
            role: m.role as "user" | "assistant",
            content: m.content,
            created_at: m.created_at,
          })));
        })
        .catch(() => {});
    }
  }, [urlConvId, isNewConv, newConvToken]);

  // -- Title rename helpers ---------------------------------------------------
  const startTitleEdit = () => {
    setEditTitleValue(convTitle);
    setEditingTitle(true);
    setTimeout(() => titleInputRef.current?.select(), 50);
  };

  const commitTitleEdit = async () => {
    setEditingTitle(false);
    const newTitle = editTitleValue.trim();
    if (!newTitle || !conversationId || newTitle === convTitle) return;
    setConvTitle(newTitle);
    try {
      await api.renameConversation(conversationId, newTitle);
    } catch {
      // revert on failure
      setConvTitle(convTitle);
    }
  };

  const handleSend = useCallback((content: string, attachments?: Attachment[], screenCapture?: string) => {
    if (!wsRef.current) return;
    setMessages((prev) => [...prev, { role: "user", content, attachments, created_at: new Date().toISOString() }]);
    wsRef.current.send(content, conversationId, attachments, screenCapture);
  }, [conversationId]);

  // J4 — drop the last user message + everything after it from the UI.
  const dropLastUserTurn = useCallback(() => {
    setMessages((prev) => {
      let idx = -1;
      for (let i = prev.length - 1; i >= 0; i--) {
        if (prev[i].role === "user") { idx = i; break; }
      }
      return idx >= 0 ? prev.slice(0, idx) : prev;
    });
  }, []);

  // J4 — regenerate the last assistant reply: drop the last turn (DB + UI),
  // then resend the same user message → fresh answer.
  const handleRegenerate = useCallback(async () => {
    if (!conversationId || !wsRef.current) return;
    let lastUser: string | undefined;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user" && typeof messages[i].content === "string") {
        lastUser = messages[i].content as string;
        break;
      }
    }
    if (lastUser === undefined) return;
    try { await api.truncateFromLastUser(conversationId); } catch { /* best-effort */ }
    dropLastUserTurn();
    handleSend(lastUser);
  }, [conversationId, messages, handleSend, dropLastUserTurn]);

  // J4 — edit the last user message then resend the edited text.
  const handleEditLast = useCallback(async (newContent: string) => {
    if (!conversationId || !wsRef.current) return;
    try { await api.truncateFromLastUser(conversationId); } catch { /* best-effort */ }
    dropLastUserTurn();
    handleSend(newContent);
  }, [conversationId, handleSend, dropLastUserTurn]);

  // ── Voice conversation hook ──────────────────────────────────────────────
  const voiceConv = useVoiceConversation({
    onSend: useCallback((message: string) => {
      if (!wsRef.current) return;
      setMessages((prev) => [...prev, { role: "user", content: message, created_at: new Date().toISOString() }]);
      wsRef.current.send(message, conversationId);
    }, [conversationId]),
    apiUrl: API_URL_CHAT,
    enabled: voiceModeEnabled,
  });

  // Feed agent responses to the voice hook when voice mode is active
  useEffect(() => {
    if (!voiceConv.state.isActive) return;
    if (!lastWsMessage) return;
    if (lastWsMessage.type === "message" && lastWsMessage.role === "assistant" && lastWsMessage.content) {
      voiceConv.responseComplete(lastWsMessage.content);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastWsMessage]);

  const handleToggleVoiceMode = useCallback(() => {
    if (voiceConv.state.isActive) {
      voiceConv.stop();
      setVoiceModeEnabled(false);
    } else {
      setVoiceModeEnabled(true);
      // Small delay to let the hook's useEffect pick up the enabled change,
      // then explicitly start active listening
      setTimeout(() => voiceConv.start(), 100);
    }
  }, [voiceConv]);

  return (
    <AuthGuard>
      {/* Layout refonte : header full-width au-dessus de la sidebar + main + avatar */}
      <div className="flex flex-col h-screen overflow-hidden">
        {/* Provider switch toast — Hermes Chantier 4. Discreet badge in
            top-right that fades after 6s. Lets the user know when ELY
            silently bascules from the configured primary LLM to a
            fallback (rate limit, hallucination, billing…). */}
        {providerToast && (
          <div
            className="fixed top-3 right-3 z-50 max-w-sm rounded-md border border-yellow-500/40 bg-bg-secondary/95 backdrop-blur px-3 py-2 shadow-lg text-xs text-text-primary animate-in fade-in slide-in-from-top-2"
            role="status"
            aria-live="polite"
          >
            <div className="flex items-start gap-2">
              <span aria-hidden="true" className="text-yellow-400 text-sm leading-none">⚡</span>
              <div className="flex-1 min-w-0">
                <div className="font-medium">Bascule de modèle</div>
                <div className="text-text-dim mt-0.5 break-words">
                  <span className="text-text-primary/80">{providerToast.from}</span>
                  {" → "}
                  <span className="text-text-primary">{providerToast.to}</span>
                </div>
                <div className="text-text-dim text-[10px] mt-1">Raison : {providerToast.reason}</div>
              </div>
              <button
                onClick={() => setProviderToast(null)}
                aria-label="Fermer"
                className="text-text-dim hover:text-text-primary leading-none"
              >
                ×
              </button>
            </div>
          </div>
        )}
        <Header wsStatus={wsStatus}>
          <button
            onClick={handleToggleVoiceMode}
            title="Mode vocal"
            className={`icon-btn ${voiceConv.state.isActive ? "active" : ""}`}
          >
            <Mic size={15} />
          </button>
        </Header>

        <div className="flex flex-1 overflow-hidden">
          <Sidebar />

          {/* `chat-thread` — le fil passe sous le reste du châssis (21/08).
              Sur le conteneur et pas sur la zone défilante seule : sinon une
              marche apparaît juste au-dessus du composeur. */}
          <div className="chat-thread flex flex-col flex-1 overflow-hidden">

          {/* Conversation title bar */}
          {conversationId && convTitle && (
            <div className="px-4 py-1.5 border-b border-border-dim bg-bg-secondary/40 flex items-center gap-2 shrink-0">
              {editingTitle ? (
                <div className="flex items-center gap-1 flex-1">
                  <input
                    ref={titleInputRef}
                    value={editTitleValue}
                    onChange={(e) => setEditTitleValue(e.target.value)}
                    onBlur={commitTitleEdit}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitTitleEdit();
                      if (e.key === "Escape") setEditingTitle(false);
                    }}
                    className="flex-1 px-2 py-0.5 text-sm bg-bg-tertiary border border-cyber-cyan/30 rounded text-text-primary focus:outline-none"
                    autoFocus
                  />
                  <button onClick={commitTitleEdit} className="text-cyber-cyan hover:text-cyber-cyan/80">
                    <Check className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => setEditingTitle(false)} className="text-text-muted hover:text-text-secondary">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ) : (
                <button
                  onClick={startTitleEdit}
                  className="group flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary transition-colors"
                  title={t("clickToRename")}
                >
                  <span className="truncate max-w-md">{convTitle}</span>
                  <Pencil className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                </button>
              )}
            </div>
          )}

          {showOnboarding === true ? (
            <OnboardingFlow onComplete={() => setShowOnboarding(false)} />
          ) : (
            <>
              <ChatWindow
                messages={messages}
                isLoading={isLoading}
                onSuggestion={setSuggestion}
                streamingContent={streamingContent}
                conversationId={conversationId}
                activeTool={activeTool}
                onRegenerate={handleRegenerate}
                onEditMessage={handleEditLast}
              />
              {browserFrame && (
                <div className="px-4 pb-1">
                  <LiveBrowserPanel
                    frame={browserFrame}
                    onClose={() => setBrowserFrame(null)}
                  />
                </div>
              )}
              <ChatInput
                onSend={handleSend}
                onStop={() => wsRef.current?.sendStop()}
                isLoading={isLoading}
                disabled={wsStatus === "disconnected"}
                prefill={suggestion}
                onPrefillConsumed={() => setSuggestion("")}
                onVoiceModeToggle={handleToggleVoiceMode}
                isVoiceModeActive={voiceConv.state.isActive}
              />
            </>
          )}
          </div>

          {/* ── Avatar panel (resizable, desktop only) ── */}
          <div
            className="hidden lg:flex shrink-0 relative"
            style={{ width: avatarWidth }}
          >
            <div
              onMouseDown={onHandleMouseDown}
              className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize group z-10 flex items-center justify-center"
              title={t("resize")}
            >
              <div className="w-px h-full bg-border-dim group-hover:bg-cyber-cyan/40 transition-colors" />
              <div className="absolute w-1 h-8 rounded-full bg-border-dim group-hover:bg-cyber-cyan/60 transition-colors opacity-0 group-hover:opacity-100" />
            </div>

            <div className="avatar-panel" style={{ width: "100%", paddingLeft: 24 }}>
              <AvatarPanel wsMessage={lastWsMessage} isLoading={isLoading} />
            </div>
          </div>
        </div>
      </div>

      {/* Voice conversation overlay */}
      {voiceConv.state.isActive && (
        <VoiceModeOverlay
          state={voiceConv.state}
          onClose={() => {
            voiceConv.stop();
            setVoiceModeEnabled(false);
          }}
        />
      )}
    </AuthGuard>
  );
}

// Suspense wrapper required by Next.js when using useSearchParams in a page
export default function ChatPage() {
  return (
    <Suspense>
      <ChatPageInner />
    </Suspense>
  );
}
