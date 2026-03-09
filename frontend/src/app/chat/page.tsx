"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { ChatInput } from "@/components/chat/ChatInput";
import { AgentWebSocket } from "@/lib/websocket";
import type { ChatMessage, WSMessage } from "@/lib/types";

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [wsStatus, setWsStatus] = useState<"connected" | "disconnected" | "connecting">("disconnected");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const wsRef = useRef<AgentWebSocket | null>(null);

  useEffect(() => {
    const ws = new AgentWebSocket();
    wsRef.current = ws;

    ws.onStatus(setWsStatus);

    ws.onMessage((msg: WSMessage) => {
      if (msg.type === "start") {
        setConversationId(msg.conversation_id);
        setIsLoading(true);
      } else if (msg.type === "message" && msg.role === "assistant") {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: msg.content ?? "" },
        ]);
        setIsLoading(false);
      } else if (msg.type === "error") {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Error: ${msg.content}` },
        ]);
        setIsLoading(false);
      }
    });

    ws.connect();
    return () => ws.disconnect();
  }, []);

  const handleSend = useCallback((content: string) => {
    if (!wsRef.current) return;
    setMessages((prev) => [...prev, { role: "user", content }]);
    wsRef.current.send(content, conversationId);
  }, [conversationId]);

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Header wsStatus={wsStatus} />
          <ChatWindow messages={messages} isLoading={isLoading} />
          <ChatInput
            onSend={handleSend}
            isLoading={isLoading}
            disabled={wsStatus === "disconnected"}
          />
        </div>
      </div>
    </AuthGuard>
  );
}
