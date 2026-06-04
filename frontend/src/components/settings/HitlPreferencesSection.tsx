"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/settings/HitlPreferencesSection.tsx
 * @brief      Per-user HITL toggles (which tools require confirmation)
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Lock, Loader2, ShieldCheck, Bell, ChevronDown } from "lucide-react";
import { api } from "@/lib/api";

interface HitlPref {
  tool_name: string;
  requires_confirmation: boolean;
  locked: boolean;
  description: string | null;
}

interface ChannelOption {
  value: string;
  label: string;
  available: boolean;
  icon: string;
}

interface HitlChannelInfo {
  preferred_channel: string;
  available_channels: ChannelOption[];
}

export function HitlPreferencesSection() {
  const t = useTranslations("settings.hitl");
  const [prefs, setPrefs] = useState<HitlPref[]>([]);
  const [channel, setChannel] = useState<HitlChannelInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [savingTool, setSavingTool] = useState<string | null>(null);
  const [savingChannel, setSavingChannel] = useState(false);
  // Collapsible category accordions — default collapsed so the page is a short
  // list of headers (no scrolling to reach "Bureau / fichiers locaux").
  const [openCats, setOpenCats] = useState<Record<string, boolean>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [data, ch] = await Promise.all([
        api.listHitlPreferences(),
        api.getHitlChannel(),
      ]);
      setPrefs(data);
      setChannel(ch);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  const handleChannelChange = async (newChannel: string) => {
    if (!channel || newChannel === channel.preferred_channel) return;
    setSavingChannel(true);
    setError("");
    const previous = channel;
    setChannel({ ...channel, preferred_channel: newChannel }); // optimistic
    try {
      const updated = await api.updateHitlChannel(newChannel);
      setChannel(updated);
    } catch (e) {
      setChannel(previous); // rollback
      setError(e instanceof Error ? e.message : t("toggleFailed"));
    } finally {
      setSavingChannel(false);
    }
  };

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleToggle = async (pref: HitlPref) => {
    if (pref.locked) return;
    setSavingTool(pref.tool_name);
    setError("");
    // Optimistic UI
    setPrefs((cur) =>
      cur.map((p) =>
        p.tool_name === pref.tool_name
          ? { ...p, requires_confirmation: !p.requires_confirmation }
          : p,
      ),
    );
    try {
      await api.updateHitlPreference(pref.tool_name, !pref.requires_confirmation);
    } catch (e) {
      // Roll back on error
      setPrefs((cur) =>
        cur.map((p) =>
          p.tool_name === pref.tool_name
            ? { ...p, requires_confirmation: pref.requires_confirmation }
            : p,
        ),
      );
      setError(e instanceof Error ? e.message : t("toggleFailed"));
    } finally {
      setSavingTool(null);
    }
  };

  // Group prefs by category prefix for nicer rendering
  const grouped: Record<string, HitlPref[]> = {};
  for (const p of prefs) {
    const prefix = p.tool_name.split("_")[0];
    (grouped[prefix] = grouped[prefix] || []).push(p);
  }
  const groupOrder = ["gmail", "calendar", "drive", "docs", "sheets", "tasks", "contacts", "ssh", "desktop", "os", "whatsapp", "mcp", "vault", "save"];
  const groupLabels: Record<string, string> = {
    gmail: "Gmail",
    calendar: "Google Calendar",
    drive: "Google Drive",
    docs: "Google Docs",
    sheets: "Google Sheets",
    tasks: "Google Tasks",
    contacts: "Google Contacts",
    ssh: "SSH",
    desktop: "Bureau / fichiers locaux",
    os: "Contrôle OS",
    whatsapp: "WhatsApp",
    mcp: "MCP",
    vault: "Coffre-fort",
    save: "Mémoire / contraintes",
  };
  // Render EVERY present category — known ones in groupOrder, then any extra
  // prefix appended (so no tool is silently dropped, as os_/whatsapp_/mcp_/
  // save_ were before — bug found 2026-06-04).
  const orderedGroups = [
    ...groupOrder.filter((g) => grouped[g]?.length),
    ...Object.keys(grouped).filter((g) => !groupOrder.includes(g)).sort(),
  ];

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-2">
        <ShieldCheck className="w-4 h-4 text-cyber-cyan" />
        <h2 className="text-sm font-medium text-text-primary">{t("title")}</h2>
      </div>
      <p className="text-xs text-text-muted">{t("intro")}</p>

      {/* Canal HITL préféré — fix #18 (mai 2026)
          Permet de choisir un canal unique pour les notifications HITL
          au lieu du broadcast (Telegram + ntfy + Android + ...). */}
      {channel && (
        <div className="bg-bg-secondary border border-border-dim rounded-lg p-3">
          <div className="flex items-center gap-2 mb-2">
            <Bell className="w-3.5 h-3.5 text-cyber-cyan" />
            <h3 className="text-xs font-semibold text-text-primary">
              Canal de notification HITL
            </h3>
            {savingChannel && (
              <Loader2 className="w-3 h-3 animate-spin text-text-muted" />
            )}
          </div>
          <p className="text-[11px] text-text-muted mb-3">
            Choisis le canal qui doit recevoir les demandes de validation. Le Web UI reste
            toujours notifié pour synchroniser le chat.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {channel.available_channels.map((ch) => {
              const selected = channel.preferred_channel === ch.value;
              const disabled = !ch.available || savingChannel;
              return (
                <button
                  key={ch.value}
                  type="button"
                  disabled={disabled && !selected}
                  onClick={() => handleChannelChange(ch.value)}
                  className={
                    "flex items-center gap-2 px-3 py-2 rounded text-xs border transition " +
                    (selected
                      ? "border-cyber-cyan/60 bg-cyber-cyan/10 text-cyber-cyan"
                      : ch.available
                      ? "border-border-dim hover:border-cyber-cyan/40 hover:bg-bg-tertiary/40 text-text-primary"
                      : "border-border-dim/50 bg-bg-tertiary/20 text-text-muted opacity-50 cursor-not-allowed")
                  }
                  title={
                    ch.available
                      ? selected
                        ? "Canal actuellement sélectionné"
                        : "Cliquer pour sélectionner"
                      : "Canal non configuré pour ton compte"
                  }
                >
                  <span aria-hidden="true">{ch.icon}</span>
                  <span className="flex-1 text-left">{ch.label}</span>
                  {!ch.available && (
                    <span className="text-[9px] uppercase tracking-wider px-1 rounded bg-bg-tertiary text-text-muted">
                      non lié
                    </span>
                  )}
                  {selected && <span className="text-[10px]">✓</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {error && (
        <div className="text-xs text-cyber-red border border-cyber-red/30 bg-cyber-red/5 rounded px-3 py-2">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-text-muted py-3">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span>{t("loading")}</span>
        </div>
      ) : (
        <div className="space-y-5">
          {orderedGroups.map((g) => {
            const catOpen = openCats[g] ?? false;
            return (
              <div key={g}>
                <button
                  type="button"
                  onClick={() => setOpenCats((s) => ({ ...s, [g]: !catOpen }))}
                  aria-expanded={catOpen}
                  className="w-full flex items-center gap-2 text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2"
                >
                  <ChevronDown
                    className={`w-3.5 h-3.5 transition-transform ${catOpen ? "" : "-rotate-90"}`}
                  />
                  <span className="flex-1 text-left">{groupLabels[g] ?? g}</span>
                  <span className="normal-case text-text-muted/60">{grouped[g].length}</span>
                </button>
                {catOpen && (
                <div className="bg-bg-secondary border border-border-dim rounded-lg divide-y divide-border-dim mb-2">
                  {grouped[g].map((p) => (
                    <div
                      key={p.tool_name}
                      className="flex items-center gap-3 px-3 py-2.5 hover:bg-bg-tertiary/30"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <code className="text-xs font-mono text-text-primary truncate">
                            {p.tool_name}
                          </code>
                          {p.locked && (
                            <span
                              title={t("lockedTooltip")}
                              className="inline-flex items-center gap-1 text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300"
                            >
                              <Lock className="w-2.5 h-2.5" /> {t("lockedBadge")}
                            </span>
                          )}
                        </div>
                        {p.description && (
                          <p className="text-[11px] text-text-muted mt-0.5 truncate">
                            {p.description}
                          </p>
                        )}
                      </div>

                      {/* Slider */}
                      <button
                        type="button"
                        onClick={() => handleToggle(p)}
                        disabled={p.locked || savingTool === p.tool_name}
                        title={
                          p.locked
                            ? t("lockedTooltip")
                            : p.requires_confirmation
                            ? t("toggleOnTooltip")
                            : t("toggleOffTooltip")
                        }
                        className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors disabled:cursor-not-allowed ${
                          p.requires_confirmation
                            ? "bg-cyber-cyan/40"
                            : "bg-bg-tertiary border border-border-dim"
                        } ${p.locked ? "opacity-60" : ""}`}
                      >
                        <span
                          className={`absolute top-0.5 h-4 w-4 rounded-full bg-bg-primary shadow transition-transform ${
                            p.requires_confirmation ? "translate-x-4" : "translate-x-0.5"
                          }`}
                        />
                        {savingTool === p.tool_name && (
                          <Loader2 className="absolute -right-5 top-0.5 w-4 h-4 animate-spin text-cyber-cyan" />
                        )}
                      </button>
                    </div>
                  ))}
                </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="text-[10px] text-text-muted leading-relaxed pt-2 border-t border-border-dim">
        {t("hint")}
      </p>
    </section>
  );
}
