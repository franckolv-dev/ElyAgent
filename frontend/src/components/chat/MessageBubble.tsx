"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/chat/MessageBubble.tsx
 * @brief      Message bubble — individual chat message renderer
 *
 * @author     Franck OLLIVIER <franck.olv@gmail.com>
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

import { motion } from "framer-motion";
import { Bot, User, FileText, Image, FileCode, ThumbsUp, ThumbsDown } from "lucide-react";
import { useState, useCallback } from "react";
import type { Attachment, ChatMessage, ToolImage } from "@/lib/types";
import { api } from "@/lib/api";
import { useTranslations } from "next-intl";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming?: boolean;
  /** The last user message text — sent with feedback for Phase 2 embedding */
  lastUserMessage?: string;
  conversationId?: string;
}

type ImageBlock = { type: "image"; data: string; mime: string; prompt: string };
type ImagesBlock = { type: "images"; items: { data: string; mime: string; title: string }[]; query: string };

/** Icône de fichier selon l'extension. */
function AttachmentFileIcon({ filename }: { filename: string }) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (["jpg", "jpeg", "png", "gif", "webp", "svg"].includes(ext))
    return <Image className="w-3 h-3 shrink-0" />;
  if (["py", "js", "ts", "html", "css", "json", "yaml", "toml", "sh"].includes(ext))
    return <FileCode className="w-3 h-3 shrink-0" />;
  return <FileText className="w-3 h-3 shrink-0" />;
}

// Types MIME autorisés — SVG exclu (peut contenir des <script> → XSS)
const SAFE_MIME = new Set(["image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"]);

function _tryParseImageJSON(raw: string): ImageBlock | ImagesBlock | null {
  try {
    const obj = JSON.parse(raw.trim());
    if (obj.type === "image" && obj.data && obj.mime && SAFE_MIME.has(obj.mime))
      return obj as ImageBlock;
    if (obj.type === "images" && Array.isArray(obj.items)) {
      obj.items = obj.items.filter((img: { mime?: string }) => img.mime && SAFE_MIME.has(img.mime));
      if (obj.items.length > 0) return obj as ImagesBlock;
    }
  } catch { /* not JSON */ }
  return null;
}

interface ParsedContent {
  text: string;
  imageBlock: ImageBlock | ImagesBlock | null;
}

/** Tente de parser un bloc image(s) JSON retourné par generate_image, qrcode_generate, etc.
 *  Gère deux cas :
 *  1. Tout le contenu est du JSON image (cas original)
 *  2. Du texte suivi d'un JSON image (QR code / Imagen via sous-agent)
 */
function parseContent(content: string): ParsedContent {
  const trimmed = content.trim();

  // Cas 1 : tout le contenu est un JSON image
  if (trimmed.startsWith("{")) {
    const imageBlock = _tryParseImageJSON(trimmed);
    if (imageBlock) return { text: "", imageBlock };
  }

  // Cas 2 : JSON image à la fin du contenu (après texte)
  const jsonStart = trimmed.lastIndexOf("\n{");
  if (jsonStart !== -1) {
    const jsonPart = trimmed.slice(jsonStart + 1); // skip the \n
    const imageBlock = _tryParseImageJSON(jsonPart);
    if (imageBlock) return { text: trimmed.slice(0, jsonStart).trim(), imageBlock };
  }

  return { text: content, imageBlock: null };
}

/** Format a ISO date string to a short, human-readable time label.
 *  - Same day  → "14:37"
 *  - Other day → "24/03 14:37"
 */
function formatTimestamp(iso: string | undefined): string | null {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate();
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    if (sameDay) return `${hh}:${mm}`;
    const dd = String(d.getDate()).padStart(2, "0");
    const mo = String(d.getMonth() + 1).padStart(2, "0");
    return `${dd}/${mo} ${hh}:${mm}`;
  } catch {
    return null;
  }
}

