"use client";
// -----------------------------------------------------------------------------
// Copyright (c) 2024 Franck OLLIVIER
// Tous droits réservés.
//
// Ce logiciel est mis à disposition sous les termes de la licence
// PolyForm Strict License 1.0.0.
//
// RÉSUMÉ DES CONDITIONS :
// - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
// - INTERDIT : Toute utilisation commerciale sans accord préalable.
// - INTERDIT : Redistribution de versions modifiées de ce code.
//
// Pour consulter le texte intégral de la licence, veuillez vous référer au
// fichier LICENSE à la racine du projet ou visiter :
// https://polyformproject.org/licenses/strict/1.0.0/
// -----------------------------------------------------------------------------

import { useState, useEffect, useCallback, useRef } from "react";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import {
  Cpu, Key, Server, ShieldCheck, Mail, Calendar, HardDrive,
  CheckCircle, XCircle, ExternalLink, Check, AlertCircle, Languages,
  Monitor, Download, Plus, Trash2, Wifi, WifiOff, Lock, Eye, EyeOff,
  GitBranch, ChevronUp, ChevronDown, Info, ToggleLeft, ToggleRight,
} from "lucide-react";
import { authFetch, isAdmin } from "@/lib/auth";
import { useTranslations } from "next-intl";
import { setLocale } from "@/lib/locale";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Provider catalogue (UI-side)
// ---------------------------------------------------------------------------
const PROVIDERS = [
  {
    id: "zhipu",
    label: "Zhipu AI — GLM",
    flag: "🇨🇳",
    desc: "GLM-4.7 · Excellent function-calling · Prefix caching auto (−80 % coût) · API OpenAI-compatible",
    tier: "A/B",
    docsUrl: "https://open.bigmodel.cn/",
  },
  {
    id: "anthropic",
    label: "Anthropic Claude",
    flag: "🇺🇸",
    desc: "Fiable, rapide — prompt caching activé (−90 % sur system prompt) · serveurs US",
    tier: "B/C",
    docsUrl: "https://console.anthropic.com/",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    flag: "🇺🇸",
    desc: "Gemini 2.0 Flash / Pro — caching implicite activé",
    tier: "B",
    docsUrl: "https://aistudio.google.com/",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    flag: "🔀",
    desc: "200+ modèles (Meta, Google, Mistral, Qwen…) — modèles gratuits disponibles — passerelle universelle",
    tier: "A/B/C",
    docsUrl: "https://openrouter.ai/",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    flag: "🇨🇳",
    desc: "Coût très faible — serveurs en Chine",
    tier: "C",
    docsUrl: "https://platform.deepseek.com/",
  },
  {
    id: "mistral",
    label: "Mistral AI",
    flag: "🇫🇷",
    desc: "IA française, serveurs en Europe (RGPD) — fallback uniquement",
    tier: "C",
    docsUrl: "https://console.mistral.ai/",
    rgpd: true,
  },
  {
    id: "ollama",
    label: "Ollama (Local)",
    flag: "🖥️",
    desc: "100 % local, zéro données transmises — tâches de fond (mémoire)",
    tier: "A",
    docsUrl: "https://ollama.com/",
    rgpd: true,
  },
];

const GOOGLE_SERVICES = [
  { id: "gmail",    label: "Gmail",          icon: Mail,     scope: "Lecture et envoi d'emails" },
  { id: "calendar", label: "Google Calendar", icon: Calendar, scope: "Consultation et création d'événements" },
  { id: "drive",    label: "Google Drive",    icon: HardDrive, scope: "Lecture des fichiers (lecture seule)" },
];

// ---------------------------------------------------------------------------
// Password strength helper (miroir des règles CNIL côté backend)
// ---------------------------------------------------------------------------
interface PasswordStrength {
  score: number;       // 0-5
  label: string;
  color: string;       // Tailwind text color
  barColor: string;    // Tailwind bg color
  hints: string[];     // règles non satisfaites
}

