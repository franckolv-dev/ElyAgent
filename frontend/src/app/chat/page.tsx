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

import { useState, useEffect, useCallback, useRef, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { AuthGuard }          from "@/components/layout/AuthGuard";
import { Sidebar }             from "@/components/layout/Sidebar";
import { Header }              from "@/components/layout/Header";
import { ChatWindow }          from "@/components/chat/ChatWindow";
import { ChatInput }           from "@/components/chat/ChatInput";
import { AvatarPanel }         from "@/components/avatar/AvatarPanel";
import { LiveBrowserPanel }    from "@/components/browser/LiveBrowserPanel";
import { AgentWebSocket }      from "@/lib/websocket";
import { api }                 from "@/lib/api";
import { authFetch }           from "@/lib/auth";
import type { Attachment, BrowserFrame, ChatMessage, WSMessage } from "@/lib/types";
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
  const [messages,        setMessages]        = useState<ChatMessage[]>([]);
  const [isLoading,       setIsLoading]       = useState(false);
  const [wsStatus,        setWsStatus]        = useState<"connected" | "disconnected" | "connecting">("disconnected");
  const [conversationId,  setConversationId]  = useState<string | undefined>();
  const [lastWsMessage,   setLastWsMessage]   = useState<WSMessage | null>(null);
  const [suggestion,      setSuggestion]      = useState<string>("");
  const [streamingContent,setStreamingContent]= useState<string>("");
  const [browserFrame,    setBrowserFrame]    = useState<BrowserFrame | null>(null);
  const [activeTool,      setActiveTool]      = useState<string | null>(null);
  const wsRef = useRef<AgentWebSocket | null>(null);
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

    ws.onMessage((msg: WSMessage) => {
      setLastWsMessage(msg);

      if (msg.type === "start") {
        setConversationId(msg.conversation_id);
        setIsLoading(true);
        setStreamingContent("");
        setActiveTool(null);
      } else if (msg.type === "tool_start") {
        setActiveTool(msg.tool ?? null);
      } else if (msg.type === "tool_end") {
        setActiveTool(null);
      } else if (msg.type === "token") {
        setActiveTool(null);
        setStreamingContent((prev) => prev + (msg.content ?? ""));
      } else if (msg.type === "message" && msg.role === "assistant") {
        setMessages((prev) => [...prev, {
          role: "assistant",
          content: msg.content ?? "",
          model_used: msg.model_used,
          routing_score: msg.routing_score,
          created_at: new Date().toISOString(),
        }]);
        setStreamingContent("");
        setActiveTool(null);
        setIsLoading(false);
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
      } else if (msg.type === "error") {
        setMessages((prev) => [...prev, { role: "assistant", content: t("error", { message: msg.content ?? "" }) }]);
        setStreamingContent("");
        setActiveTool(null);
        setIsLoading(false);
      } else if (msg.type === "browser_frame" && msg.data) {
        setBrowserFrame({ data: msg.data, url: msg.url ?? "", title: msg.title ?? "" });
      }
    });

    ws.connect();

    return () => ws.disconnect();
  }, []); // WebSocket lifecycle: mount once, disconnect on unmount

  // React to URL param changes (new conv or load history)
  useEffect(() => {
    if (isNewConv) {
      setMessages([]);
      setConversationId(undefined);
    } else if (urlConvId) {
      setConversationId(urlConvId);
      api.getConversationMessages(urlConvId)
        .then((data: { messages: Array<{role: string; content: string}> }) => {
          setMessages(data.messages.map((m: { role: string; content: string; created_at?: string }) => ({
            role: m.role as "user" | "assistant",
            content: m.content,
            created_at: m.created_at,
          })));
        })
        .catch(() => {});
    }
  }, [urlConvId, isNewConv]);

  const handleSend = useCallback((content: string, attachments?: Attachment[], screenCapture?: string) => {
    if (!wsRef.current) return;
    setMessages((prev) => [...prev, { role: "user", content, attachments, created_at: new Date().toISOString() }]);
    wsRef.current.send(content, conversationId, attachments, screenCapture);
  }, [conversationId]);

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />

        <div className="flex flex-col flex-1 overflow-hidden">
          <Header wsStatus={wsStatus} />

          <div className="flex flex-1 overflow-hidden">
            {/* ── Chat column ── */}
            <div className="flex flex-col flex-1 overflow-hidden">
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
              />
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
