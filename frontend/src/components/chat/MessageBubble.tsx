"use client";

import { motion } from "framer-motion";
import { Bot, User, FileText, Image, FileCode } from "lucide-react";
import type { Attachment, ChatMessage } from "@/lib/types";

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming?: boolean;
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

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
}

/** Tente de parser un bloc image(s) JSON retourné par generate_image ou browser_search_images. */
function parseImageBlock(content: string): ImageBlock | ImagesBlock | null {
  const trimmed = content.trim();
  if (!trimmed.startsWith("{")) return null;
  try {
    const obj = JSON.parse(trimmed);
    if (obj.type === "image"  && obj.data && obj.mime) return obj as ImageBlock;
    if (obj.type === "images" && Array.isArray(obj.items)) return obj as ImagesBlock;
  } catch { /* not JSON */ }
  return null;
}

export function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const imageBlock = !isUser ? parseImageBlock(message.content) : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
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

        {imageBlock?.type === "image" ? (
          /* Image unique — Gemini Imagen ou screenshot */
          <div className="flex flex-col gap-2">
            <img
              src={`data:${imageBlock.mime};base64,${imageBlock.data}`}
              alt={imageBlock.prompt}
              className="rounded-md max-w-full border border-cyber-cyan/20"
              style={{ maxHeight: "400px", objectFit: "contain" }}
            />
            <p className="text-xs text-text-muted italic">{imageBlock.prompt}</p>
          </div>
        ) : imageBlock?.type === "images" ? (
          /* Grille d'images — recherche web */
          <div className="flex flex-col gap-2">
            <p className="text-xs text-text-muted mb-1">Images pour « {imageBlock.query} »</p>
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
        ) : (
          <pre className="whitespace-pre-wrap font-mono text-sm break-words">
            {message.content}
            {isStreaming && (
              <span className="inline-block w-2 h-4 bg-cyber-cyan ml-0.5 animate-pulse" />
            )}
          </pre>
        )}
      </div>
    </motion.div>
  );
}