function checkPasswordStrength(pwd: string): PasswordStrength {
  const hints: string[] = [];
  let score = 0;
  if (pwd.length >= 12)           score++; else hints.push("Au moins 12 caractères");
  if (/[A-Z]/.test(pwd))          score++; else hints.push("Une lettre majuscule");
  if (/[a-z]/.test(pwd))          score++; else hints.push("Une lettre minuscule");
  if (/\d/.test(pwd))             score++; else hints.push("Un chiffre");
  if (/[^a-zA-Z0-9]/.test(pwd))  score++; else hints.push("Un caractère spécial (!@#...)");

  const levels = [
    { label: "Très faible", color: "text-red-400",    barColor: "bg-red-500" },
    { label: "Faible",      color: "text-orange-400", barColor: "bg-orange-500" },
    { label: "Moyen",       color: "text-yellow-400", barColor: "bg-yellow-500" },
    { label: "Bon",         color: "text-lime-400",   barColor: "bg-lime-500" },
    { label: "Fort",        color: "text-emerald-400",barColor: "bg-emerald-500" },
    { label: "Excellent",   color: "text-cyber-cyan", barColor: "bg-cyber-cyan" },
  ];
  return { score, hints, ...levels[score] };
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface ProviderMeta {
  id: string;
  name: string;
  models: string[];
  has_key: boolean;
}

interface LLMSettings {
  provider: string;
  model: string;
  providers: ProviderMeta[];
}

interface TierMeta {
  id: string;
  label: string;
  badge: string;
  color: string;
  description: string;
}

interface TierEntry {
  providers: string[];
  fallback_enabled: boolean;
}

interface TierConfig {
  [tierId: string]: TierEntry;
}

interface ORModel {
  id: string;
  name: string;
  context_length: number;
  is_free: boolean;
  modality: string;
  prompt_price: string;
  completion_price: string;
}

const TIER_BADGE_COLORS: Record<string, string> = {
  emerald: "bg-emerald-500/10 border-emerald-500/30 text-emerald-400",
  blue:    "bg-blue-500/10 border-blue-500/30 text-blue-400",
  violet:  "bg-violet-500/10 border-violet-500/30 text-violet-400",
  amber:   "bg-amber-500/10 border-amber-500/30 text-amber-400",
  slate:   "bg-slate-500/10 border-slate-500/30 text-slate-400",
};

type ToastKind = "success" | "error";
interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

// ---------------------------------------------------------------------------
// Small toast hook
// ---------------------------------------------------------------------------
let _toastCounter = 0;

function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((kind: ToastKind, message: string) => {
    const id = ++_toastCounter;
    setToasts((prev) => [...prev, { id, kind, message }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 3500);
  }, []);

  return { toasts, push };
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------
export default function SettingsPage() {
  const t = useTranslations("settings");
  const tc = useTranslations("common");
  const admin = isAdmin();

  // LLM state
  const [llmLoaded, setLlmLoaded]         = useState(false);
  const [activeProvider, setActiveProvider] = useState("anthropic");
  const [activeModel, setActiveModel]       = useState("");
  const [providersMeta, setProvidersMeta]   = useState<ProviderMeta[]>([]);
  const [apiKeyInput, setApiKeyInput]       = useState("");
  const [savingLLM, setSavingLLM]           = useState(false);
  const [savingKey, setSavingKey]           = useState(false);

  // Google state
  const [googleConnected, setGoogleConnected] = useState<boolean | null>(null);
  const [googleLoading, setGoogleLoading]     = useState(false);

  // Change password state
  const [currentPwd, setCurrentPwd]     = useState("");
  const [newPwd, setNewPwd]             = useState("");
  const [confirmPwd, setConfirmPwd]     = useState("");
  const [showCurrentPwd, setShowCurrentPwd] = useState(false);
  const [showNewPwd, setShowNewPwd]         = useState(false);
  const [savingPwd, setSavingPwd]       = useState(false);

  // OpenRouter models state
  const [orModels, setOrModels]           = useState<ORModel[]>([]);
  const [orLoading, setOrLoading]         = useState(false);
  const [orFreeOnly, setOrFreeOnly]       = useState(true);
  const [orSearch, setOrSearch]           = useState("");

  // Tier routing state
  const [tierMeta, setTierMeta]           = useState<TierMeta[]>([]);
  const [tierConfig, setTierConfig]       = useState<TierConfig>({});
  const [tierProviderIds, setTierProviderIds] = useState<string[]>([]);
  const [savingTiers, setSavingTiers]     = useState(false);
  const [tierTooltip, setTierTooltip]     = useState<string | null>(null);

  // Desktop state
  const [desktopConnected, setDesktopConnected] = useState<boolean | null>(null);
  const [desktopPlatform, setDesktopPlatform]   = useState<string>("");
  const [desktopVersion, setDesktopVersion]     = useState<string>("");
  const [sandboxDirs, setSandboxDirs]           = useState<string[]>([]);
  const [sandboxInput, setSandboxInput]         = useState<string>("");
  const [savingDesktop, setSavingDesktop]       = useState(false);
  const [desktopBinaries, setDesktopBinaries]  = useState<Array<{os: string; arch: string; filename: string; url: string}>>([]);
  const desktopPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const { toasts, push } = useToasts();

  // Derived: current provider metadata from the API response
  const currentMeta = providersMeta.find((p) => p.id === activeProvider);
  const uiProvider  = PROVIDERS.find((p) => p.id === activeProvider);
  const models      = currentMeta?.models ?? [];

  // ---------------------------------------------------------------------------
  // Load LLM settings from API
  // ---------------------------------------------------------------------------
  const loadLLMSettings = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm`);
      if (!res.ok) return;
      const data: LLMSettings = await res.json();
      setActiveProvider(data.provider);
      setActiveModel(data.model);
      setProvidersMeta(data.providers);
      setLlmLoaded(true);
    } catch {
      // silently ignore — env defaults remain
    }
  }, []);

  useEffect(() => {
    loadLLMSettings();
  }, [loadLLMSettings]);

  // Clear key input whenever provider changes
  useEffect(() => {
    setApiKeyInput("");
  }, [activeProvider]);

  // Load OpenRouter models when provider = openrouter or freeOnly changes
  useEffect(() => {
    if (activeProvider !== "openrouter") return;
    setOrLoading(true);
    authFetch(`${API_URL}/api/settings/llm/openrouter-models?free_only=${orFreeOnly}`)
      .then((r) => r.ok ? r.json() : [])
      .then((data: ORModel[]) => {
        setOrModels(data);
        // Auto-select first model if current one not in list
        if (data.length > 0 && !data.find((m) => m.id === activeModel)) {
          handleModelChange(data[0].id);
        }
      })
      .catch(() => setOrModels([]))
      .finally(() => setOrLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProvider, orFreeOnly]);

  // Load tier routing config
  useEffect(() => {
    authFetch(`${API_URL}/api/settings/llm/tiers`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => {
        if (!d) return;
        setTierMeta(d.tiers ?? []);
        setTierConfig(d.config ?? {});
        setTierProviderIds(d.provider_ids ?? []);
      })
      .catch(() => {});
  }, []);

  // Check Google connection status
  useEffect(() => {
    authFetch(`${API_URL}/api/google/status`)
      .then((r) => r.json())
      .then((d) => setGoogleConnected(d.connected))
      .catch(() => setGoogleConnected(false));
  }, []);

  // Handle ?google=connected redirect from OAuth callback
  useEffect(() => {
    if (typeof window !== "undefined" && window.location.search.includes("google=connected")) {
      setGoogleConnected(true);
      window.history.replaceState({}, "", "/settings");
    }
  }, []);

  // Load desktop config and status
  const loadDesktopStatus = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/desktop/status`);
      if (!res.ok) return;
      const data = await res.json();
      setDesktopConnected(data.connected);
      if (data.connected) {
        setDesktopPlatform(data.platform ?? "");
        setDesktopVersion(data.version ?? "");
      }
    } catch {
      setDesktopConnected(false);
    }
  }, []);

  const loadDesktopConfig = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/desktop/config`);
      if (!res.ok) return;
      const data = await res.json();
      setSandboxDirs(data.sandbox_dirs ?? []);
    } catch {
      // silently ignore
    }
  }, []);

  const loadDesktopBinaries = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/desktop/binaries`);
      if (!res.ok) return;
      const data = await res.json();
      setDesktopBinaries(data.binaries ?? []);
    } catch {
      // silently ignore
    }
  }, []);

  useEffect(() => {
    loadDesktopStatus();
    loadDesktopConfig();
    loadDesktopBinaries();

    // Poll status every 10 seconds
    desktopPollRef.current = setInterval(loadDesktopStatus, 10_000);
    return () => {
      if (desktopPollRef.current) clearInterval(desktopPollRef.current);
    };
  }, [loadDesktopStatus, loadDesktopConfig, loadDesktopBinaries]);

  // ---------------------------------------------------------------------------
  // Handlers — LLM
  // ---------------------------------------------------------------------------
  const handleProviderClick = async (providerId: string) => {
    if (!admin || savingLLM) return;
    const meta = providersMeta.find((p) => p.id === providerId);
    const defaultModel = meta?.models[0] ?? "";

    setActiveProvider(providerId);
    setActiveModel(defaultModel);
    setSavingLLM(true);
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: providerId, model: defaultModel }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? `Erreur ${res.status}`);
      } else {
        push("success", "Fournisseur sauvegardé");
      }
    } catch {
      push("error", "Impossible de contacter le serveur");
    } finally {
      setSavingLLM(false);
    }
  };

  const handleModelChange = async (model: string) => {
    if (!admin || savingLLM) return;
    setActiveModel(model);
    setSavingLLM(true);
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: activeProvider, model }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? `Erreur ${res.status}`);
      } else {
        push("success", "Modèle sauvegardé");
      }
    } catch {
      push("error", "Impossible de contacter le serveur");
    } finally {
      setSavingLLM(false);
    }
  };

  const handleSaveKey = async () => {
    if (!admin || savingKey || !apiKeyInput.trim()) return;
    setSavingKey(true);
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm/keys/${activeProvider}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKeyInput.trim() }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? `Erreur ${res.status}`);
      } else {
        push("success", "Clé API sauvegardée");
        setApiKeyInput("");
        // Refresh metadata so has_key badge updates
        await loadLLMSettings();
      }
    } catch {
      push("error", "Impossible de contacter le serveur");
    } finally {
      setSavingKey(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Handlers — Google
  // ---------------------------------------------------------------------------
  const handleGoogleConnect = async () => {
    setGoogleLoading(true);
    try {
      const res = await authFetch(`${API_URL}/api/google/auth-url`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Erreur serveur ${res.status}`);
      if (!data.url) throw new Error("URL de connexion Google non reçue du serveur");
      window.location.href = data.url;
    } catch (e) {
      alert(e instanceof Error ? e.message : "Erreur lors de la connexion Google.");
    } finally {
      setGoogleLoading(false);
    }
  };

  const handleGoogleDisconnect = async () => {
    setGoogleLoading(true);
    try {
      await authFetch(`${API_URL}/api/google/disconnect`, { method: "DELETE" });
      setGoogleConnected(false);
    } finally {
      setGoogleLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Handlers — Tier routing
  // ---------------------------------------------------------------------------

  const moveTierProvider = (tierId: string, index: number, dir: -1 | 1) => {
    setTierConfig((prev) => {
      const entry = prev[tierId];
      if (!entry) return prev;
      const providers = [...entry.providers];
      const newIndex = index + dir;
      if (newIndex < 0 || newIndex >= providers.length) return prev;
      [providers[index], providers[newIndex]] = [providers[newIndex], providers[index]];
      return { ...prev, [tierId]: { ...entry, providers } };
    });
  };

  const removeTierProvider = (tierId: string, provId: string) => {
    setTierConfig((prev) => {
      const entry = prev[tierId];
      if (!entry) return prev;
      return { ...prev, [tierId]: { ...entry, providers: entry.providers.filter((p) => p !== provId) } };
    });
  };

  const addTierProvider = (tierId: string, provId: string) => {
    setTierConfig((prev) => {
      const entry = prev[tierId] ?? { providers: [], fallback_enabled: true };
      if (entry.providers.includes(provId)) return prev;
      return { ...prev, [tierId]: { ...entry, providers: [...entry.providers, provId] } };
    });
  };

  const toggleTierFallback = (tierId: string) => {
    setTierConfig((prev) => {
      const entry = prev[tierId];
      if (!entry) return prev;
      return { ...prev, [tierId]: { ...entry, fallback_enabled: !entry.fallback_enabled } };
    });
  };

  const handleSaveTiers = async () => {
    if (savingTiers) return;
    setSavingTiers(true);
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm/tiers`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: tierConfig }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? `Erreur ${res.status}`);
      } else {
        push("success", "Niveaux de routage sauvegardés");
      }
    } catch {
      push("error", "Impossible de contacter le serveur");
    } finally {
      setSavingTiers(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Handlers — Desktop
  // ---------------------------------------------------------------------------

  const handleAddSandboxDir = () => {
    const trimmed = sandboxInput.trim();
    if (!trimmed || sandboxDirs.includes(trimmed)) return;
    setSandboxDirs((prev) => [...prev, trimmed]);
    setSandboxInput("");
  };

  const handleRemoveSandboxDir = (dir: string) => {
    setSandboxDirs((prev) => prev.filter((d) => d !== dir));
  };

  const handleSaveDesktopConfig = async () => {
    if (savingDesktop) return;
    setSavingDesktop(true);
    try {
      const res = await authFetch(`${API_URL}/api/desktop/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sandbox_dirs: sandboxDirs }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? `Erreur ${res.status}`);
      } else {
        push("success", "Configuration ELY Desktop sauvegardée");
      }
    } catch {
      push("error", "Impossible de contacter le serveur");
    } finally {
      setSavingDesktop(false);
    }
  };

  const handleDownloadConfig = async () => {
    try {
      const res = await authFetch(`${API_URL}/api/desktop/download-config`);
      if (!res.ok) {
        push("error", "Erreur lors de la génération du fichier de configuration");
        return;
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "ely-config.json";
      a.click();
      window.URL.revokeObjectURL(url);
    } catch {
      push("error", "Impossible de télécharger la configuration");
    }
  };

  // ---------------------------------------------------------------------------
  // Handlers — Change password
  // ---------------------------------------------------------------------------
  const handleChangePassword = async () => {
    if (savingPwd) return;
    if (newPwd !== confirmPwd) {
      push("error", "Les deux nouveaux mots de passe ne correspondent pas.");
      return;
    }
    const strength = checkPasswordStrength(newPwd);
    if (strength.score < 5) {
      push("error", "Le mot de passe ne respecte pas les critères de sécurité.");
      return;
    }
    setSavingPwd(true);
    try {
      const res = await authFetch(`${API_URL}/auth/change-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPwd, new_password: newPwd }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? `Erreur ${res.status}`);
      } else {
        push("success", "Mot de passe modifié avec succès.");
        setCurrentPwd("");
        setNewPwd("");
        setConfirmPwd("");
      }
    } catch {
      push("error", "Impossible de contacter le serveur.");
    } finally {
      setSavingPwd(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  const needsKey = !["ollama"].includes(activeProvider);
  const hasKey   = currentMeta?.has_key ?? false;

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Header />

          {/* Toast stack */}
          <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 pointer-events-none">
            {toasts.map((t) => (
              <div
                key={t.id}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-lg border text-xs shadow-lg pointer-events-auto transition-all ${
                  t.kind === "success"
                    ? "bg-emerald-900/80 border-emerald-500/30 text-emerald-300"
                    : "bg-red-900/80 border-red-500/30 text-red-300"
                }`}
              >
                {t.kind === "success"
                  ? <Check className="w-3.5 h-3.5 shrink-0" />
                  : <AlertCircle className="w-3.5 h-3.5 shrink-0" />}
                {t.message}
              </div>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-6 space-y-6 max-w-2xl">

            {/* ----------------------------------------------------------------
                LLM Provider — admin only
            ---------------------------------------------------------------- */}
            {admin && (
              <section>
                <div className="flex items-center gap-2 mb-4">
                  <Cpu className="w-4 h-4 text-cyber-cyan" />
                  <h2 className="text-sm font-medium text-text-primary">{t("llmProvider")}</h2>
                  {savingLLM && (
                    <span className="text-[10px] text-text-muted animate-pulse">{tc("saving")}</span>
                  )}
                </div>

                {/* Provider cards */}
                <div className="space-y-2">
                  {PROVIDERS.map((p) => {
                    const isActive = activeProvider === p.id;
                    const meta = providersMeta.find((m) => m.id === p.id);
                    return (
                      <button
                        key={p.id}
                        onClick={() => handleProviderClick(p.id)}
                        disabled={savingLLM}
                        className={`w-full flex items-center justify-between p-4 rounded-lg border text-left transition-all disabled:opacity-60 ${
                          isActive
                            ? "bg-cyber-cyan/5 border-cyber-cyan/30 text-text-primary"
                            : "bg-bg-secondary border-border-dim text-text-secondary hover:border-text-muted"
                        }`}
                      >
                        <div className="flex items-start gap-3 min-w-0">
                          <span className="text-base mt-0.5 shrink-0">{p.flag}</span>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-sm font-medium">{p.label}</span>
                              {p.rgpd && (
                                <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0">
                                  <ShieldCheck className="w-2.5 h-2.5" />
                                  RGPD
                                </span>
                              )}
                              {llmLoaded && meta && meta.has_key && p.id !== "ollama" && (
                                <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0">
                                  <Check className="w-2.5 h-2.5" />
                                  {t("keyConfigured")}
                                </span>
                              )}
                            </div>
                            <div className="text-xs text-text-muted mt-0.5">{p.desc}</div>
                          </div>
                        </div>
                        <span className={`text-[10px] px-2 py-0.5 rounded border shrink-0 ml-3 ${
                          isActive
                            ? "bg-cyber-cyan/10 border-cyber-cyan/30 text-cyber-cyan"
                            : "bg-bg-primary border-border-dim text-text-muted"
                        }`}>
                          Tier {p.tier}
                        </span>
                      </button>
                    );
                  })}
                </div>

                {/* Model selector + API key input */}
                <div className="mt-4 bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4">

                  {/* Model selector */}
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-text-muted uppercase tracking-wider">{t("activeModel")}</span>
                      {uiProvider && (
                        <a
                          href={uiProvider.docsUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] text-cyber-cyan hover:underline"
                        >
                          Console →
                        </a>
                      )}
                    </div>

                    {/* OpenRouter: dynamic model browser */}
                    {activeProvider === "openrouter" ? (
                      <div className="space-y-2">
                        {/* Controls */}
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => setOrFreeOnly(!orFreeOnly)}
                            className={`flex items-center gap-1.5 text-[10px] px-2 py-1 rounded border transition-all ${
                              orFreeOnly
                                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                                : "bg-bg-primary border-border-dim text-text-muted hover:border-text-muted"
                            }`}
                          >
                            {orFreeOnly ? <ToggleRight className="w-3 h-3" /> : <ToggleLeft className="w-3 h-3" />}
                            Gratuits uniquement
                          </button>
                          <span className="text-[10px] text-text-muted">
                            {orLoading ? "Chargement…" : `${orModels.length} modèles`}
                          </span>
                        </div>
                        {/* Search */}
                        <input
                          type="text"
                          value={orSearch}
                          onChange={(e) => setOrSearch(e.target.value)}
                          placeholder="Rechercher un modèle…"
                          className="w-full text-xs bg-bg-primary border border-border-dim rounded px-3 py-1.5 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
                        />
                        {/* Model list */}
                        <div className="max-h-48 overflow-y-auto space-y-1 rounded border border-border-dim bg-bg-primary p-1">
                          {orLoading ? (
                            <div className="text-[11px] text-text-muted text-center py-3 animate-pulse">Chargement des modèles…</div>
                          ) : orModels
                              .filter((m) =>
                                !orSearch || m.name.toLowerCase().includes(orSearch.toLowerCase()) || m.id.toLowerCase().includes(orSearch.toLowerCase())
                              )
                              .map((m) => (
                                <button
                                  key={m.id}
                                  onClick={() => handleModelChange(m.id)}
                                  disabled={savingLLM}
                                  className={`w-full flex items-center justify-between px-2 py-1.5 rounded text-left transition-all disabled:opacity-50 ${
                                    activeModel === m.id
                                      ? "bg-cyber-cyan/10 border border-cyber-cyan/30"
                                      : "hover:bg-bg-secondary border border-transparent"
                                  }`}
                                >
                                  <div className="min-w-0">
                                    <div className="text-xs text-text-primary truncate">{m.name}</div>
                                    <div className="text-[9px] text-text-muted truncate">{m.id}</div>
                                  </div>
                                  <div className="flex items-center gap-1.5 shrink-0 ml-2">
                                    {m.is_free && (
                                      <span className="text-[8px] px-1 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                                        Gratuit
                                      </span>
                                    )}
                                    {m.modality !== "text->text" && (
                                      <span className="text-[8px] px-1 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400">
                                        Vision
                                      </span>
                                    )}
                                    <span className="text-[8px] text-text-muted">
                                      {m.context_length >= 1000 ? `${Math.round(m.context_length / 1000)}k` : m.context_length}
                                    </span>
                                  </div>
                                </button>
                              ))}
                          {!orLoading && orModels.filter((m) =>
                            !orSearch || m.name.toLowerCase().includes(orSearch.toLowerCase()) || m.id.toLowerCase().includes(orSearch.toLowerCase())
                          ).length === 0 && (
                            <div className="text-[11px] text-text-muted text-center py-3">Aucun modèle trouvé</div>
                          )}
                        </div>
                        {/* Selected model display */}
                        {activeModel && (
                          <div className="text-[10px] text-text-muted">
                            Sélectionné : <code className="text-cyber-cyan">{activeModel}</code>
                          </div>
                        )}
                      </div>
                    ) : models.length > 0 ? (
                      <select
                        value={activeModel}
                        onChange={(e) => handleModelChange(e.target.value)}
                        disabled={savingLLM}
                        className="w-full text-xs bg-bg-primary border border-border-dim rounded px-3 py-2 text-text-primary focus:outline-none focus:border-cyber-cyan/40 disabled:opacity-60"
                      >
                        {models.map((m) => (
                          <option key={m} value={m}>{m}</option>
                        ))}
                      </select>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {PROVIDERS.find((p) => p.id === activeProvider) &&
                          <code className="text-[11px] px-2 py-0.5 rounded bg-bg-primary border border-border-dim text-text-secondary">
                            {activeModel}
                          </code>
                        }
                      </div>
                    )}
                  </div>

                  {/* API key section */}
                  {needsKey && (
                    <div className="space-y-2 pt-3 border-t border-border-dim">
                      <div className="flex items-center gap-2">
                        <Key className="w-3.5 h-3.5 text-cyber-cyan" />
                        <span className="text-xs text-text-muted uppercase tracking-wider">{t("apiKey")}</span>
                        {hasKey && (
                          <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                            <Check className="w-2.5 h-2.5" />
                            {t("keyConfigured")}
                          </span>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          value={apiKeyInput}
                          onChange={(e) => setApiKeyInput(e.target.value)}
                          placeholder="sk-••••••••"
                          autoComplete="new-password"
                          className="flex-1 text-xs bg-bg-primary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
                        />
                        <button
                          onClick={handleSaveKey}
                          disabled={savingKey || !apiKeyInput.trim()}
                          className="text-xs px-3 py-2 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all disabled:opacity-40 shrink-0"
                        >
                          {savingKey ? "…" : tc("save")}
                        </button>
                      </div>
                      <p className="text-[10px] text-text-muted">
                        {t("keyStoredEncrypted")}
                      </p>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* ----------------------------------------------------------------
                Tier Routing — admin only
            ---------------------------------------------------------------- */}
            {admin && tierMeta.length > 0 && (
              <section>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <GitBranch className="w-4 h-4 text-cyber-cyan" />
                    <h2 className="text-sm font-medium text-text-primary">Niveaux de routage</h2>
                  </div>
                  <button
                    onClick={handleSaveTiers}
                    disabled={savingTiers}
                    className="text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 transition-all disabled:opacity-50"
                  >
                    {savingTiers ? "…" : "Enregistrer"}
                  </button>
                </div>

                <p className="text-[11px] text-text-muted mb-3">
                  Définissez quel modèle est utilisé selon la complexité détectée. Les modèles en tête de liste sont prioritaires ; le fallback tente le suivant en cas d'erreur.
                </p>

                <div className="space-y-3">
                  {tierMeta.map((tier) => {
                    const entry: TierEntry = tierConfig[tier.id] ?? { providers: [], fallback_enabled: true };
                    const badgeCls = TIER_BADGE_COLORS[tier.color] ?? TIER_BADGE_COLORS.slate;
                    const availableToAdd = tierProviderIds.filter((pid) => !entry.providers.includes(pid));

                    return (
                      <div key={tier.id} className="bg-bg-secondary border border-border-dim rounded-lg p-4">
                        {/* Header */}
                        <div className="flex items-start justify-between gap-2 mb-3">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border shrink-0 ${badgeCls}`}>
                              {tier.badge}
                            </span>
                            <span className="text-xs font-medium text-text-primary">{tier.label}</span>
                            <button
                              onClick={() => setTierTooltip(tierTooltip === tier.id ? null : tier.id)}
                              className="text-text-muted hover:text-text-secondary transition-colors shrink-0"
                              title="Explication"
                            >
                              <Info className="w-3 h-3" />
                            </button>
                          </div>
                          {/* Fallback toggle */}
                          <button
                            onClick={() => toggleTierFallback(tier.id)}
                            className="flex items-center gap-1.5 text-[10px] shrink-0 transition-colors"
                            title={entry.fallback_enabled ? "Désactiver le fallback" : "Activer le fallback"}
                          >
                            {entry.fallback_enabled
                              ? <ToggleRight className="w-4 h-4 text-cyber-cyan" />
                              : <ToggleLeft className="w-4 h-4 text-text-muted" />}
                            <span className={entry.fallback_enabled ? "text-cyber-cyan" : "text-text-muted"}>
                              Fallback {entry.fallback_enabled ? "activé" : "désactivé"}
                            </span>
                          </button>
                        </div>

                        {/* Tooltip description */}
                        {tierTooltip === tier.id && (
                          <p className="text-[11px] text-text-muted bg-bg-primary rounded px-3 py-2 mb-3 border border-border-dim">
                            {tier.description}
                          </p>
                        )}

                        {/* Ordered provider list */}
                        <div className="space-y-1.5">
                          {entry.providers.length === 0 && (
                            <p className="text-[11px] text-text-muted italic">Aucun modèle configuré — le provider global sera utilisé.</p>
                          )}
                          {entry.providers.map((provId, idx) => {
                            const provLabel = PROVIDERS.find((p) => p.id === provId);
                            return (
                              <div key={provId} className="flex items-center gap-2">
                                {/* Priority number */}
                                <span className="text-[9px] text-text-muted w-4 text-right shrink-0">{idx + 1}.</span>
                                {/* Provider pill */}
                                <div className="flex-1 flex items-center gap-2 bg-bg-primary border border-border-dim rounded px-2 py-1 text-xs text-text-primary">
                                  {provLabel && <span className="text-base leading-none">{provLabel.flag}</span>}
                                  <span>{provLabel?.label ?? provId}</span>
                                </div>
                                {/* Move up */}
                                <button
                                  onClick={() => moveTierProvider(tier.id, idx, -1)}
                                  disabled={idx === 0}
                                  className="text-text-muted hover:text-text-secondary disabled:opacity-30 transition-colors"
                                >
                                  <ChevronUp className="w-3.5 h-3.5" />
                                </button>
                                {/* Move down */}
                                <button
                                  onClick={() => moveTierProvider(tier.id, idx, 1)}
                                  disabled={idx === entry.providers.length - 1}
                                  className="text-text-muted hover:text-text-secondary disabled:opacity-30 transition-colors"
                                >
                                  <ChevronDown className="w-3.5 h-3.5" />
                                </button>
                                {/* Remove */}
                                <button
                                  onClick={() => removeTierProvider(tier.id, provId)}
                                  className="text-text-muted hover:text-cyber-red transition-colors"
                                >
                                  <Trash2 className="w-3 h-3" />
                                </button>
                              </div>
                            );
                          })}
                        </div>

                        {/* Add provider dropdown */}
                        {availableToAdd.length > 0 && (
                          <div className="mt-2">
                            <select
                              defaultValue=""
                              onChange={(e) => {
                                if (e.target.value) {
                                  addTierProvider(tier.id, e.target.value);
                                  e.target.value = "";
                                }
                              }}
                              className="text-[11px] bg-bg-primary border border-border-dim rounded px-2 py-1 text-text-muted w-full"
                            >
                              <option value="">+ Ajouter un provider…</option>
                              {availableToAdd.map((pid) => {
                                const p = PROVIDERS.find((pp) => pp.id === pid);
                                return (
                                  <option key={pid} value={pid}>
                                    {p ? `${p.flag} ${p.label}` : pid}
                                  </option>
                                );
                              })}
                            </select>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* ----------------------------------------------------------------
                Google Services — visible by all authenticated users
            ---------------------------------------------------------------- */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <div className="w-4 h-4 text-cyber-cyan font-bold text-sm">G</div>
                <h2 className="text-sm font-medium text-text-primary">{t("googleServices")}</h2>
                {googleConnected === true && (
                  <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                    <CheckCircle className="w-2.5 h-2.5" /> {tc("connected")}
                  </span>
                )}
                {googleConnected === false && (
                  <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-text-muted/10 border border-border-dim text-text-muted">
                    <XCircle className="w-2.5 h-2.5" /> {tc("disconnected")}
                  </span>
                )}
              </div>

              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4">
                <div className="space-y-2">
                  {GOOGLE_SERVICES.map(({ id, label, icon: Icon, scope }) => (
                    <div key={id} className="flex items-center gap-3">
                      <div className={`w-7 h-7 rounded flex items-center justify-center shrink-0 ${
                        googleConnected ? "bg-emerald-500/10 border border-emerald-500/20" : "bg-bg-primary border border-border-dim"
                      }`}>
                        <Icon className={`w-3.5 h-3.5 ${googleConnected ? "text-emerald-400" : "text-text-muted"}`} />
                      </div>
                      <div>
                        <div className="text-xs font-medium text-text-primary">{label}</div>
                        <div className="text-[11px] text-text-muted">{scope}</div>
                      </div>
                    </div>
                  ))}
                </div>

                <p className="text-[11px] text-text-muted flex items-start gap-1.5 pt-2 border-t border-border-dim">
                  <ShieldCheck className="w-3 h-3 shrink-0 mt-0.5 text-emerald-400" />
                  ELY n'accède à ces services que sur demande explicite. Un token OAuth2 est stocké localement — aucune donnée ne transite par un serveur tiers.
                </p>

                <div className="pt-1">
                  {googleConnected ? (
                    <button
                      onClick={handleGoogleDisconnect}
                      disabled={googleLoading}
                      className="text-xs px-3 py-1.5 rounded border border-cyber-red/30 text-cyber-red hover:bg-cyber-red/5 transition-all disabled:opacity-50"
                    >
                      {googleLoading ? "..." : t("disconnectGoogle")}
                    </button>
                  ) : (
                    <button
                      onClick={handleGoogleConnect}
                      disabled={googleLoading}
                      className="inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all disabled:opacity-50"
                    >
                      <ExternalLink className="w-3 h-3" />
                      {googleLoading ? tc("redirecting") : t("connectGoogle")}
                    </button>
                  )}
                </div>

                <details className="text-[11px] text-text-muted">
                  <summary className="cursor-pointer hover:text-text-secondary">{t("howToConfigure")}</summary>
                  <ol className="mt-2 space-y-1 pl-3 list-decimal">
                    <li>Aller sur <a href="https://console.cloud.google.com/" target="_blank" rel="noopener noreferrer" className="text-cyber-cyan hover:underline">console.cloud.google.com</a></li>
                    <li>Créer un projet → API &amp; Services → Identifiants</li>
                    <li>Créer un ID client OAuth 2.0 (application Web)</li>
                    <li>Ajouter l'URI de redirection : <code className="text-cyber-cyan">http://localhost:8000/api/google/callback</code></li>
                    <li>Renseigner le Client ID et Secret dans <a href="/admin" className="text-cyber-cyan hover:underline">Admin → OAuth Google</a> (sans redémarrage)</li>
                    <li>Revenir ici et cliquer sur "Connecter mon compte Google"</li>
                  </ol>
                </details>
              </div>
            </section>

            {/* ----------------------------------------------------------------
                Language
            ---------------------------------------------------------------- */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Languages className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary">{t("language")}</h2>
              </div>
              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
                <p className="text-xs text-text-muted">{t("languageDescription")}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setLocale("fr")}
                    className="text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all"
                  >
                    {t("french")}
                  </button>
                  <button
                    onClick={() => setLocale("en")}
                    className="text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all"
                  >
                    {t("english")}
                  </button>
                </div>
              </div>
            </section>

            {/* ----------------------------------------------------------------
                SSH Hosts — admin only
            ---------------------------------------------------------------- */}
            {admin && (
              <section>
                <div className="flex items-center gap-2 mb-4">
                  <Server className="w-4 h-4 text-cyber-cyan" />
                  <h2 className="text-sm font-medium text-text-primary">{t("sshHosts")}</h2>
                </div>
                <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
                  <p className="text-xs text-text-muted">
                    Configurer les hôtes SSH et leurs commandes autorisées dans{" "}
                    <code className="text-cyber-cyan">config/hosts.yaml</code>.
                    Chaque hôte requiert une liste explicite de commandes — l'agent ne peut pas
                    exécuter de commandes arbitraires.
                  </p>
                  <pre className="mt-3 text-[11px] text-text-secondary bg-bg-primary border border-border-dim rounded p-3 overflow-x-auto">
{`hosts:
  my-server:
    hostname: 192.168.1.100
    port: 22
    username: ubuntu
    key_file: ~/.ssh/id_rsa
    allowed_commands:
      - "df -h"
      - "docker ps"
      - "systemctl status *"`}
                  </pre>
                </div>
              </section>
            )}

            {/* ----------------------------------------------------------------
                ELY Desktop
            ---------------------------------------------------------------- */}
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Monitor className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary">ELY Desktop</h2>
                {desktopConnected === true && (
                  <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                    <Wifi className="w-2.5 h-2.5" /> Connecté
                    {desktopPlatform && ` · ${desktopPlatform}`}
                    {desktopVersion && ` v${desktopVersion}`}
                  </span>
                )}
                {desktopConnected === false && (
                  <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-text-muted/10 border border-border-dim text-text-muted">
                    <WifiOff className="w-2.5 h-2.5" /> Non connecté
                  </span>
                )}
              </div>

              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4">

                {/* Description */}
                <p className="text-xs text-text-muted">
                  ELY Desktop est un daemon léger qui tourne sur votre machine et donne à ELY
                  un accès contrôlé à votre système de fichiers local. Seuls les répertoires
                  listés ci-dessous sont accessibles.
                </p>

                {/* Sandbox dirs */}
                <div className="space-y-2">
                  <span className="text-xs text-text-muted uppercase tracking-wider">
                    Répertoires autorisés
                  </span>

                  {sandboxDirs.length === 0 && (
                    <p className="text-[11px] text-text-muted italic">
                      Aucun répertoire configuré — ajoutez-en un ci-dessous.
                    </p>
                  )}

                  <div className="space-y-1.5">
                    {sandboxDirs.map((dir) => (
                      <div
                        key={dir}
                        className="flex items-center justify-between gap-2 px-3 py-1.5 rounded bg-bg-primary border border-border-dim"
                      >
                        <code className="text-[11px] text-text-secondary flex-1 truncate">{dir}</code>
                        <button
                          onClick={() => handleRemoveSandboxDir(dir)}
                          className="shrink-0 text-text-muted hover:text-cyber-red transition-colors"
                          aria-label="Supprimer"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>

                  {/* Add dir input */}
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={sandboxInput}
                      onChange={(e) => setSandboxInput(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleAddSandboxDir()}
                      placeholder="/home/user/documents"
                      className="flex-1 text-xs bg-bg-primary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
                    />
                    <button
                      onClick={handleAddSandboxDir}
                      className="text-xs px-3 py-2 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all shrink-0"
                    >
                      <Plus className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Save button */}
                <button
                  onClick={handleSaveDesktopConfig}
                  disabled={savingDesktop}
                  className="text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all disabled:opacity-50"
                >
                  {savingDesktop ? "Sauvegarde…" : "Sauvegarder"}
                </button>

                {/* Download config */}
                <div className="pt-3 border-t border-border-dim space-y-2">
                  <p className="text-[11px] text-text-muted">
                    Téléchargez le fichier de configuration et placez-le dans le même répertoire
                    que le daemon ELY Desktop. Il contient un token d'authentification valable
                    30 jours.
                  </p>
                  <button
                    onClick={handleDownloadConfig}
                    className="inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all"
                  >
                    <Download className="w-3 h-3" />
                    Télécharger ely-config.json
                  </button>
                </div>

                {/* Binaries */}
                {desktopBinaries.length > 0 && (
                  <div className="pt-3 border-t border-border-dim space-y-2">
                    <span className="text-xs text-text-muted uppercase tracking-wider">
                      Télécharger le daemon
                    </span>
                    <div className="space-y-1.5">
                      {desktopBinaries.map((b) => (
                        <a
                          key={b.filename}
                          href={b.url}
                          download={b.filename}
                          className="flex items-center gap-2 px-3 py-1.5 rounded bg-bg-primary border border-border-dim hover:border-cyber-cyan/30 transition-colors group"
                        >
                          <Download className="w-3 h-3 text-text-muted group-hover:text-cyber-cyan transition-colors shrink-0" />
                          <span className="text-[11px] text-text-secondary group-hover:text-text-primary transition-colors truncate">
                            {b.filename}
                          </span>
                          <span className="text-[10px] text-text-muted ml-auto shrink-0">
                            {b.os} {b.arch}
                          </span>
                        </a>
                      ))}
                    </div>
                    <details className="text-[11px] text-text-muted">
                      <summary className="cursor-pointer hover:text-text-secondary">
                        Instructions d'installation
                      </summary>
                      <ol className="mt-2 space-y-1 pl-3 list-decimal">
                        <li>Télécharger le binaire correspondant à votre OS</li>
                        <li>Télécharger <code className="text-cyber-cyan">ely-config.json</code> (bouton ci-dessus)</li>
                        <li>Placer les deux fichiers dans le même répertoire</li>
                        <li>
                          Linux/macOS : <code className="text-cyber-cyan">chmod +x ely-desktop-* && ./ely-desktop-*</code>
                        </li>
                        <li>Windows : double-cliquer sur <code className="text-cyber-cyan">ely-desktop-windows-amd64.exe</code></li>
                        <li>Le statut ci-dessus passera à "Connecté" en quelques secondes</li>
                      </ol>
                    </details>
                  </div>
                )}

              </div>
            </section>

            {/* ----------------------------------------------------------------
                Mon compte — changement de mot de passe (tous les utilisateurs)
            ---------------------------------------------------------------- */}
            {(() => {
              const strength = newPwd ? checkPasswordStrength(newPwd) : null;
              const mismatch = confirmPwd && newPwd !== confirmPwd;

              return (
                <section>
                  <div className="flex items-center gap-2 mb-4">
                    <Lock className="w-4 h-4 text-cyber-cyan" />
                    <h2 className="text-sm font-medium text-text-primary">Mon compte</h2>
                  </div>

                  <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4">
                    <p className="text-xs text-text-muted">
                      Conformément au RGPD, vous pouvez modifier votre mot de passe à tout moment.
                      Le mot de passe doit respecter les recommandations de la CNIL.
                    </p>

                    {/* Mot de passe actuel */}
                    <div className="space-y-1">
                      <label className="text-xs text-text-secondary">Mot de passe actuel</label>
                      <div className="relative">
                        <input
                          type={showCurrentPwd ? "text" : "password"}
                          value={currentPwd}
                          onChange={(e) => setCurrentPwd(e.target.value)}
                          placeholder="••••••••••••"
                          className="w-full bg-bg-primary border border-border-dim rounded-md px-3 py-2 text-sm text-text-primary placeholder-text-muted/40 focus:outline-none focus:border-cyber-cyan/50 pr-9"
                        />
                        <button
                          type="button"
                          onClick={() => setShowCurrentPwd((v) => !v)}
                          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                        >
                          {showCurrentPwd ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    </div>

                    {/* Nouveau mot de passe */}
                    <div className="space-y-1">
                      <label className="text-xs text-text-secondary">Nouveau mot de passe</label>
                      <div className="relative">
                        <input
                          type={showNewPwd ? "text" : "password"}
                          value={newPwd}
                          onChange={(e) => setNewPwd(e.target.value)}
                          placeholder="••••••••••••"
                          className="w-full bg-bg-primary border border-border-dim rounded-md px-3 py-2 text-sm text-text-primary placeholder-text-muted/40 focus:outline-none focus:border-cyber-cyan/50 pr-9"
                        />
                        <button
                          type="button"
                          onClick={() => setShowNewPwd((v) => !v)}
                          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                        >
                          {showNewPwd ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>
                      </div>

                      {/* Indicateur de force */}
                      {strength && (
                        <div className="mt-2 space-y-1.5">
                          <div className="flex items-center gap-2">
                            <div className="flex gap-0.5 flex-1">
                              {[1,2,3,4,5].map((i) => (
                                <div
                                  key={i}
                                  className={`h-1 flex-1 rounded-full transition-all ${
                                    i <= strength.score ? strength.barColor : "bg-border-dim"
                                  }`}
                                />
                              ))}
                            </div>
                            <span className={`text-[10px] font-medium ${strength.color} shrink-0`}>
                              {strength.label}
                            </span>
                          </div>
                          {strength.hints.length > 0 && (
                            <ul className="space-y-0.5">
                              {strength.hints.map((h) => (
                                <li key={h} className="text-[10px] text-text-muted flex items-center gap-1">
                                  <XCircle className="w-3 h-3 text-red-400 shrink-0" />
                                  {h}
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Confirmation */}
                    <div className="space-y-1">
                      <label className="text-xs text-text-secondary">Confirmer le nouveau mot de passe</label>
                      <input
                        type="password"
                        value={confirmPwd}
                        onChange={(e) => setConfirmPwd(e.target.value)}
                        placeholder="••••••••••••"
                        className={`w-full bg-bg-primary border rounded-md px-3 py-2 text-sm text-text-primary placeholder-text-muted/40 focus:outline-none ${
                          mismatch
                            ? "border-red-500/50 focus:border-red-500"
                            : "border-border-dim focus:border-cyber-cyan/50"
                        }`}
                      />
                      {mismatch && (
                        <p className="text-[10px] text-red-400 flex items-center gap-1">
                          <XCircle className="w-3 h-3" /> Les mots de passe ne correspondent pas.
                        </p>
                      )}
                    </div>

                    <button
                      onClick={handleChangePassword}
                      disabled={savingPwd || !currentPwd || !newPwd || !confirmPwd}
                      className="w-full py-2 rounded-md text-xs font-medium bg-cyber-cyan/10 border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      {savingPwd ? "Modification en cours…" : "Modifier le mot de passe"}
                    </button>
                  </div>
                </section>
              );
            })()}

          </div>
        </div>
      </div>
    </AuthGuard>
  );
}
