"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { AuthGuard }          from "@/components/layout/AuthGuard";
import { Sidebar }             from "@/components/layout/Sidebar";
import { Header }              from "@/components/layout/Header";
import { ChatWindow }          from "@/components/chat/ChatWindow";
import { ChatInput }           from "@/components/chat/ChatInput";
import { AvatarPanel }         from "@/components/avatar/AvatarPanel";
import { LiveBrowserPanel }    from "@/components/browser/LiveBrowserPanel";
import { AgentWebSocket }      from "@/lib/websocket";
import type { Attachment, BrowserFrame, ChatMessage, WSMessage } from "@/lib/types";

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

// ── Page ─────────────────────────────────────────────────────────────────
export default function ChatPage() {
  const [messages,        setMessages]        = useState<ChatMessage[]>([]);
  const [isLoading,       setIsLoading]       = useState(false);
  const [wsStatus,        setWsStatus]        = useState<"connected" | "disconnected" | "connecting">("disconnected");
  const [conversationId,  setConversationId]  = useState<string | undefined>();
  const [lastWsMessage,   setLastWsMessage]   = useState<WSMessage | null>(null);
  const [suggestion,      setSuggestion]      = useState<string>("");
  const [streamingContent,setStreamingContent]= useState<string>("");
  const [browserFrame,    setBrowserFrame]    = useState<BrowserFrame | null>(null);
  const wsRef = useRef<AgentWebSocket | null>(null);

  const { width: avatarWidth, onHandleMouseDown } = usePanelResize();

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
      } else if (msg.type === "token") {
        setStreamingContent((prev) => prev + (msg.content ?? ""));
      } else if (msg.type === "message" && msg.role === "assistant") {
        setMessages((prev) => [...prev, {
          role: "assistant",
          content: msg.content ?? "",
          model_used: msg.model_used,
          routing_score: msg.routing_score,
        }]);
        setStreamingContent("");
        setIsLoading(false);
      } else if (msg.type === "error") {
        setMessages((prev) => [...prev, { role: "assistant", content: `Erreur : ${msg.content}` }]);
        setStreamingContent("");
        setIsLoading(false);
      } else if (msg.type === "browser_frame" && msg.data) {
        setBrowserFrame({ data: msg.data, url: msg.url ?? "", title: msg.title ?? "" });
      }
    });

    ws.connect();
    return () => ws.disconnect();
  }, []);

  const handleSend = useCallback((content: string, attachments?: Attachment[]) => {
    if (!wsRef.current) return;
    setMessages((prev) => [...prev, { role: "user", content, attachments }]);
    wsRef.current.send(content, conversationId, attachments);
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
                title="Redimensionner le panneau"
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