export function MessageBubble({ message, isStreaming, lastUserMessage, conversationId }: MessageBubbleProps) {
  const t = useTranslations("messageBubble");
  const isUser = message.role === "user";
  const { text: parsedText, imageBlock } = !isUser
    ? parseContent(message.content)
    : { text: message.content, imageBlock: null };
  const [feedbackSent, setFeedbackSent] = useState<1 | -1 | null>(null);

  function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} ${t("bytes")}`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} ${t("kilobytes")}`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} ${t("megabytes")}`;
  }

  const sendFeedback = useCallback(async (rating: 1 | -1) => {
    if (feedbackSent !== null || !conversationId) return;
    setFeedbackSent(rating);
    try {
      await api.submitFeedback({
        conversation_id: conversationId,
        user_message: (lastUserMessage ?? "").slice(0, 500),
        rating,
        model_used: message.model_used,
        routing_score: message.routing_score,
      });
    } catch {
      // Silent — feedback is best-effort
    }
  }, [feedbackSent, conversationId, lastUserMessage, message.model_used, message.routing_score]);

  // Derive a short label for the model badge
  const modelLabel = message.model_used?.startsWith("slm:")
    ? "local"
    : message.model_used?.startsWith("llm:")
    ? null  // don't show badge for LLM (default, expected)
    : null;

  const timestamp = formatTimestamp(message.created_at);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex flex-col gap-0.5 ${isUser ? "items-end" : "items-start"}`}
    >
    <div className={`flex gap-3 w-full ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar icon */}
      <div
        className={`w-7 h-7 rounded-md flex items-center justify-center shrink-0 mt-0.5 ${
          isUser
            ? "bg-cyber-blue/10 border border-cyber-blue/30"
            : "bg-cyber-cyan/10 border border-cyber-cyan/30"
        }`}
      >
        {isUser ? (
          <User className="w-3.5 h-3.5 text-cyber-blue" />
        ) : (
          <Bot className="w-3.5 h-3.5 text-cyber-cyan" />
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
        {/* Attachment chips on user messages */}
        {isUser && message.attachments && message.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {message.attachments.map((att: Attachment) => (
              <div
                key={att.file_id}
                className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-cyber-blue/10 border border-cyber-blue/20 text-[11px] text-text-muted max-w-[180px]"
                title={att.filename}
              >
                <AttachmentFileIcon filename={att.filename} />
                <span className="truncate">{att.filename}</span>
                <span className="shrink-0 opacity-60">{formatSize(att.size)}</span>
              </div>
            ))}
          </div>
        )}

        {(
          <div className="text-sm break-words prose-cyber">
            {parsedText && (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children }) => (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-cyber-cyan underline hover:text-cyber-cyan/70 transition-colors"
                    >
                      {children}
                    </a>
                  ),
                  p: ({ children }) => (
                    <p className="mb-2 last:mb-0 whitespace-pre-wrap">{children}</p>
                  ),
                  code: ({ children, className }) => {
                    const isBlock = className?.includes("language-");
                    return isBlock ? (
                      <pre className="bg-bg-primary/60 border border-border-dim rounded p-2 overflow-x-auto my-2">
                        <code className="font-mono text-xs text-text-secondary">{children}</code>
                      </pre>
                    ) : (
                      <code className="font-mono text-xs bg-bg-primary/60 px-1 py-0.5 rounded text-cyber-cyan/80">{children}</code>
                    );
                  },
                  ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-0.5">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-0.5">{children}</ol>,
                  li: ({ children }) => <li className="text-sm">{children}</li>,
                  strong: ({ children }) => <strong className="font-semibold text-text-primary">{children}</strong>,
                  h1: ({ children }) => <h1 className="text-base font-bold text-cyber-cyan mb-1">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-sm font-bold text-cyber-cyan mb-1">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-sm font-semibold text-text-primary mb-1">{children}</h3>,
                }}
              >
                {parsedText}
              </ReactMarkdown>
            )}
            {imageBlock?.type === "image" && (
              <div className="flex flex-col gap-2 mt-1">
                <img
                  src={`data:${imageBlock.mime};base64,${imageBlock.data}`}
                  alt={imageBlock.prompt ?? "image"}
                  className="rounded-md max-w-full border border-cyber-cyan/20"
                  style={{ maxHeight: "400px", objectFit: "contain" }}
                />
                {imageBlock.prompt && (
                  <p className="text-xs text-text-muted italic">{imageBlock.prompt}</p>
                )}
              </div>
            )}
            {imageBlock?.type === "images" && (
              <div className="flex flex-col gap-2 mt-1">
                <p className="text-xs text-text-muted mb-1">{t("imagesFor", { query: imageBlock.query })}</p>
                <div className="grid grid-cols-2 gap-2">
                  {imageBlock.items.map((img, i) => (
                    <div key={i} className="flex flex-col gap-1">
                      <img
                        src={`data:${img.mime};base64,${img.data}`}
                        alt={img.title}
                        className="rounded-md w-full border border-cyber-cyan/20"
                        style={{ maxHeight: "180px", objectFit: "cover" }}
                      />
                      <p className="text-xs text-text-muted truncate">{img.title}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {isStreaming && (
              <span className="inline-block w-2 h-4 bg-cyber-cyan ml-0.5 animate-pulse" />
            )}
          </div>
        )}

        {/* Tool-generated images (QR codes, generated images, etc.) */}
        {!isUser && message.toolImages && message.toolImages.length > 0 && (
          <div className="flex flex-col gap-2 mt-2">
            {message.toolImages.map((img: ToolImage, i: number) => (
              <img
                key={i}
                src={`data:${img.mime};base64,${img.data}`}
                alt={img.prompt ?? "generated image"}
                className="rounded-md max-w-xs border border-cyber-cyan/20"
                style={{ maxHeight: "300px", objectFit: "contain" }}
              />
            ))}
          </div>
        )}

        {/* Feedback + model badge — assistant messages only, not while streaming */}
        {!isUser && !isStreaming && (
          <div className="flex items-center gap-2 mt-2 pt-1.5 border-t border-border-dim/40">
            {modelLabel && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/20 font-mono">
                {modelLabel}
              </span>
            )}
            <div className="flex items-center gap-1 ml-auto">
              <button
                onClick={() => sendFeedback(1)}
                disabled={feedbackSent !== null}
                title={t("goodResponse")}
                className={`p-1 rounded transition-colors ${
                  feedbackSent === 1
                    ? "text-cyber-cyan"
                    : feedbackSent !== null
                    ? "text-text-muted/30 cursor-default"
                    : "text-text-muted hover:text-cyber-cyan"
                }`}
              >
                <ThumbsUp className="w-3 h-3" />
              </button>
              <button
                onClick={() => sendFeedback(-1)}
                disabled={feedbackSent !== null}
                title={t("badResponse")}
                className={`p-1 rounded transition-colors ${
                  feedbackSent === -1
                    ? "text-red-400"
                    : feedbackSent !== null
                    ? "text-text-muted/30 cursor-default"
                    : "text-text-muted hover:text-red-400"
                }`}
              >
                <ThumbsDown className="w-3 h-3" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
    {timestamp && (
      <span
        className={`text-[10px] text-text-muted/50 font-mono px-1 ${
          isUser ? "pr-10" : "pl-10"
        }`}
      >
        {timestamp}
      </span>
    )}
    </motion.div>
  );
}
