"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/chat/OnboardingFlow.tsx
 * @brief      Conversational onboarding flow that takes over /chat at first login.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *
 * Behavior :
 *   - At /chat mount, parent checks /api/onboarding/status. If `should_show`
 *     is true, this component is rendered INSTEAD of the regular ChatWindow.
 *   - Renders Éli's questions one after the other with a typing animation
 *     (~500ms) and the user's free-form answers (optimistic UI).
 *   - Buttons: Send, Skip cette question (sends empty answer), Plus tard 🌙
 *     (POST /skip → parent re-renders without overlay).
 *   - When done, displays a final "thanks" then signals parent to swap to
 *     normal ChatWindow (`onComplete`).
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Send, SkipForward, Moon, Loader2, Sparkles } from "lucide-react";
import { api } from "@/lib/api";

interface Question {
  id: string;
  text: string;
  placeholder: string;
  step: number;
  total: number;
  skippable: boolean;
}

interface ChatLine {
  who: "ely" | "user" | "system";
  text: string;
  pending?: boolean;
}

interface Props {
  onComplete: () => void; // called when finished or user clicked "Plus tard"
}

/** Trivial markdown helper for **bold** and bullet lines. Frontend already
 *  ships next-mdx but for the onboarding we keep it inline & dependency-free. */
function renderMarkdown(text: string): React.ReactElement {
  const parts: React.ReactElement[] = [];
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // bullet line ?
    const bullet = line.match(/^\s*[•\-\*]\s+(.*)$/);
    const segments: (string | React.ReactElement)[] = [];
    let raw = bullet ? bullet[1] : line;
    let lastIdx = 0;
    const re = /\*\*([^*]+)\*\*/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(raw)) !== null) {
      if (m.index > lastIdx) segments.push(raw.slice(lastIdx, m.index));
      segments.push(
        <strong key={`b-${i}-${m.index}`} className="text-text-primary">
          {m[1]}
        </strong>,
      );
      lastIdx = m.index + m[0].length;
    }
    if (lastIdx < raw.length) segments.push(raw.slice(lastIdx));
    parts.push(
      bullet ? (
        <div key={i} className="flex gap-2 pl-3">
          <span className="text-cyber-cyan">•</span>
          <span>{segments}</span>
        </div>
      ) : (
        <p key={i} className={line.trim() === "" ? "h-2" : ""}>
          {segments}
        </p>
      ),
    );
  }
  return <>{parts}</>;
}

