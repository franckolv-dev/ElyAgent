"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";
import { Bot } from "lucide-react";
import { useTranslations } from "next-intl";

interface ChatWindowProps {
  messages: ChatMessage[];
  isLoading?: boolean;
  onSuggestion?: (text: string) => void;
  streamingContent?: string;
  conversationId?: string;
}

export function ChatWindow({ messages, isLoading, onSuggestion, streamingContent, conversationId }: ChatWindowProps) {
  const t = useTranslations("chat");
  const bottomRef = useRef<HTMLDivElement>(null);

  const SUGGESTIONS = [
    t("suggestions.hosts"),
    t("suggestions.sysinfo"),
    t("suggestions.disk"),
  ];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <div className="w-16 h-16 rounded-2xl bg-cyber-cyan/10 border border-cyber-cyan/20 flex items-center justify-center mb-4">
          <Bot className="w-7 h-7 text-cyber-cyan" />
        </div>
        <h2 className="text-lg font-bold text-cyber-cyan glow-cyan-text mb-2">
          ELY ONLINE
        </h2>
        <p className="text-sm text-text-muted max-w-sm">
          {t("welcome")}
        </p>
        <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-md">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => onSuggestion?.(s)}
              className="text-left px-3 py-2 rounded-md text-xs text-text-secondary border border-border-dim hover:border-cyber-cyan/30 hover:text-cyber-cyan hover:bg-cyber-cyan/5 transition-all"
            >
              {s}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {messages.map((msg, i) => {
        // Find the last user message before this assistant message (for feedback context)
        const lastUserMsg = msg.role === "assistant"
          ? messages.slice(0, i).reverse().find((m) => m.role === "user")?.content
          : undefined;
        return (
          <MessageBubble
            key={i}
            message={msg}
            isStreaming={isLoading && i === messages.length - 1 && msg.role === "assistant"}
            lastUserMessage={lastUserMsg}
            conversationId={conversationId}
          />
        );
      })}

      {/* Streaming message — tokens arriving in real time */}
      {isLoading && streamingContent && (
        <div className="flex gap-3 message assistant streaming">
          <div className="w-7 h-7 rounded-md bg-cyber-cyan/10 border border-cyber-cyan/30 flex items-center justify-center shrink-0">
            <Bot className="w-3.5 h-3.5 text-cyber-cyan" />
          </div>
          <div className="bg-bg-card border border-border-dim rounded-lg px-4 py-3 text-sm text-text-primary whitespace-pre-wrap max-w-prose">
            {streamingContent}<span className="animate-pulse">▊</span>
          </div>
        </div>
      )}

      {/* Thinking indicator — shown only before first token arrives */}
      {isLoading && !streamingContent && messages[messages.length - 1]?.role !== "assistant" && (
        <div className="flex gap-3">
          <div className="w-7 h-7 rounded-md bg-cyber-cyan/10 border border-cyber-cyan/30 flex items-center justify-center shrink-0">
            <Bot className="w-3.5 h-3.5 text-cyber-cyan" />
          </div>
          <div className="bg-bg-card border border-border-dim rounded-lg px-4 py-3 flex items-center gap-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-cyber-cyan animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }}
              />
            ))}
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
