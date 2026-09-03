/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/HitlBell.tsx
 * @brief      Bell icon with pending HITL approvals — badge + dropdown
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, Check, X, Ban } from "lucide-react";
import { api } from "@/lib/api";

interface PendingAction {
  action_id: string;
  description: string;
  created_at: string;
}

const POLL_INTERVAL_MS = 5000;

export default function HitlBell() {
  const [pending, setPending] = useState<PendingAction[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const refresh = useCallback(async () => {
    try {
      const items = await api.hitlPending();
      setPending(items);
    } catch {
      // Auth not ready / network blip — silent retry on next tick
    }
  }, []);

  // Polling
  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  // Refresh when window/tab regains focus (instant catch-up)
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("focus", refresh);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("focus", refresh);
    };
  }, [refresh]);

  // Close dropdown on outside click
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(target) &&
        buttonRef.current &&
        !buttonRef.current.contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const resolve = async (
    actionId: string,
    decision: "allow" | "allow_for_task" | "allow_always" | "deny" | "ban"
  ) => {
    setBusy(actionId);
    try {
      await api.hitlResolve(actionId, decision);
      // Optimistic UI removal — refresh to confirm
      setPending((p) => p.filter((a) => a.action_id !== actionId));
      await refresh();
    } catch (e) {
      console.error("HITL resolve failed:", e);
      await refresh();
    } finally {
      setBusy(null);
    }
  };

  const count = pending.length;

  return (
    <div className="hitl-bell-wrap">
      <button
        ref={buttonRef}
        className="icon-btn hitl-bell-btn"
        title={
          count === 0
            ? "Aucune validation en attente"
            : `${count} validation${count > 1 ? "s" : ""} en attente`
        }
        onClick={() => setOpen((v) => !v)}
        aria-label="Notifications HITL"
        aria-expanded={open}
      >
        <Bell size={15} />
        {count > 0 && (
          <span className="hitl-bell-badge" aria-hidden="true">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {open && (
        <div ref={dropdownRef} className="hitl-bell-dropdown" role="dialog">
          <div className="hitl-bell-dropdown-header">
            <strong>Validations en attente</strong>
            <span className="hitl-bell-count">
              {count} pendante{count > 1 ? "s" : ""}
            </span>
          </div>

          {count === 0 ? (
            <div className="hitl-bell-empty">
              Aucune action ne nécessite votre validation.
            </div>
          ) : (
            <ul className="hitl-bell-list">
              {pending.map((a) => (
                <li key={a.action_id} className="hitl-bell-item">
                  <div className="hitl-bell-desc">{a.description}</div>
                  <div className="hitl-bell-meta">
                    {new Date(a.created_at).toLocaleString()}
                  </div>
                  {/* 2×2 grid (2026-05-23 redesign — adds "Toujours autoriser"
                      symmetric to "Toujours interdire", so a user with
                      recurring tasks doesn't have to re-approve the same
                      tool 15×/day). */}
                  <div
                    className="hitl-bell-actions"
                    style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}
                  >
                    <button
                      className="hitl-act hitl-act-allow"
                      disabled={busy === a.action_id}
                      onClick={() => resolve(a.action_id, "allow")}
                      title="Autoriser cette action une fois"
                    >
                      <Check size={12} /> Autoriser
                    </button>
                    <button
                      className="hitl-act hitl-act-allow"
                      disabled={busy === a.action_id}
                      onClick={() => resolve(a.action_id, "allow_for_task")}
                      title="Autoriser ce type d'action pour le reste de cette tâche, sans redemander (éphémère, non permanent)"
                    >
                      <Check size={12} /> Pour cette tâche
                    </button>
                    <button
                      className="hitl-act hitl-act-allow"
                      disabled={busy === a.action_id}
                      onClick={() => resolve(a.action_id, "allow_always")}
                      title="Autoriser et ne plus jamais demander pour cette action"
                    >
                      <Check size={12} /> Toujours autoriser
                    </button>
                    <button
                      className="hitl-act hitl-act-deny"
                      disabled={busy === a.action_id}
                      onClick={() => resolve(a.action_id, "deny")}
                      title="Refuser cette action"
                    >
                      <X size={12} /> Refuser
                    </button>
                    <button
                      className="hitl-act hitl-act-ban"
                      disabled={busy === a.action_id}
                      onClick={() => resolve(a.action_id, "ban")}
                      title="Refuser et bloquer définitivement cette action"
                    >
                      <Ban size={12} /> Toujours interdire
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
