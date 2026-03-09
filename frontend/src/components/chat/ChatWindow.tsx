"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";
import { Bot } from "lucide-react";

interface ChatWindowProps {
  messages: ChatMessage[];
  isLoading?: boolean;
}

export function ChatWindow({ messages, isLoading }: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <div className="w-16 h-16 rounded-2xl bg-cyber-green/10 border border-cyber-green/20 flex items-center justify-center mb-4">
          <Bot className="w-7 h-7 text-cyber-green" />
        </div>
        <h2 className="text-lg font-bold text-cyber-green glow-green-text mb-2">
          CYBER-ENTITY ONLINE
        </h2>
        <p className="text-sm text-text-muted max-w-sm">
          Your AI agent is ready. Ask me to execute commands on remote hosts,
          analyze files, or manage your systems.
        </p>
        <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-md">
          {[
            "What hosts are configured?",
            "Check system info",
            "List running processes",
            "Show disk usage",
          ].map((suggestion) => (
            <button
              key={suggestion}
              className="text-left px-3 py-2 rounded-md text-xs text-text-secondary border border-border-dim hover:border-cyber-green/30 hover:text-cyber-green hover:bg-cyber-green/5 transition-all"
            >
              {suggestion}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {messages.map((msg, i) => (
        <MessageBubble
          key={i}
          message={msg}
          isStreaming={isLoading && i === messages.length - 1 && msg.role === "assistant"}
        />
      ))}
      {isLoading && messages[messages.length - 1]?.role !== "assistant" && (
        <div className="flex gap-3">
          <div className="w-7 h-7 rounded-md bg-cyber-green/10 border border-cyber-green/30 flex items-center justify-center shrink-0">
            <Bot className="w-3.5 h-3.5 text-cyber-green" />
          </div>
          <div className="bg-bg-card border border-border-dim rounded-lg px-4 py-3 flex items-center gap-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-cyber-green animate-bounce"
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
