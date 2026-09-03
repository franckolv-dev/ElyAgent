"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/chat/ChatWindow.tsx
 * @brief      Chat window — message list and conversation container
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *            https://www.elastic.co/licensing/elastic-license
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";
import { Zap } from "lucide-react";
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
  const bottomRef = useRef<HTMLDivElement>(null);

  // J4 — only the last assistant gets a "regenerate" affordance, and only the
  // last user message gets an "edit" affordance.
  let lastAssistantIdx = -1;
  let lastUserIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (lastAssistantIdx === -1 && messages[i].role === "assistant") lastAssistantIdx = i;
    if (lastUserIdx === -1 && messages[i].role === "user") lastUserIdx = i;
  }

  const SUGGESTIONS = [
    t("suggestions.hosts"),
    t("suggestions.sysinfo"),
    t("suggestions.disk"),
    t("suggestions.unreadEmails"),
  ];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: streamingContent ? "auto" : "smooth" });
  }, [messages, streamingContent]);

  if (messages.length === 0) {
    return (
      <div className="chat-empty">
        <div className="chat-orb">
          <Zap size={26} />
        </div>
        <h2 className="chat-title">{t("title")}</h2>
        <p className="chat-welcome">{t("welcome")}</p>
        <div className="chat-suggestions">
          {SUGGESTIONS.map((s, i) => (
            <button
              key={s}
              onClick={() => onSuggestion?.(s)}
              className="chat-suggestion"
            >
              <span className="chat-suggestion-tag">SUGGESTION 0{i + 1}</span>
              <span className="chat-suggestion-text">{s}</span>
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
    <div className="flex-1 overflow-y-auto px-6 pt-7 pb-3">
      <div className="chat-column flex flex-col gap-[18px]">
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
          <div key={i}>
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
        <div className="flex flex-col">
          <div
            className="bubble-trace self-start flex-row items-center gap-2.5 text-xs"
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
        <div className="flex flex-col">
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

      <div ref={bottomRef} />
      </div>
    </div>
  );
}
