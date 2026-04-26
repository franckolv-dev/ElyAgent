"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/LangSwitcher.tsx
 * @brief      Language switcher — toggle UI locale + persist user preference
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 *             https://polyformproject.org/licenses/strict/1.0.0/
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 */
import { useLocale } from "next-intl";
import { useTransition, useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { Languages } from "lucide-react";
import { setLocale } from "@/lib/locale";
import { api } from "@/lib/api";

const FLAGS: Record<string, string> = { fr: "🇫🇷", en: "🇬🇧" };
const LABELS: Record<string, string> = { fr: "FR", en: "EN" };

export function LangSwitcher() {
  const current = useLocale() as "fr" | "en";
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; right: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Anchor the portal-rendered dropdown to the trigger button — recompute
  // on open and on window resize so it stays glued visually.
  useEffect(() => {
    if (!open) return;
    function recalc() {
      const rect = buttonRef.current?.getBoundingClientRect();
      if (!rect) return;
      setCoords({
        top: rect.bottom + 4,
        right: window.innerWidth - rect.right,
      });
    }
    recalc();
    window.addEventListener("resize", recalc);
    window.addEventListener("scroll", recalc, true);
    return () => {
      window.removeEventListener("resize", recalc);
      window.removeEventListener("scroll", recalc, true);
    };
  }, [open]);

  function pick(next: "fr" | "en") {
    setOpen(false);
    if (next === current) return;
    startTransition(async () => {
      // 1. Persist UI cookie (server action) — controls next-intl on next render
      await setLocale(next);
      // 2. Best-effort sync to backend so Éli replies in the same language
      try {
        await api.updateUserPreferences({ language: next });
      } catch {
        // Silent: UI switch must work even if backend sync fails
      }
      // 3. Refresh server components to re-render with new locale
      router.refresh();
    });
  }

  // Portal target — rendered to <body> to escape Three.js canvas stacking
  // contexts (the avatar panel uses WebGL which creates its own context,
  // so a regular z-index on the dropdown gets swallowed).
  const dropdown = open && coords && typeof document !== "undefined"
    ? createPortal(
        <>
          {/* Click-outside backdrop */}
          <div
            className="fixed inset-0"
            style={{ zIndex: 9998 }}
            onClick={() => setOpen(false)}
            aria-hidden
          />
          <div
            className="fixed min-w-[140px] bg-bg-secondary border border-border-dim rounded shadow-lg overflow-hidden"
            style={{
              top: coords.top,
              right: coords.right,
              zIndex: 9999,
            }}
            role="menu"
          >
            {(["fr", "en"] as const).map((loc) => (
              <button
                key={loc}
                type="button"
                role="menuitem"
                onClick={() => pick(loc)}
                disabled={pending}
                className={`w-full px-3 py-2 text-left text-xs flex items-center gap-2 hover:bg-bg-tertiary transition-colors ${
                  loc === current ? "text-cyber-cyan" : "text-text-secondary"
                }`}
              >
                <span aria-hidden>{FLAGS[loc]}</span>
                <span>{loc === "fr" ? "Français" : "English"}</span>
                {loc === current && <span className="ml-auto">●</span>}
              </button>
            ))}
          </div>
        </>,
        document.body,
      )
    : null;

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={pending}
        title={current === "fr" ? "Changer de langue" : "Change language"}
        aria-label="Language switcher"
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-1.5 px-2 py-1 rounded border border-border-dim hover:border-cyber-cyan/40 text-xs text-text-secondary hover:text-text-primary transition-colors disabled:opacity-50"
      >
        <Languages className="w-3.5 h-3.5" />
        <span className="font-medium">{LABELS[current]}</span>
        <span aria-hidden>{FLAGS[current]}</span>
      </button>
      {dropdown}
    </div>
  );
}