export function OnboardingFlow({ onComplete }: Props) {
  const [question, setQuestion] = useState<Question | null>(null);
  const [history, setHistory] = useState<ChatLine[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [typing, setTyping] = useState(false);
  const [doneMessage, setDoneMessage] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Fetch the first question on mount
  const fetchNext = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getNextOnboardingQuestion();
      if (data.done || !data.question) {
        // All questions answered → show goodbye then signal parent
        setDoneMessage(true);
        setHistory((h) => [
          ...h,
          {
            who: "ely",
            text:
              "✨ **Parfait, j'ai bien noté tout ça !** Tu peux toujours réviser tes réponses dans **Paramètres → Mon compte → Refaire l'onboarding**.\n\nMaintenant, comment puis-je t'aider ?",
          },
        ]);
        // Auto-redirect to normal chat after 3s
        setTimeout(onComplete, 3000);
        return;
      }
      // Typing animation before showing the question
      setTyping(true);
      setTimeout(() => {
        setQuestion(data.question);
        setHistory((h) => [...h, { who: "ely", text: data.question!.text }]);
        setTyping(false);
      }, 450);
    } catch (e) {
      // If anything fails, fall back to normal chat — onboarding is opt-in
      // and shouldn't block usage.
      console.error("Onboarding next-question failed:", e);
      onComplete();
    } finally {
      setLoading(false);
    }
  }, [onComplete]);

  useEffect(() => {
    fetchNext();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-scroll on new line
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [history, typing]);

  const handleSend = async (skipThisQuestion: boolean = false) => {
    if (!question) return;
    if (!skipThisQuestion && !input.trim()) return;
    setSubmitting(true);
    const text = skipThisQuestion ? "" : input.trim();

    // Optimistic UI : show the user's answer right away (or a placeholder if skipped)
    if (text) {
      setHistory((h) => [...h, { who: "user", text }]);
    } else {
      setHistory((h) => [
        ...h,
        { who: "system", text: "Question passée." },
      ]);
    }
    setInput("");

    try {
      await api.submitOnboardingAnswer(question.id, text);
      setQuestion(null);
      // Small delay then fetch next so the typing animation kicks in naturally
      setTimeout(fetchNext, 300);
    } catch (e) {
      console.error("Submit answer failed:", e);
      setHistory((h) => [
        ...h,
        {
          who: "system",
          text: "⚠️ Erreur d'enregistrement. Réessaie ou clique « Plus tard ».",
        },
      ]);
    } finally {
      setSubmitting(false);
    }
  };

  const handleSkipForLater = async () => {
    setSubmitting(true);
    try {
      await api.skipOnboarding();
      onComplete();
    } catch (e) {
      console.error("Skip failed:", e);
      // Still let the user proceed to chat
      onComplete();
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !submitting) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full bg-bg-primary text-text-primary">
      {/* Header — light progress bar */}
      <div className="px-6 py-3 border-b border-border-dim flex items-center gap-3">
        <Sparkles className="w-4 h-4 text-cyber-cyan" />
        <span className="text-sm font-medium">Apprenons à nous connaître</span>
        {question && (
          <span className="text-xs text-text-muted ml-auto">
            Étape {question.step + 1} / {question.total}
          </span>
        )}
      </div>
      {question && (
        <div className="h-0.5 bg-bg-secondary">
          <div
            className="h-full bg-cyber-cyan transition-all duration-500"
            style={{
              width: `${((question.step + 1) / question.total) * 100}%`,
            }}
          />
        </div>
      )}

      {/* Conversation */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {loading && history.length === 0 && (
          <div className="flex items-center gap-2 text-text-muted text-sm">
            <Loader2 className="w-4 h-4 animate-spin" />
            Préparation…
          </div>
        )}
        {history.map((line, i) => (
          <div
            key={i}
            className={
              "flex " +
              (line.who === "user" ? "justify-end" : "justify-start")
            }
          >
            <div
              className={
                "max-w-2xl rounded-lg px-4 py-3 text-sm leading-relaxed " +
                (line.who === "user"
                  ? "bg-cyber-cyan/15 border border-cyber-cyan/30 text-text-primary"
                  : line.who === "system"
                  ? "text-text-muted text-xs italic"
                  : "bg-bg-secondary border border-border-dim text-text-primary")
              }
            >
              {line.who === "ely" || line.who === "user"
                ? renderMarkdown(line.text)
                : line.text}
            </div>
          </div>
        ))}
        {typing && (
          <div className="flex justify-start">
            <div className="bg-bg-secondary border border-border-dim rounded-lg px-4 py-3 text-sm">
              <span className="inline-flex gap-1">
                <span className="w-1.5 h-1.5 bg-cyber-cyan rounded-full animate-bounce" />
                <span className="w-1.5 h-1.5 bg-cyber-cyan rounded-full animate-bounce [animation-delay:0.15s]" />
                <span className="w-1.5 h-1.5 bg-cyber-cyan rounded-full animate-bounce [animation-delay:0.3s]" />
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Input area */}
      {question && !doneMessage && (
        <div className="border-t border-border-dim p-4 space-y-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={question.placeholder || "Ta réponse…"}
            rows={2}
            disabled={submitting}
            className="w-full bg-bg-secondary border border-border-dim rounded-lg px-3 py-2 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:border-cyber-cyan/50 resize-none"
          />
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {question.skippable && (
                <button
                  type="button"
                  onClick={() => handleSend(true)}
                  disabled={submitting}
                  className="text-xs text-text-muted hover:text-text-primary inline-flex items-center gap-1 px-2 py-1.5 rounded hover:bg-bg-secondary transition"
                  title="Passer cette question"
                >
                  <SkipForward className="w-3.5 h-3.5" />
                  Passer
                </button>
              )}
              <button
                type="button"
                onClick={handleSkipForLater}
                disabled={submitting}
                className="text-xs text-text-muted hover:text-text-primary inline-flex items-center gap-1 px-2 py-1.5 rounded hover:bg-bg-secondary transition"
                title="Reprendre plus tard"
              >
                <Moon className="w-3.5 h-3.5" />
                Plus tard
              </button>
            </div>
            <button
              type="button"
              onClick={() => handleSend(false)}
              disabled={submitting || !input.trim()}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-cyber-cyan/15 border border-cyber-cyan/40 text-cyber-cyan text-sm font-medium hover:bg-cyber-cyan/25 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              {submitting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
              Envoyer
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
