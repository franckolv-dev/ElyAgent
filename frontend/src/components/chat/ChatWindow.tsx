"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";
import { Bot } from "lucide-react";

interface ChatWindowProps {
  messages: ChatMessage[];
  isLoading?: boolean;
  onSuggestion?: (text: string) => void;
}

const SUGGESTIONS = [
  "Quels hôtes sont configurés ?",
  "Infos système",
  "Lister les processus actifs",
  "Utilisation du disque",
];

export function ChatWindow({ messages, isLoading, onSuggestion }: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
          Votre agent IA est prêt. Demandez-lui d'exécuter des commandes,
          analyser des fichiers ou gérer vos systèmes.
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
      {messages.map((msg, i) => (
        <MessageBubble
          key={i}
          message={msg}
          isStreaming={isLoading && i === messages.length - 1 && msg.role === "assistant"}
        />
      ))}

      {/* Thinking indicator */}
      {isLoading && messages[messages.length - 1]?.role !== "assistant" && (
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
