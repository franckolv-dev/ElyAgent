"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/chat/page.tsx
 * @brief      Chat page — main conversation interface with Eli
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 *             https://polyformproject.org/licenses/strict/1.0.0/
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
 *   - INTERDIT : Toute utilisation commerciale sans accord préalable.
 *   - INTERDIT : Redistribution de versions modifiées de ce code.
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

  // Reactive URL params via Next.js hook
  const searchParams  = useSearchParams();
  const urlConvId     = searchParams.get("c") ?? undefined;
  const isNewConv     = searchParams.has("new"); // ?new=<ts> → reset

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
      }
    });

    ws.connect();

    return () => {
      disarmWatchdog();
      ws.disconnect();
    };
  }, []); // WebSocket lifecycle: mount once, disconnect on unmount

  // React to URL param changes (new conv or load history)
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
  }, [urlConvId, isNewConv]);

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
      <div className="flex h-screen overflow-hidden">
        <Sidebar />

        <div className="flex flex-col flex-1 overflow-hidden">
          <Header wsStatus={wsStatus}>
            <button
              onClick={handleToggleVoiceMode}
              title="Mode vocal"
              className={`w-8 h-8 rounded-md border flex items-center justify-center transition-all ${
                voiceConv.state.isActive
                  ? "bg-cyber-cyan/20 border-cyber-cyan/50 text-cyber-cyan shadow-[0_0_8px_rgba(0,229,255,0.3)]"
                  : "border-border-dim text-text-muted hover:text-cyber-cyan hover:border-cyber-cyan/30 hover:bg-cyber-cyan/10"
              }`}
            >
              <Mic className="w-4 h-4" />
            </button>
          </Header>

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

          <div className="flex flex-1 overflow-hidden">
            {/* ── Chat column ── */}
            <div className="flex flex-col flex-1 overflow-hidden">
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
              />
              {/* ── Live Browser Copilot — visible whenever Ély uses the browser ── */}
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
              {/* Drag handle — 6 px wide, sits at the left edge */}
              <div
                onMouseDown={onHandleMouseDown}
                className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize group z-10 flex items-center justify-center"
                title={t("resize")}
              >
                {/* Visible track */}
                <div className="w-px h-full bg-border-dim group-hover:bg-cyber-cyan/40 transition-colors" />
                {/* Pill indicator */}
                <div className="absolute w-1 h-8 rounded-full bg-border-dim group-hover:bg-cyber-cyan/60 transition-colors opacity-0 group-hover:opacity-100" />
              </div>

              {/* Panel content */}
              <div className="flex flex-col items-center justify-start p-4 overflow-y-auto w-full pl-5 bg-bg-secondary/40">
                <AvatarPanel wsMessage={lastWsMessage} isLoading={isLoading} />
              </div>
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
