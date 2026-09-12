"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { authFetch, isAdmin } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function CodexConnectionBanner() {
  const t = useTranslations("settings");
  const [required, setRequired] = useState(false);
  const [admin, setAdmin] = useState(false);

  useEffect(() => {
    setAdmin(isAdmin());
    const controller = new AbortController();
    let pending = false;
    const refresh = async () => {
      if (pending || document.visibilityState === "hidden") return;
      pending = true;
      try {
        const response = await authFetch(`${API_URL}/api/settings/llm/codex/health`, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (response.ok) {
          const result = await response.json();
          if (!controller.signal.aborted) setRequired(result.reconnect_required === true);
        }
      } catch {
        // A failed health request is not evidence of a broken GPT connection.
      } finally {
        pending = false;
      }
    };
    void refresh();
    const timer = setInterval(refresh, 30_000);
    window.addEventListener("ely:codex-health", refresh);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      controller.abort();
      clearInterval(timer);
      window.removeEventListener("ely:codex-health", refresh);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);

  if (!required) return null;
  return (
    <div role="alert" className="shrink-0 border-b border-amber-400/40 bg-amber-400/10 px-4 py-3 text-sm text-text-primary">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-semibold">{t("codexReconnectTitle")}</p>
          <p className="text-xs mt-1">{t(admin ? "codexReconnectMessage" : "codexReconnectMember")}</p>
        </div>
        {admin && (
          <Link href="/settings?tab=modeles#codex-connection" className="rounded-md border border-amber-400/50 px-3 py-2 text-xs font-medium hover:bg-amber-400/15 focus-visible:outline focus-visible:outline-2">
            {t("codexReconnectAction")}
          </Link>
        )}
      </div>
    </div>
  );
}
