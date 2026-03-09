"use client";

import { motion } from "framer-motion";
import { Bot, User } from "lucide-react";
import type { ChatMessage } from "@/lib/types";

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming?: boolean;
}

export function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      {/* Avatar */}
      <div
        className={`w-7 h-7 rounded-md flex items-center justify-center shrink-0 mt-0.5 ${
          isUser
            ? "bg-cyber-blue/10 border border-cyber-blue/30"
            : "bg-cyber-green/10 border border-cyber-green/30"
        }`}
      >
        {isUser ? (
          <User className="w-3.5 h-3.5 text-cyber-blue" />
        ) : (
          <Bot className="w-3.5 h-3.5 text-cyber-green" />
        )}
      </div>

      {/* Bubble */}
      <div
        className={`max-w-[75%] rounded-lg px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-cyber-blue/10 border border-cyber-blue/20 text-text-primary"
            : "bg-bg-card border border-border-dim text-text-primary"
        }`}
      >
        <pre className="whitespace-pre-wrap font-mono text-sm break-words">
          {message.content}
          {isStreaming && (
            <span className="inline-block w-2 h-4 bg-cyber-green ml-0.5 animate-pulse" />
          )}
        </pre>
      </div>
    </motion.div>
  );
}
