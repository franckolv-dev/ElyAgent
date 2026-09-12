"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/chat/ChatWindow.tsx
 * @brief      Chat window — message list and conversation container
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 */

import { useLayoutEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";
import { Zap, Compass, FileText, ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";

// Maps backend tool names → human-readable French labels
const TOOL_LABELS: Record<string, string> = {
  pdf_read:               "Lecture du PDF…",
  pdf_info:               "Analyse du PDF…",
  pdf_analyze_with_vision: "Analyse visuelle du PDF…",
  vision_analyze_image:   "Analyse de l'image…",
  python_execute:         "Exécution du code…",
  search_web:             "Recherche sur le web…",
  navigate:               "Navigation web…",
  get_text:               "Lecture de la page…",
  screenshot:             "Capture d'écran…",
  click:                  "Interaction avec la page…",
  fill:                   "Remplissage du formulaire…",
  google_sheets_create:   "Création du fichier Excel…",
  google_sheets_read:     "Lecture du fichier…",
  google_sheets_append_rows: "Mise à jour du fichier…",
  google_docs_create:     "Création du document…",
  google_docs_read:       "Lecture du document…",
  google_drive_list:      "Parcours de Drive…",
  google_gmail_send:      "Envoi de l'email…",
  google_gmail_list:      "Lecture des emails…",
  google_calendar_create: "Création de l'événement…",
  google_calendar_list:   "Lecture du calendrier…",
  ssh_execute:            "Exécution de la commande…",
  weather_get:            "Récupération de la météo…",
  news_get_headlines:     "Chargement des actualités…",
  generate_image:         "Génération de l'image…",
  translate_text:         "Traduction…",
  notes_create:           "Création de la note…",
  notes_search:           "Recherche dans les notes…",
  trainer_screenshot:     "Capture de l'écran…",
  trainer_start:          "Démarrage de la démonstration…",
};

function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? `${tool.replace(/_/g, " ")}…`;
}

interface ChatWindowProps {
  messages: ChatMessage[];
  isLoading?: boolean;
  onSuggestion?: (text: string) => void;
  streamingContent?: string;
  conversationId?: string;
  activeTool?: string | null;
  /** J4 — regenerate the last assistant reply. */
  onRegenerate?: () => void;
  /** J4 — edit the last user message then resend. */
  onEditMessage?: (newContent: string) => void;
}

export function ChatWindow({ messages, isLoading, onSuggestion, streamingContent, conversationId, activeTool, onRegenerate, onEditMessage }: ChatWindowProps) {
  const t = useTranslations("chat");
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const previousConversation = useRef(conversationId);
  const previousMessageCount = useRef(0);

  // J4 — only the last assistant gets a "regenerate" affordance, and only the
  // last user message gets an "edit" affordance.
  let lastAssistantIdx = -1;
  let lastUserIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (lastAssistantIdx === -1 && messages[i].role === "assistant") lastAssistantIdx = i;
    if (lastUserIdx === -1 && messages[i].role === "user") lastUserIdx = i;
  }

  const SUGGESTIONS = [
    { key: "brief", icon: FileText },
    { key: "action", icon: Zap },
    { key: "mission", icon: Compass },
  ] as const;

  useLayoutEffect(() => {
    const newConversation = previousConversation.current !== conversationId;
    const newMessage = messages.length > previousMessageCount.current;
    if (newConversation || newMessage) followLatest.current = true;
    previousConversation.current = conversationId;
    previousMessageCount.current = messages.length;
    const scroll = scrollRef.current;
    if (!scroll || !followLatest.current) return;
    // Confine scrolling to the message list so the composer stays in place.
    scroll.scrollTop = scroll.scrollHeight;
    const latest = contentRef.current?.querySelector<HTMLElement>("[data-latest-answer]");
    if (!isLoading && newMessage && latest && latest.offsetHeight > scroll.clientHeight - 32) {
      // An answer taller than the viewport opens at its beginning for reading.
      scroll.scrollTop += latest.getBoundingClientRect().top - scroll.getBoundingClientRect().top - 16;
      followLatest.current = false;
    }
  }, [messages, streamingContent, conversationId, isLoading, activeTool]);

  const hasMessages = messages.length > 0;
  useLayoutEffect(() => {
    const scroll = scrollRef.current;
    const content = contentRef.current;
    if (!scroll || !content) return;
    // Images, Markdown and a growing composer can change height after render.
    const observer = new ResizeObserver(() => {
      if (followLatest.current) scroll.scrollTop = scroll.scrollHeight;
    });
    observer.observe(scroll);
    observer.observe(content);
    return () => observer.disconnect();
  }, [hasMessages]);

  if (messages.length === 0) {
    return (
      <div className="chat-empty">
        <div className="chat-orb">
          <span className="ely-mark" aria-hidden="true" />
        </div>
        <h2 className="chat-title">{t("title")}</h2>
        <p className="chat-welcome">{t("welcome")}</p>
        <div className="chat-suggestions">
          {SUGGESTIONS.map(({ key, icon: Icon }) => (
            <button key={key} onClick={() => onSuggestion?.(t(`intents.${key}.prompt`))}
              className="chat-suggestion">
              <span className="suggestion-icon"><Icon size={21} strokeWidth={1.5} /></span>
              <span className="suggestion-copy">
                <span className="chat-suggestion-text">{t(`intents.${key}.title`)}</span>
                <span className="chat-suggestion-description">{t(`intents.${key}.description`)}</span>
              </span>
              <ArrowUpRight size={18} className="suggestion-arrow" />
            </button>
          ))}
        </div>
      </div>
    );
  }

  // ── Date separators — show a divider when day changes between two messages ──
  const formatDateSeparator = (iso: string): string => {
    const d = new Date(iso);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const sameDay = (a: Date, b: Date) =>
      a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() &&
      a.getDate() === b.getDate();
    if (sameDay(d, today)) return "Aujourd'hui";
    if (sameDay(d, yesterday)) return "Hier";
    return d.toLocaleDateString("fr-FR", {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: d.getFullYear() !== today.getFullYear() ? "numeric" : undefined,
    });
  };

  const dayKey = (iso: string | undefined): string => {
    if (!iso) return "";
    const d = new Date(iso);
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  };

  // Colonne de lecture bornée à 760 px, alignée sur le composeur : les deux
  // partagent `.chat-column`, sinon le champ de saisie paraît décalé sous
  // les messages.
  return (
    <div ref={scrollRef} className="chat-scroll flex-1 min-h-0 overflow-y-auto px-6 pt-7 pb-6" onScroll={(event) => {
      const el = event.currentTarget;
      followLatest.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    }}>
      <div ref={contentRef} className="chat-column flex flex-col gap-[18px]">
      {messages.map((msg, i) => {
        // Find the last user message before this assistant message (for feedback context)
        const lastUserMsg = msg.role === "assistant"
          ? messages.slice(0, i).reverse().find((m) => m.role === "user")?.content
          : undefined;
        // Inject a date separator before the first message of each new day
        const prevMsg = i > 0 ? messages[i - 1] : null;
        const showDateSeparator =
          msg.created_at && (!prevMsg || dayKey(prevMsg.created_at) !== dayKey(msg.created_at));
        return (
          <div key={i} data-latest-answer={i === messages.length - 1 && msg.role === "assistant" ? "" : undefined}>
            {showDateSeparator && msg.created_at && (
              <div className="flex items-center my-6">
                <div className="flex-grow border-t border-border-dim"></div>
                <span className="mx-4 text-xs text-text-muted uppercase tracking-wider">
                  {formatDateSeparator(msg.created_at)}
                </span>
                <div className="flex-grow border-t border-border-dim"></div>
              </div>
            )}
            <MessageBubble
              message={msg}
              isStreaming={isLoading && i === messages.length - 1 && msg.role === "assistant"}
              lastUserMessage={lastUserMsg}
              conversationId={conversationId}
              onRegenerate={i === lastAssistantIdx && !isLoading ? onRegenerate : undefined}
              onEdit={i === lastUserIdx ? onEditMessage : undefined}
            />
          </div>
        );
      })}

      {/* Streaming message — tokens arriving in real time */}
      {isLoading && streamingContent && (
        <div className="flex flex-col message assistant streaming">
          <div className="bubble-assistant whitespace-pre-wrap">
            {streamingContent}<span className="animate-pulse">▊</span>
          </div>
        </div>
      )}

      {/* Tool execution indicator — shown when a tool is running */}
      {isLoading && activeTool && (
        <div className="flex flex-col items-end">
          <div
            className="bubble-trace self-end flex-row items-center gap-2.5 text-xs"
            style={{ color: "var(--accent)" }}
          >
            {/* Spinning ring */}
            <span className="w-3.5 h-3.5 rounded-full border-2 border-cyber-cyan/30 border-t-cyber-cyan animate-spin shrink-0" />
            {toolLabel(activeTool)}
          </div>
        </div>
      )}

      {/* Thinking indicator — shown before first token and when no tool is active */}
      {isLoading && !streamingContent && !activeTool && messages[messages.length - 1]?.role !== "assistant" && (
        <div className="flex flex-col items-end">
          <div className="bubble-assistant flex-row items-center gap-1.5 py-4">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1.5 h-1.5 rounded-full"
                style={{
                  background: "var(--text-muted)",
                  animation: "pulse-dot 1s infinite",
                  animationDelay: `${i * 0.15}s`,
                }}
              />
            ))}
          </div>
        </div>
      )}

      </div>
    </div>
  );
}
