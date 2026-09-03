"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/settings/page.tsx
 * @brief      Settings page — user preferences and configuration
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { LicenceBanner } from "@/components/layout/LicenceBanner";
import { GoogleAccountsSection } from "@/components/settings/GoogleAccountsSection";
import { HitlPreferencesSection } from "@/components/settings/HitlPreferencesSection";
import { SovereigntySection } from "@/components/settings/SovereigntySection";
import { LicenceSection } from "@/components/settings/LicenceSection";
import { ToolCatalogSection } from "@/components/settings/ToolCatalogSection";
import { api } from "@/lib/api";
import {
  Cpu, Key, Server, ShieldCheck, Mail, Calendar, HardDrive,
  CheckCircle, XCircle, ExternalLink, Check, AlertCircle, Languages,
  Monitor, Download, Plus, Trash2, Pencil, Wifi, WifiOff, Lock, Eye, EyeOff,
  GitBranch, ChevronUp, ChevronDown, Info, ToggleLeft, ToggleRight, User,
  Plug, Sparkles, Zap, KeyRound, Wrench,
} from "lucide-react";
import { authFetch, isAdmin } from "@/lib/auth";
import { useTranslations, useLocale } from "next-intl";
import { setLocale } from "@/lib/locale";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Provider catalogue (UI-side) — used in the "Add instance" modal
// ---------------------------------------------------------------------------
const PROVIDERS = [
  {
    id: "zhipu",
    label: "Zhipu AI — GLM",
    flag: "🇨🇳",
    needsKey: true,
    defaultModel: "glm-4.7",
    docsUrl: "https://open.bigmodel.cn/",
  },
  {
    id: "anthropic",
    label: "Anthropic Claude",
    flag: "🇺🇸",
    needsKey: true,
    defaultModel: "claude-haiku-4-5-20251001",
    docsUrl: "https://console.anthropic.com/",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    flag: "🇺🇸",
    needsKey: true,
    defaultModel: "gemini-2.5-flash",
    docsUrl: "https://aistudio.google.com/",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    flag: "🔀",
    needsKey: true,
    defaultModel: "meta-llama/llama-3.3-70b-instruct:free",
    docsUrl: "https://openrouter.ai/",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    flag: "🇨🇳",
    needsKey: true,
    defaultModel: "deepseek-chat",
    docsUrl: "https://platform.deepseek.com/",
  },
  {
    id: "mistral",
    label: "Mistral AI",
    flag: "🇫🇷",
    needsKey: true,
    defaultModel: "mistral-small-latest",
    docsUrl: "https://console.mistral.ai/",
  },
  {
    id: "ollama",
    label: "Ollama (Local)",
    flag: "🖥️",
    needsKey: false,
    defaultModel: "",
    docsUrl: "https://ollama.com/",
  },
  {
    id: "lm_studio",
    label: "LM Studio (Local)",
    flag: "🖥️",
    needsKey: false,
    defaultModel: "gemma-4-26B-A4B-it-MLX-4bit",
    docsUrl: "https://lmstudio.ai/docs/api/openai-api",
  },
  {
    id: "qwen_api",
    label: "Qwen API (Alibaba Cloud)",
    flag: "🇨🇳",
    needsKey: true,
    defaultModel: "qwen-plus-latest",
    docsUrl: "https://help.aliyun.com/zh/model-studio",
  },
  {
    id: "openai",
    label: "OpenAI",
    flag: "🇺🇸",
    needsKey: true,
    defaultModel: "gpt-4o-mini",
    docsUrl: "https://platform.openai.com/api-keys",
  },
  {
    // Abonnement ChatGPT (forfait mensuel) — PAS de clé API : connexion par
    // import des tokens du CLI Codex (`codex login`) via la carte dédiée
    // de l'onglet Modèles. Backend Responses API chatgpt.com/backend-api/codex.
    id: "openai_codex",
    label: "OpenAI — Abonnement ChatGPT",
    flag: "💳",
    needsKey: false,
    defaultModel: "gpt-5.5",
    docsUrl: "https://developers.openai.com/codex/",
  },
  {
    id: "moonshot",
    label: "Moonshot — Kimi K2.x",
    flag: "🌙",  // Endpoint default = international (.ai), drapeau neutre
    needsKey: true,
    defaultModel: "kimi-k2-0905-preview",
    docsUrl: "https://platform.moonshot.ai/",
  },
];

const GOOGLE_SERVICES = [
  { id: "gmail",    label: "Gmail",          icon: Mail,     scopeKey: "googleScopeGmail" },
  { id: "calendar", label: "Google Calendar", icon: Calendar, scopeKey: "googleScopeCalendar" },
  { id: "drive",    label: "Google Drive",    icon: HardDrive, scopeKey: "googleScopeDrive" },
];

// ---------------------------------------------------------------------------
// Password strength helper (miroir des règles CNIL côté backend)
// ---------------------------------------------------------------------------
interface PasswordStrength {
  score: number;       // 0-5
  labelKey: string;    // i18n key under settings.* for the strength level
  color: string;       // Tailwind text color
  barColor: string;    // Tailwind bg color
  hintKeys: string[];  // i18n keys for unmet rules
}

function checkPasswordStrength(pwd: string): PasswordStrength {
  const hintKeys: string[] = [];
  let score = 0;
  if (pwd.length >= 12)           score++; else hintKeys.push("pwdHintLength");
  if (/[A-Z]/.test(pwd))          score++; else hintKeys.push("pwdHintUpper");
  if (/[a-z]/.test(pwd))          score++; else hintKeys.push("pwdHintLower");
  if (/\d/.test(pwd))             score++; else hintKeys.push("pwdHintDigit");
  if (/[^a-zA-Z0-9]/.test(pwd))  score++; else hintKeys.push("pwdHintSpecial");

  const levels = [
    { labelKey: "pwdStrengthVeryWeak", color: "text-red-400",    barColor: "bg-red-500" },
    { labelKey: "pwdStrengthWeak",      color: "text-orange-400", barColor: "bg-orange-500" },
    { labelKey: "pwdStrengthMedium",       color: "text-yellow-400", barColor: "bg-yellow-500" },
    { labelKey: "pwdStrengthGood",         color: "text-lime-400",   barColor: "bg-lime-500" },
    { labelKey: "pwdStrengthStrong",        color: "text-cyber-cyan",barColor: "bg-emerald-500" },
    { labelKey: "pwdStrengthExcellent",   color: "text-cyber-cyan", barColor: "bg-cyber-cyan" },
  ];
  return { score, hintKeys, ...levels[score] };
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface LLMInstance {
  id: string;
  label: string;
  provider: string;
  model: string;
  has_key: boolean;
  created_at: string;
  // Portés par l'instance depuis #272 : avant, fenêtre et tarifs vivaient dans
  // des tables du code qu'on ne pouvait pas éditer — Ely tronquait à 8 192
  // tokens et facturait un tarif inventé sans que rien ne le signale.
  context_window?: number | null;
  max_output_tokens?: number | null;
  input_price_per_million?: number | null;
  output_price_per_million?: number | null;
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

// Represents either a legacy provider id or a LLM instance for display in routing
interface RoutingItem {
  id: string;        // provider id or instance uuid
  label: string;     // display name
  flag: string;      // emoji flag/icon
  isInstance: boolean;
}

const TIER_BADGE_COLORS: Record<string, string> = {
  emerald: "bg-cyber-cyan/10 border-cyber-cyan/30 text-cyber-cyan",
  blue:    "bg-cyber-cyan/10 border-cyber-cyan/30 text-cyber-cyan",
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
  const currentLocale = useLocale();
  const tc = useTranslations("common");
  // admin is read client-side only (localStorage unavailable during SSR)
  const [admin, setAdmin] = useState(false);

  // LLM Instances state
  const [instances, setInstances]   = useState<LLMInstance[]>([]);
  const [instancesLoading, setInstancesLoading] = useState(false);

  // Add instance modal state
  const [showAddModal, setShowAddModal]       = useState(false);
  const [modalProvider, setModalProvider]     = useState("ollama");
  const [modalModel, setModalModel]           = useState("");
  // Chaînes et non nombres : un champ vide doit rester « non renseigné » et
  // non « zéro ». Un modèle local à 0 est gratuit, un modèle sans tarif est
  // inconnu — les confondre ramènerait le tarif générique inventé.
  const [modalCtxWindow, setModalCtxWindow]   = useState("");
  const [modalMaxOut, setModalMaxOut]         = useState("");
  const [modalInPrice, setModalInPrice]       = useState("");
  const [modalOutPrice, setModalOutPrice]     = useState("");
  const [modalLabel, setModalLabel]           = useState("");
  const [modalApiKey, setModalApiKey]         = useState("");
  // When non-null, the modal is in edit mode and PATCH-es this instance
  // instead of creating a new one. Provider is locked (PATCH backend
  // doesn't support changing it — would require deleting and recreating).
  const [editingInstanceId, setEditingInstanceId] = useState<string | null>(null);
  // Neutralise l'auto-remplissage du modèle pour la prochaine ouverture du
  // modal — voir openEditModal.
  const skipAutoModelRef = useRef(false);
  const [modalOllamaModels, setModalOllamaModels] = useState<string[]>([]);
  const [modalSaving, setModalSaving]         = useState(false);

  // Google state
  const [googleConnected, setGoogleConnected] = useState<boolean | null>(null);
  const [googleLoading, setGoogleLoading]     = useState(false);

  // OpenAI Codex (abonnement ChatGPT) state — connexion par import des
  // tokens du CLI officiel, pas de clé API (voir carte onglet Modèles)
  const [codexConnected, setCodexConnected] = useState<boolean | null>(null);
  const [codexAuthJson, setCodexAuthJson]   = useState("");
  const [codexBusy, setCodexBusy]           = useState(false);

  // Change password state
  const [currentPwd, setCurrentPwd]     = useState("");
  const [newPwd, setNewPwd]             = useState("");
  const [confirmPwd, setConfirmPwd]     = useState("");
  const [showCurrentPwd, setShowCurrentPwd] = useState(false);
  const [showNewPwd, setShowNewPwd]         = useState(false);
  const [savingPwd, setSavingPwd]       = useState(false);

  // Tier routing state
  const [tierMeta, setTierMeta]           = useState<TierMeta[]>([]);
  const [tierConfig, setTierConfig]       = useState<TierConfig>({});
  const [tierProviderIds, setTierProviderIds] = useState<string[]>([]);
  const [tierInstances, setTierInstances] = useState<Array<{id: string; label: string; provider: string; model: string; has_key: boolean}>>([]);
  const [savingTiers, setSavingTiers]     = useState(false);
  const [tierTooltip, setTierTooltip]     = useState<string | null>(null);
  // Mono-agent mode toggle (mai 2026) — bypass router, force `general` everywhere
  const [monoAgent, setMonoAgent]         = useState<boolean>(false);
  const [monoAgentSaving, setMonoAgentSaving] = useState<boolean>(false);

  // Desktop state
  const [desktopConnected, setDesktopConnected] = useState<boolean | null>(null);
  const [desktopPlatform, setDesktopPlatform]   = useState<string>("");
  const [desktopVersion, setDesktopVersion]     = useState<string>("");
  const [sandboxDirs, setSandboxDirs]           = useState<string[]>([]);
  const [sandboxInput, setSandboxInput]         = useState<string>("");
  const [savingDesktop, setSavingDesktop]       = useState(false);
  const [desktopBinaries, setDesktopBinaries]  = useState<Array<{os: string; arch: string; filename: string; url: string}>>([]);
  const desktopPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Active tab — initialised on mount once we know the role
  const [activeTab, setActiveTab] = useState<string>("integrations");

  // Toasts — extracted early so all callbacks below can capture `push`
  // from the lexical scope. Moving this up was a defensive cleanup
  // (the original placement at the bottom worked thanks to JS closure
  // laziness, but a code reviewer flagged it as TDZ-fragile).
  const { toasts, push } = useToasts();

  // ── Telegram channel config state ───────────────────────────────────────
  // ⚠️ AUDIT 02/09/2026 : cet onglet pilotait quatre canaux. WhatsApp (pont
  // neonize QR + Meta Cloud), Discord et Slack sont partis sous
  // `archive/canaux` — zéro appel de modèle en cinq mois de production. Leurs
  // formulaires n'offraient qu'un endroit où coller un jeton sans effet.
  const [tgStatus, setTgStatus] = useState<{ configured: boolean; bot_username?: string | null; running: boolean }>({ configured: false, running: false });
  const [tgToken, setTgToken] = useState("");
  const [tgBusy, setTgBusy] = useState(false);

  const refreshChannelsStatus = useCallback(async () => {
    try {
      const tg = await authFetch(`${API_URL}/api/channels/telegram/status`)
        .then((r) => r.ok ? r.json() : null)
        .catch(() => null);
      if (tg) setTgStatus(tg);
    } catch {/* silent */}
  }, []);

  useEffect(() => {
    if (activeTab === "channels") refreshChannelsStatus();
  }, [activeTab, refreshChannelsStatus]);

  const handleTgSave = useCallback(async () => {
    const token = tgToken.trim();
    if (!token) { push("error", t("tgPasteToken")); return; }
    setTgBusy(true);
    try {
      const res = await authFetch(`${API_URL}/api/channels/telegram/save`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const data = await res.json();
      if (res.ok && data.saved) {
        push("success", t("tgConfigured", { username: data.bot_username }));
        setTgToken("");
        await refreshChannelsStatus();
      } else {
        push("error", data.detail || t("invalidToken"));
      }
    } catch { push("error", t("tgNetworkError")); }
    finally { setTgBusy(false); }
  }, [tgToken, refreshChannelsStatus, t, push]);

  const handleTgDisable = useCallback(async () => {
    if (!confirm(t("tgDisableConfirm"))) return;
    setTgBusy(true);
    try {
      await authFetch(`${API_URL}/api/channels/telegram/disable`, { method: "POST" });
      push("success", t("tgDisabled"));
      await refreshChannelsStatus();
    } finally { setTgBusy(false); }
  }, [refreshChannelsStatus, t, push]);

  // Initialise admin role and default tab once mounted (client-side only).
  // Honour ?tab=<id> in the URL so the LicenceBanner CTA can deep-link straight
  // to the Licence panel — and react to subsequent URL changes (e.g. clicking
  // the banner while already on /settings just updates ?tab without remounting,
  // so we must re-sync activeTab when the search params change).
  const searchParams = useSearchParams();
  useEffect(() => {
    setAdmin(isAdmin());
  }, []);
  useEffect(() => {
    const a = isAdmin();
    let nextTab: string = a ? "modeles" : "integrations";
    const allowed = ["modeles", "routage", "outils", "integrations", "channels", "hitl", "licence", "compte"];
    const requested = searchParams?.get("tab");
    if (requested && allowed.includes(requested)) {
      nextTab = requested;
    }
    setActiveTab(nextTab);
  }, [searchParams]);

  // ---------------------------------------------------------------------------
  // Load LLM instances from API
  // ---------------------------------------------------------------------------
  const loadInstances = useCallback(async () => {
    setInstancesLoading(true);
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm/instances`);
      if (!res.ok) return;
      const data: LLMInstance[] = await res.json();
      setInstances(data);
    } catch {
      // silently ignore
    } finally {
      setInstancesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (admin) loadInstances();
  }, [admin, loadInstances]);

  // ---------------------------------------------------------------------------
  // OpenAI Codex (abonnement ChatGPT) — statut + import + déconnexion
  // ---------------------------------------------------------------------------
  const loadCodexStatus = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm/codex/status`);
      if (!res.ok) return;
      const d = await res.json();
      setCodexConnected(!!d.connected);
    } catch {
      // silently ignore
    }
  }, []);

  useEffect(() => {
    if (admin) loadCodexStatus();
  }, [admin, loadCodexStatus]);

  const handleCodexImport = async () => {
    if (!codexAuthJson.trim()) return;
    setCodexBusy(true);
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm/codex/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auth_json: codexAuthJson.trim() }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? t("errorStatus", { status: res.status }));
        return;
      }
      setCodexConnected(true);
      setCodexAuthJson("");
      push("success", t("codexConnectedToast"));
    } catch {
      push("error", t("serverUnreachable"));
    } finally {
      setCodexBusy(false);
    }
  };

  const handleCodexDisconnect = async () => {
    setCodexBusy(true);
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm/codex`, {
        method: "DELETE",
      });
      if (res.ok) {
        setCodexConnected(false);
        push("success", t("codexDisconnectedToast"));
      }
    } catch {
      push("error", t("serverUnreachable"));
    } finally {
      setCodexBusy(false);
    }
  };

  // Load tier routing config
  const loadTierConfig = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm/tiers`);
      if (!res.ok) return;
      const d = await res.json();
      setTierMeta(d.tiers ?? []);
      setTierConfig(d.config ?? {});
      setTierProviderIds(d.provider_ids ?? []);
      setTierInstances(d.instances ?? []);
    } catch {
      // silently ignore
    }
  }, []);

  useEffect(() => {
    loadTierConfig();
  }, [loadTierConfig]);

  // Load mono-agent flag (admin only)
  const loadMonoAgent = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm/mono-agent`);
      if (!res.ok) return;
      const d = await res.json();
      setMonoAgent(!!d.enabled);
    } catch { /* silently ignore */ }
  }, []);

  useEffect(() => {
    if (admin) loadMonoAgent();
  }, [admin, loadMonoAgent]);

  const handleToggleMonoAgent = async () => {
    if (monoAgentSaving) return;
    const next = !monoAgent;
    setMonoAgentSaving(true);
    setMonoAgent(next); // optimistic
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm/mono-agent`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next }),
      });
      if (!res.ok) {
        setMonoAgent(!next); // rollback
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? `HTTP ${res.status}`);
      } else {
        push("success", next ? t("monoAgentEnabledToast") : t("monoAgentDisabledToast"));
      }
    } catch {
      setMonoAgent(!next);
      push("error", t("serverUnreachable"));
    } finally {
      setMonoAgentSaving(false);
    }
  };

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
  // Modal: load Ollama models when provider changes to "ollama"
  // ---------------------------------------------------------------------------
  useEffect(() => {
    // Ne fetcher que si le modal est réellement ouvert
    if (!showAddModal) return;

    // Ouverture en édition : le modèle enregistré vient d'être posé, ne pas
    // le remplacer par le défaut du fournisseur.
    if (skipAutoModelRef.current) {
      skipAutoModelRef.current = false;
      return;
    }

    if (modalProvider !== "ollama") {
      // Auto-set default model for cloud providers
      const p = PROVIDERS.find((pp) => pp.id === modalProvider);
      if (p) {
        setModalModel(p.defaultModel);
        setModalLabel(`${p.label} — ${p.defaultModel}`);
      }
      return;
    }
    setModalModel("");
    setModalLabel("");
    authFetch(`${API_URL}/api/settings/llm/ollama-models`)
      .then((r) => r.ok ? r.json() : [])
      .then((data: string[]) => {
        setModalOllamaModels(data);
        if (data.length > 0) {
          setModalModel(data[0]);
          setModalLabel(`Ollama — ${data[0]}`);
        }
      })
      .catch(() => setModalOllamaModels([]));
  }, [modalProvider, showAddModal]);

  // Update label when model changes in modal
  useEffect(() => {
    if (!modalModel) return;
    const p = PROVIDERS.find((pp) => pp.id === modalProvider);
    if (!p) return;
    // Only auto-update label if it looks like it was auto-generated (contains provider label)
    const autoPrefix = modalProvider === "ollama" ? "Ollama — " : `${p.label} — `;
    setModalLabel((prev) => {
      if (!prev || prev.startsWith(autoPrefix)) {
        return `${autoPrefix}${modalModel}`;
      }
      return prev;
    });
  }, [modalModel, modalProvider]);

  // ---------------------------------------------------------------------------
  // Handlers — LLM Instances
  // ---------------------------------------------------------------------------

  const openAddModal = () => {
    setEditingInstanceId(null);
    setModalProvider("ollama");
    setModalModel("");
    setModalLabel("");
    setModalApiKey("");
    setShowAddModal(true);
  };

  const openEditModal = (inst: LLMInstance) => {
    // L'effet d'auto-remplissage ci-dessous se déclenche à CHAQUE ouverture du
    // modal (il dépend de `showAddModal`). En édition, il écrasait le modèle
    // enregistré par le défaut du fournisseur : Franck voyait revenir
    // « kimi-k2-0905-preview » alors que sa base contenait bien « kimi-k3 »,
    // et valider aurait détruit sa valeur. Ce drapeau le neutralise pour la
    // seule ouverture ; un changement de fournisseur ENSUITE doit continuer de
    // proposer le modèle par défaut.
    skipAutoModelRef.current = true;
    setEditingInstanceId(inst.id);
    setModalProvider(inst.provider);
    setModalModel(inst.model);
    setModalLabel(inst.label);
    setModalCtxWindow(inst.context_window != null ? String(inst.context_window) : "");
    setModalMaxOut(inst.max_output_tokens != null ? String(inst.max_output_tokens) : "");
    setModalInPrice(inst.input_price_per_million != null ? String(inst.input_price_per_million) : "");
    setModalOutPrice(inst.output_price_per_million != null ? String(inst.output_price_per_million) : "");
    // API key field stays empty in edit mode — typing here replaces the
    // stored key, leaving it blank keeps the existing one untouched.
    setModalApiKey("");
    setShowAddModal(true);
  };

  const closeModal = () => {
    setShowAddModal(false);
    setEditingInstanceId(null);
    setModalCtxWindow("");
    setModalMaxOut("");
    setModalInPrice("");
    setModalOutPrice("");
  };

  const handleSubmitInstance = async () => {
    if (modalSaving || !modalLabel.trim() || !modalModel.trim()) return;
    setModalSaving(true);
    try {
      // Champ vide = non renseigné : on n'envoie rien, le backend garde la
      // valeur existante. `null` explicite serait interprété comme « ne
      // touche pas » côté API ; pour effacer, on envoie 0.
      const numOrUndef = (v: string): number | undefined => {
        const t2 = v.trim();
        if (!t2) return undefined;
        const n = Number(t2);
        return Number.isFinite(n) && n >= 0 ? n : undefined;
      };

      if (editingInstanceId) {
        // ── PATCH (edit existing) ──────────────────────────────────────
        // Provider is intentionally NOT sent — backend doesn't accept it
        // on PATCH. label/model always sent, api_key only if user typed
        // a new one (empty = keep existing key).
        const body: {
          label: string; model: string; api_key?: string;
          context_window?: number; max_output_tokens?: number;
          input_price_per_million?: number; output_price_per_million?: number;
        } = {
          label: modalLabel.trim(),
          model: modalModel.trim(),
        };
        if (modalApiKey.trim()) body.api_key = modalApiKey.trim();
        const cw = numOrUndef(modalCtxWindow);
        const ip = numOrUndef(modalInPrice);
        const op = numOrUndef(modalOutPrice);
        const mo = numOrUndef(modalMaxOut);
        if (cw !== undefined) body.context_window = cw;
        if (mo !== undefined) body.max_output_tokens = mo;
        if (ip !== undefined) body.input_price_per_million = ip;
        if (op !== undefined) body.output_price_per_million = op;

        const res = await authFetch(
          `${API_URL}/api/settings/llm/instances/${editingInstanceId}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          },
        );
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          push("error", err.detail ?? t("errorStatus", { status: res.status }));
          return;
        }
        push("success", t("instanceUpdated"));
      } else {
        // ── POST (create new) ──────────────────────────────────────────
        const body: {
          label: string; provider: string; model: string; api_key?: string;
          context_window?: number; max_output_tokens?: number;
          input_price_per_million?: number; output_price_per_million?: number;
        } = {
          label: modalLabel.trim(),
          provider: modalProvider,
          model: modalModel.trim(),
        };
        if (modalApiKey.trim()) body.api_key = modalApiKey.trim();
        const cwN = numOrUndef(modalCtxWindow);
        const ipN = numOrUndef(modalInPrice);
        const opN = numOrUndef(modalOutPrice);
        const moN = numOrUndef(modalMaxOut);
        if (cwN !== undefined) body.context_window = cwN;
        if (moN !== undefined) body.max_output_tokens = moN;
        if (ipN !== undefined) body.input_price_per_million = ipN;
        if (opN !== undefined) body.output_price_per_million = opN;

        const res = await authFetch(`${API_URL}/api/settings/llm/instances`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          push("error", err.detail ?? t("errorStatus", { status: res.status }));
          return;
        }
        push("success", t("instanceCreated"));
      }

      closeModal();
      await loadInstances();
      // Refresh tier config to get updated instances list
      await loadTierConfig();
    } catch {
      push("error", t("serverUnreachable"));
    } finally {
      setModalSaving(false);
    }
  };

  const handleDeleteInstance = async (id: string) => {
    try {
      const res = await authFetch(`${API_URL}/api/settings/llm/instances/${id}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        const err = await res.json().catch(() => ({}));
        push("error", err.detail ?? t("errorStatus", { status: res.status }));
        return;
      }
      push("success", t("instanceDeleted"));
      setInstances((prev) => prev.filter((i) => i.id !== id));
      // Remove from tier configs that reference this instance
      setTierConfig((prev) => {
        const next: TierConfig = {};
        for (const [tid, entry] of Object.entries(prev)) {
          next[tid] = { ...entry, providers: entry.providers.filter((p) => p !== id) };
        }
        return next;
      });
      // Refresh tier config to get updated instances list
      await loadTierConfig();
    } catch {
      push("error", t("serverUnreachable"));
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
      if (!res.ok) throw new Error(data.detail || t("serverErrorStatus", { status: res.status }));
      if (!data.url) throw new Error(t("googleAuthUrlMissing"));
      window.location.href = data.url;
    } catch (e) {
      alert(e instanceof Error ? e.message : t("googleConnectError"));
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

  // Build the combined routing items list (instances + legacy providers for routing tab display)
  const buildRoutingItems = (): RoutingItem[] => {
    const items: RoutingItem[] = [];
    // Named instances first
    for (const inst of tierInstances) {
      const p = PROVIDERS.find((pp) => pp.id === inst.provider);
      items.push({
        id: inst.id,
        label: inst.label,
        flag: p?.flag ?? "🤖",
        isInstance: true,
      });
    }
    // Legacy provider IDs
    for (const pid of tierProviderIds) {
      const p = PROVIDERS.find((pp) => pp.id === pid);
      items.push({
        id: pid,
        label: p?.label ?? pid,
        flag: p?.flag ?? "🤖",
        isInstance: false,
      });
    }
    return items;
  };

  const routingItems = buildRoutingItems();

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
        push("error", err.detail ?? t("errorStatus", { status: res.status }));
      } else {
        push("success", t("tiersSaved"));
      }
    } catch {
      push("error", t("serverUnreachable"));
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
        push("error", err.detail ?? t("errorStatus", { status: res.status }));
      } else {
        push("success", t("desktopConfigSaved"));
      }
    } catch {
      push("error", t("serverUnreachable"));
    } finally {
      setSavingDesktop(false);
    }
  };

  const handleDownloadConfig = async () => {
    try {
      const res = await authFetch(`${API_URL}/api/desktop/download-config`);
      if (!res.ok) {
        push("error", t("desktopConfigGenError"));
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
      push("error", t("desktopDownloadError"));
    }
  };

  // ---------------------------------------------------------------------------
  // Handlers — Change password
  // ---------------------------------------------------------------------------
  const handleChangePassword = async () => {
    if (savingPwd) return;
    if (newPwd !== confirmPwd) {
      push("error", t("pwdMismatchError"));
      return;
    }
    const strength = checkPasswordStrength(newPwd);
    if (strength.score < 5) {
      push("error", t("pwdNotStrongEnough"));
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
        push("error", err.detail ?? t("errorStatus", { status: res.status }));
      } else {
        push("success", t("pwdChangedSuccess"));
        setCurrentPwd("");
        setNewPwd("");
        setConfirmPwd("");
      }
    } catch {
      push("error", t("serverUnreachable"));
    } finally {
      setSavingPwd(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  // Resolve a routing item id to a RoutingItem for display
  const resolveRoutingItem = (id: string): RoutingItem => {
    const found = routingItems.find((ri) => ri.id === id);
    if (found) return found;
    const p = PROVIDERS.find((pp) => pp.id === id);
    return { id, label: p?.label ?? id, flag: p?.flag ?? "🤖", isInstance: false };
  };

  const selectedModalProvider = PROVIDERS.find((p) => p.id === modalProvider);

  // Tab definitions — admin-only tabs are hidden for regular users
  const TABS = [
    ...(admin ? [
      { id: "modeles",      label: t("tabModels"),         icon: Cpu        },
      { id: "routage",      label: t("tabRouting"),        icon: GitBranch  },
    ] : []),
    { id: "outils",       label: "Outils",               icon: Wrench     },
    { id: "integrations", label: t("tabIntegrations"),  icon: Plug       },
    { id: "channels",     label: t("tabChannels"),       icon: Mail       },
    { id: "hitl",         label: t("tabHitl"),           icon: ShieldCheck },
    { id: "licence",      label: "Licence",              icon: KeyRound   },
    { id: "compte",       label: t("tabAccount"),        icon: User       },
  ];

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <LicenceBanner />
        <div className="flex flex-1 overflow-hidden">
          <main className="flex flex-col flex-1 overflow-hidden" style={{ background: "var(--bg-app)" }}>

          {/* Toast stack */}
          <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 pointer-events-none">
            {toasts.map((toast) => (
              <div
                key={toast.id}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-lg border text-xs shadow-lg pointer-events-auto transition-all ${
                  toast.kind === "success"
                    ? "bg-emerald-900/80 border-cyber-cyan/30 text-cyber-cyan"
                    : "bg-red-900/80 border-red-500/30 text-red-300"
                }`}
              >
                {toast.kind === "success"
                  ? <Check className="w-3.5 h-3.5 shrink-0" />
                  : <AlertCircle className="w-3.5 h-3.5 shrink-0" />}
                {toast.message}
              </div>
            ))}
          </div>

          {/* ── Tab navigation bar ────────────────────────────────────── */}
          <div className="shrink-0 px-6" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
            <nav style={{ display: "flex", gap: 4 }}>
              {TABS.map(({ id, label, icon: Icon }) => {
                const isActive = activeTab === id;
                return (
                  <button
                    key={id}
                    onClick={() => setActiveTab(id)}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "12px 16px",
                      fontSize: 14,
                      fontWeight: 500,
                      color: isActive ? "var(--text-primary)" : "var(--text-tertiary)",
                      background: "transparent",
                      border: "none",
                      borderBottom: `2px solid ${isActive ? "var(--accent)" : "transparent"}`,
                      marginBottom: -1,
                      transition: "all 0.15s var(--ease)",
                      cursor: "pointer",
                    }}
                    onMouseEnter={(e) => {
                      if (!isActive) e.currentTarget.style.color = "var(--text-primary)";
                    }}
                    onMouseLeave={(e) => {
                      if (!isActive) e.currentTarget.style.color = "var(--text-tertiary)";
                    }}
                  >
                    <Icon className="w-4 h-4" />
                    {label}
                  </button>
                );
              })}
            </nav>
          </div>

          {/* ── Tab content ───────────────────────────────────────────── */}
          <div className="flex-1 overflow-y-auto p-6">
          {/* Pleine largeur disponible — le max-w-3xl original contraignait
              les tableaux Routage et Modèles à ~768px. Demande Franck mai 2026. */}
          <div className="space-y-6" style={{ width: "100%" }}>

            {/* ================================================================
                TAB: Modèles IA — instance list
            ================================================================ */}
            {admin && activeTab === "modeles" && (
              <section>
                {/* Header */}
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Cpu className="w-4 h-4 text-cyber-cyan" />
                    <h2 className="text-sm font-medium text-text-primary">{t("modelsConfigured")}</h2>
                    {instancesLoading && (
                      <span className="text-[10px] text-text-muted animate-pulse">{t("loading")}</span>
                    )}
                  </div>
                  <button
                    onClick={openAddModal}
                    className="btn primary"
                  >
                    <Plus size={14} />
                    {t("add")}
                  </button>
                </div>

                <p className="tab-intro">
                  {t("instanceDescription")}
                </p>

                {/* Instance list */}
                {instances.length === 0 && !instancesLoading ? (
                  <div className="bg-bg-secondary border border-border-dim rounded-lg p-6 text-center">
                    <p className="text-[11px] text-text-muted italic">
                      {t("noInstances")}
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {instances.map((inst) => {
                      const p = PROVIDERS.find((pp) => pp.id === inst.provider);
                      return (
                        <div
                          key={inst.id}
                          className="flex items-center justify-between gap-3 bg-bg-secondary border border-border-dim rounded-lg px-4 py-3"
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            <span className="text-base shrink-0">{p?.flag ?? "🤖"}</span>
                            <div className="min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-xs font-medium text-text-primary">{inst.label}</span>
                                {inst.has_key && (
                                  <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded bg-cyber-cyan/10 border border-cyber-cyan/20 text-cyber-cyan shrink-0">
                                    <Key className="w-2 h-2" />
                                    {t("keyBadge")}
                                  </span>
                                )}
                              </div>
                              <div className="text-[10px] text-text-muted mt-0.5">
                                {inst.provider}/{inst.model}
                              </div>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <button
                              onClick={() => openEditModal(inst)}
                              className="text-text-muted hover:text-cyber-cyan transition-colors"
                              title={t("edit")}
                              aria-label={t("edit")}
                            >
                              <Pencil className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => handleDeleteInstance(inst.id)}
                              className="text-text-muted hover:text-cyber-red transition-colors"
                              title={t("delete")}
                              aria-label={t("delete")}
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* ── OpenAI Codex — abonnement ChatGPT (pas de clé API) ── */}
                <div className="mt-6 bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-base shrink-0">💳</span>
                      <h3 className="text-xs font-medium text-text-primary truncate">{t("codexTitle")}</h3>
                      {codexConnected !== null && (
                        <span className={`text-[9px] px-1.5 py-0.5 rounded border shrink-0 ${
                          codexConnected
                            ? "bg-cyber-cyan/10 border-cyber-cyan/20 text-cyber-cyan"
                            : "bg-bg-primary border-border-dim text-text-muted"
                        }`}>
                          {codexConnected ? t("codexBadgeConnected") : t("codexBadgeNotConnected")}
                        </span>
                      )}
                    </div>
                    {codexConnected && (
                      <button
                        onClick={handleCodexDisconnect}
                        disabled={codexBusy}
                        className="text-[10px] px-2 py-1 rounded border border-border-dim text-text-muted hover:text-cyber-red hover:border-cyber-red/40 transition-all disabled:opacity-40"
                      >
                        {t("codexDisconnect")}
                      </button>
                    )}
                  </div>
                  <p className="text-[10px] text-text-muted whitespace-pre-line">
                    {t("codexDescription")}
                  </p>
                  {!codexConnected && (
                    <div className="space-y-2">
                      <textarea
                        value={codexAuthJson}
                        onChange={(e) => setCodexAuthJson(e.target.value)}
                        placeholder={t("codexPlaceholder")}
                        rows={4}
                        spellCheck={false}
                        className="w-full text-[10px] font-mono bg-bg-primary border border-border-dim rounded px-3 py-2 text-text-primary focus:outline-none focus:border-cyber-cyan/40 resize-y"
                      />
                      <button
                        onClick={handleCodexImport}
                        disabled={codexBusy || !codexAuthJson.trim()}
                        className="text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 bg-cyber-cyan/10 text-cyber-cyan hover:bg-cyber-cyan/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        {codexBusy ? t("codexImporting") : t("codexImport")}
                      </button>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* ================================================================
                TAB: Routage
            ================================================================ */}
            {admin && activeTab === "routage" && tierMeta.length > 0 && (
              <section>
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <GitBranch className="w-4 h-4 text-cyber-cyan" />
                    <h2 className="text-sm font-medium text-text-primary">{t("routingTiers")}</h2>
                  </div>
                  <button
                    onClick={handleSaveTiers}
                    disabled={savingTiers}
                    className="btn primary"
                  >
                    <Check size={14} />
                    {savingTiers ? "…" : t("save")}
                  </button>
                </div>

                <p className="tab-intro">
                  {t("routingDescription")}
                </p>

                {/* ── Mono-agent mode toggle (mai 2026) ────────────────────
                    Court-circuite tout le routeur (keyword + LLM + sticky)
                    et envoie chaque requête sur le specialist `general` qui
                    a accès à TOUS les tools. Idéal pour valider un nouveau
                    modèle agentique long-contexte (Kimi K2.6 par ex.) sans
                    subir les erreurs de classification. ─────────────────── */}
                <div
                  className="card"
                  style={{
                    width: "100%",
                    marginBottom: 16,
                    borderColor: monoAgent ? "var(--accent)" : "var(--border-subtle)",
                    background: monoAgent ? "var(--accent-soft)" : "var(--bg-surface)",
                    transition: "all 0.15s var(--ease)",
                  }}
                >
                  <div className="flex items-start justify-between gap-4" style={{ padding: 4 }}>
                    <div style={{ flex: 1 }}>
                      <div className="flex items-center gap-2 mb-1">
                        <Zap size={14} style={{ color: monoAgent ? "var(--accent)" : "var(--text-secondary)" }} />
                        <h3 className="text-sm font-semibold" style={{ color: monoAgent ? "var(--accent)" : "var(--text-primary)" }}>
                          {t("monoAgentTitle")} {monoAgent && `— ${t("monoAgentActive")}`}
                        </h3>
                      </div>
                      <p className="text-xs" style={{ color: "var(--text-secondary)", lineHeight: 1.5 }}>
                        {t.rich("monoAgentDescription", {
                          code: (chunks) => <code style={{ color: "var(--accent)" }}>{chunks}</code>,
                          strong: (chunks) => <strong>{chunks}</strong>,
                        })}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={handleToggleMonoAgent}
                      disabled={monoAgentSaving}
                      role="switch"
                      aria-checked={monoAgent}
                      title={monoAgent ? t("monoAgentDisable") : t("monoAgentEnable")}
                      style={{
                        position: "relative",
                        width: 44,
                        height: 24,
                        borderRadius: 999,
                        border: "1px solid " + (monoAgent ? "var(--accent)" : "var(--border-subtle)"),
                        background: monoAgent ? "var(--accent)" : "var(--bg-surface-2)",
                        cursor: monoAgentSaving ? "wait" : "pointer",
                        transition: "all 0.15s var(--ease)",
                        flexShrink: 0,
                        marginTop: 4,
                      }}
                    >
                      <span
                        style={{
                          position: "absolute",
                          top: 2,
                          left: monoAgent ? 22 : 2,
                          width: 18,
                          height: 18,
                          borderRadius: "50%",
                          background: monoAgent ? "var(--text-on-accent)" : "var(--text-secondary)",
                          transition: "left 0.15s var(--ease), background 0.15s var(--ease)",
                        }}
                      />
                    </button>
                  </div>
                </div>

                {routingItems.length === 0 && (
                  <div className="mb-3 p-3 bg-amber-500/5 border border-amber-500/20 rounded-lg">
                    <p className="text-[11px] text-amber-400">
                      {t("routingNoInstances")}
                    </p>
                  </div>
                )}

                <div className="space-y-4">
                  {tierMeta.map((tier) => {
                    const entry: TierEntry = tierConfig[tier.id] ?? { providers: [], fallback_enabled: true };
                    const badgeCls = TIER_BADGE_COLORS[tier.color] ?? TIER_BADGE_COLORS.slate;
                    const availableToAdd = routingItems.filter((ri) => !entry.providers.includes(ri.id));

                    return (
                      <div key={tier.id} className="card" style={{ width: "100%" }}>
                        {/* Header */}
                        <div className="flex items-center justify-between gap-3 mb-4">
                          <div className="flex items-center gap-3 min-w-0">
                            <span className={`text-[10px] font-bold px-2 py-1 rounded border shrink-0 ${badgeCls}`}>
                              {tier.badge}
                            </span>
                            <span className="text-sm font-medium text-text-primary">
                              {t.has(`tierLabels.${tier.id}`) ? t(`tierLabels.${tier.id}`) : tier.label}
                            </span>
                            <button
                              onClick={() => setTierTooltip(tierTooltip === tier.id ? null : tier.id)}
                              className="text-text-muted hover:text-text-secondary transition-colors shrink-0"
                              title={t("explanation")}
                            >
                              <Info className="w-3.5 h-3.5" />
                            </button>
                          </div>
                          {/* Fallback toggle */}
                          <button
                            onClick={() => toggleTierFallback(tier.id)}
                            className="flex items-center gap-1.5 text-[11px] shrink-0 transition-colors"
                            title={entry.fallback_enabled ? t("disableFallback") : t("enableFallback")}
                          >
                            {entry.fallback_enabled
                              ? <ToggleRight className="w-5 h-5 text-cyber-cyan" />
                              : <ToggleLeft className="w-5 h-5 text-text-muted" />}
                            <span className={entry.fallback_enabled ? "text-cyber-cyan" : "text-text-muted"}>
                              {entry.fallback_enabled ? t("fallbackEnabled") : t("fallbackDisabled")}
                            </span>
                          </button>
                        </div>

                        {/* Tooltip description */}
                        {tierTooltip === tier.id && (
                          <p className="text-[11px] text-text-muted bg-bg-primary rounded px-3 py-2 mb-3 border border-border-dim">
                            {t.has(`tierDescriptions.${tier.id}`) ? t(`tierDescriptions.${tier.id}`) : tier.description}
                          </p>
                        )}

                        {/* Ordered provider / instance list */}
                        <div className="space-y-2">
                          {entry.providers.length === 0 && (
                            <p className="text-[11px] text-text-muted italic">{t("noTierModels")}</p>
                          )}
                          {entry.providers.map((provId, idx) => {
                            const item = resolveRoutingItem(provId);
                            const isFirst = idx === 0;
                            const isLast  = idx === entry.providers.length - 1;
                            return (
                              <div
                                key={provId}
                                className="flex items-center gap-2"
                                style={{
                                  background: "var(--bg-surface-2)",
                                  border: "1px solid var(--border-subtle)",
                                  borderRadius: "var(--radius-md)",
                                  padding: "8px 12px",
                                  width: "100%",
                                }}
                              >
                                {/* Priority number */}
                                <span className="text-[10px] text-text-muted w-5 text-right shrink-0 font-mono">
                                  {idx + 1}.
                                </span>
                                {/* Flag + label, full width */}
                                <span className="text-base leading-none shrink-0">{item.flag}</span>
                                <span className="flex-1 truncate text-sm text-text-primary">{item.label}</span>

                                {/* Right-side controls: arrows up/down stacked + delete */}
                                <div
                                  style={{
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: 1,
                                    flexShrink: 0,
                                  }}
                                >
                                  <button
                                    onClick={() => moveTierProvider(tier.id, idx, -1)}
                                    disabled={isFirst}
                                    className="icon-btn"
                                    style={{ width: 22, height: 16 }}
                                    title={t("moveUp")}
                                  >
                                    <ChevronUp size={12} />
                                  </button>
                                  <button
                                    onClick={() => moveTierProvider(tier.id, idx, 1)}
                                    disabled={isLast}
                                    className="icon-btn"
                                    style={{ width: 22, height: 16 }}
                                    title={t("moveDown")}
                                  >
                                    <ChevronDown size={12} />
                                  </button>
                                </div>

                                {/* Delete */}
                                <button
                                  onClick={() => removeTierProvider(tier.id, provId)}
                                  className="icon-btn"
                                  style={{
                                    width: 28,
                                    height: 28,
                                    color: "var(--text-tertiary)",
                                  }}
                                  title={t("remove")}
                                >
                                  <Trash2 size={14} />
                                </button>
                              </div>
                            );
                          })}
                        </div>

                        {/* Add dropdown */}
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
                              <option value="">{t("addModelOption")}</option>
                              {/* Instances group */}
                              {availableToAdd.filter((ri) => ri.isInstance).length > 0 && (
                                <optgroup label={t("namedInstancesGroup")}>
                                  {availableToAdd.filter((ri) => ri.isInstance).map((ri) => (
                                    <option key={ri.id} value={ri.id}>
                                      {ri.flag} {ri.label}
                                    </option>
                                  ))}
                                </optgroup>
                              )}
                              {/* Legacy providers group */}
                              {availableToAdd.filter((ri) => !ri.isInstance).length > 0 && (
                                <optgroup label={t("genericProvidersGroup")}>
                                  {availableToAdd.filter((ri) => !ri.isInstance).map((ri) => (
                                    <option key={ri.id} value={ri.id}>
                                      {ri.flag} {ri.label}
                                    </option>
                                  ))}
                                </optgroup>
                              )}
                            </select>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* ================================================================
                TAB: Intégrations
            ================================================================ */}
            {activeTab === "outils" && (
              <section className="space-y-4">
                <div>
                  <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                    Outils envoyés au modèle
                  </h2>
                  <p className="mt-1 text-sm text-[var(--text-secondary)]">
                    Chaque outil actif part dans le prompt à chaque tour. Couper
                    une compétence dont vous ne vous servez pas allège toutes les
                    conversations.
                  </p>
                </div>
                <ToolCatalogSection />
              </section>
            )}

            {activeTab === "integrations" && (
            <section className="vstack" style={{ gap: 16 }}>
              {/* ── Services Google ── */}
              <div className="section-block">
                <div className="section-block-head">
                  <h3>
                    <ExternalLink size={16} style={{ color: "var(--accent)" }} />
                    {t("googleServices")}
                    {googleConnected === true && (
                      <span className="badge accent">
                        <CheckCircle className="w-2.5 h-2.5" /> {tc("connected")}
                      </span>
                    )}
                    {googleConnected === false && (
                      <span className="badge">
                        <XCircle className="w-2.5 h-2.5" /> {tc("disconnected")}
                      </span>
                    )}
                  </h3>
                </div>

                <div className="vstack" style={{ gap: 8 }}>
                  {GOOGLE_SERVICES.map(({ id, label, icon: Icon, scopeKey }) => (
                    <div
                      key={id}
                      className="hstack"
                      style={{
                        padding: "10px 12px",
                        background: "var(--bg-surface-2)",
                        borderRadius: "var(--radius-sm)",
                      }}
                    >
                      <div
                        style={{
                          width: 28,
                          height: 28,
                          borderRadius: "var(--radius-sm)",
                          background: googleConnected ? "var(--success-soft)" : "var(--bg-surface)",
                          border: `1px solid ${googleConnected ? "var(--success)" : "var(--border-subtle)"}`,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          flexShrink: 0,
                        }}
                      >
                        <Icon size={14} style={{ color: googleConnected ? "var(--success)" : "var(--text-muted)" }} />
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>{label}</div>
                        <div className="muted mono" style={{ fontSize: 11 }}>{t(scopeKey as never)}</div>
                      </div>
                      {googleConnected && (
                        <span className="badge accent">
                          <Check className="w-2.5 h-2.5" />
                        </span>
                      )}
                    </div>
                  ))}
                </div>

                <div className="callout">
                  <ShieldCheck size={14} />
                  <span>{t("googlePrivacyNote")}</span>
                </div>

                <div>
                  {googleConnected ? (
                    <button
                      onClick={handleGoogleDisconnect}
                      disabled={googleLoading}
                      className="btn danger"
                    >
                      {googleLoading ? "..." : t("disconnectGoogle")}
                    </button>
                  ) : (
                    <button
                      onClick={handleGoogleConnect}
                      disabled={googleLoading}
                      className="btn primary"
                    >
                      <ExternalLink size={13} />
                      {googleLoading ? tc("redirecting") : t("connectGoogle")}
                    </button>
                  )}
                </div>

                {googleConnected && (
                  <>
                    <div className="divider" />
                    <GoogleAccountsSection />
                  </>
                )}

                <details style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
                  <summary style={{ cursor: "pointer" }}>{t("howToConfigure")}</summary>
                  <ol className="mt-2 space-y-1 pl-3 list-decimal">
                    <li>{t.rich("googleStep1", { link: (chunks) => <a href="https://console.cloud.google.com/" target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>{chunks}</a> })}</li>
                    <li>{t("googleStep2")}</li>
                    <li>{t("googleStep3")}</li>
                    <li>{t.rich("googleStep4", { code: (chunks) => <code style={{ color: "var(--accent)" }}>{chunks}</code> })}</li>
                    <li>{t.rich("googleStep5", { link: (chunks) => <a href="/admin" style={{ color: "var(--accent)" }}>{chunks}</a> })}</li>
                    <li>{t("googleStep6")}</li>
                  </ol>
                </details>
              </div>
            </section>
            )}

            {/* ================================================================
                TAB: Channels — Telegram
                Card: status badge · help toggle · form · action buttons
            ================================================================ */}
            {activeTab === "channels" && (
            <section className="space-y-8">
              <div>
                <h2 className="text-base font-medium text-text-primary mb-1">{t("channelsTitle")}</h2>
                <p className="tab-intro">
                  {t("channelsIntro")}
                </p>
              </div>

              {/* ── Telegram ──────────────────────────────────────────── */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <span className="brand-logo" style={{ width: 32, height: 32, fontSize: 13, fontWeight: 700 }}>T</span>
                  <h3 className="text-base font-semibold text-text-primary">Telegram</h3>
                  {tgStatus.configured && tgStatus.running && (
                    <span className="badge accent">
                      <CheckCircle className="w-2.5 h-2.5" /> {tgStatus.bot_username ? t("activeNamed", { name: tgStatus.bot_username }) : t("active")}
                    </span>
                  )}
                  {tgStatus.configured && !tgStatus.running && (
                    <span className="badge warning">
                      {t("configuredButStopped")}
                    </span>
                  )}
                  {!tgStatus.configured && (
                    <span className="badge">
                      {t("notConfiguredBadge")}
                    </span>
                  )}
                </div>

                <div className="section-block">
                  <p className="text-[11px] text-text-muted">
                    {t.rich("tgIntro", {
                      strong: (chunks) => <strong>{chunks}</strong>,
                      code: (chunks) => <code className="text-cyber-cyan">{chunks}</code>,
                    })}
                  </p>

                  <div className="flex gap-2 items-center">
                    <input
                      type="password"
                      value={tgToken}
                      onChange={(e) => setTgToken(e.target.value)}
                      placeholder={tgStatus.configured ? t("tgTokenPlaceholderConfigured") : t("tgTokenPlaceholder")}
                      className="input mono"
                      style={{ maxWidth: 480 }}
                    />
                    <button
                      onClick={handleTgSave}
                      disabled={tgBusy || !tgToken.trim()}
                      className="btn primary"
                      style={{ whiteSpace: "nowrap" }}
                    >
                      {tgBusy ? "..." : tgStatus.configured ? t("update") : t("enable")}
                    </button>
                    {tgStatus.configured && (
                      <button
                        onClick={handleTgDisable}
                        disabled={tgBusy}
                        className="btn danger"
                        style={{ whiteSpace: "nowrap" }}
                      >
                        {t("disable")}
                      </button>
                    )}
                  </div>

                  <details className="pt-2 border-t border-border-dim text-[11px] text-text-muted">
                    <summary className="cursor-pointer hover:text-text-secondary">{t("howToConfigure")}</summary>
                    <ol className="mt-2 space-y-1 pl-3 list-decimal">
                      <li>{t.rich("tgHelpStep1", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
                      <li>{t.rich("tgHelpStep2", { code: (chunks) => <code className="text-cyber-cyan">{chunks}</code> })}</li>
                      <li>{t.rich("tgHelpStep3", { code: (chunks) => <code className="text-cyber-cyan">{chunks}</code> })}</li>
                      <li>{t.rich("tgHelpStep4", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
                      <li>{t.rich("tgHelpStep5", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
                      <li>{t.rich("tgHelpStep6", { code: (chunks) => <code className="text-cyber-cyan">{chunks}</code> })}</li>
                      <li>{t("tgHelpStep7")}</li>
                    </ol>
                    <p className="mt-2">
                      {t.rich("tgLatencyNote", {
                        strong: (chunks) => <strong>{chunks}</strong>,
                        code: (chunks) => <code>{chunks}</code>,
                      })}
                    </p>
                  </details>
                </div>
              </div>

            </section>
            )}

            {/* ================================================================
                TAB: HITL preferences (Human-in-the-Loop on/off per tool)
            ================================================================ */}
            {activeTab === "hitl" && (
              <HitlPreferencesSection />
            )}

            {/* ================================================================
                TAB: Licence — tier-aware enforcement (Phase 1)
            ================================================================ */}
            {activeTab === "licence" && (
              <LicenceSection />
            )}

            {/* ================================================================
                TAB: Compte
            ================================================================ */}
            {activeTab === "compte" && (
            <section>
              <div className="flex items-center gap-2 mb-4">
                <Languages className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary">{t("language")}</h2>
              </div>
              <div className="section-block">
                <p className="text-xs text-text-muted">{t("languageDescription")}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setLocale("fr")}
                    className={currentLocale === "fr" ? "btn primary" : "btn"}
                  >
                    {t("french")}
                  </button>
                  <button
                    onClick={() => setLocale("en")}
                    className={currentLocale === "en" ? "btn primary" : "btn"}
                  >
                    {t("english")}
                  </button>
                </div>
              </div>
            </section>
            )}

            {activeTab === "compte" && <SovereigntySection />}

            {/* ----------------------------------------------------------------
                SSH Hosts — in "integrations" tab, admin only
            ---------------------------------------------------------------- */}
            {activeTab === "integrations" && admin && (
              <section className="vstack" style={{ gap: 16, marginTop: 16 }}>
                <div className="section-block">
                  <div className="section-block-head">
                    <h3>
                      <Server size={16} />
                      {t("sshHosts")}
                    </h3>
                  </div>
                  <p>
                    {t.rich("sshConfigDesc", { code: (chunks) => <code className="mono" style={{ color: "var(--accent)" }}>{chunks}</code> })}
                  </p>
                  <pre style={{
                    background: "var(--bg-surface-2)",
                    padding: 12,
                    borderRadius: "var(--radius-md)",
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    color: "var(--text-secondary)",
                    margin: 0,
                    border: "1px solid var(--border-subtle)",
                    overflow: "auto",
                  }}>
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
                ELY Desktop — in "integrations" tab
            ---------------------------------------------------------------- */}
            {activeTab === "integrations" && (<section style={{ marginTop: 16 }}>
              <div className="section-block">
              <div className="section-block-head">
                <h3>
                  <Monitor size={16} />
                  ELY Desktop
                  {desktopConnected === true && (
                    <span className="badge accent">
                      <Wifi className="w-2.5 h-2.5" /> {t("connected")}
                      {desktopPlatform && ` · ${desktopPlatform}`}
                      {desktopVersion && ` v${desktopVersion}`}
                    </span>
                  )}
                  {desktopConnected === false && (
                    <span className="badge warning">
                      <WifiOff className="w-2.5 h-2.5" /> {t("notConnected")}
                    </span>
                  )}
                </h3>
              </div>

              <div className="vstack" style={{ gap: 16 }}>

                {/* Description */}
                <p className="text-xs text-text-muted">
                  {t("desktopDescription")}
                </p>

                {/* Démon absent — ce qu'il faut faire, pas juste le constat.
                    Un badge « non connecté » ne dit pas quoi faire, et cette
                    fonctionnalité peut rester morte des mois sans que
                    personne s'en aperçoive : c'est arrivé (21/08).

                    ⚠️ PAS de bouton « lancer » : une page web ne peut pas
                    démarrer un programme sur la machine de l'utilisateur, et
                    le backend est dans un conteneur — il ne le peut pas non
                    plus. Un bouton qui ne pourrait qu'attendre serait une
                    action annoncée qui n'a pas lieu. On donne les deux vrais
                    leviers à la place. */}
                {desktopConnected === false && (
                  <div className="text-xs border border-amber-500/30 bg-amber-500/5 rounded px-3 py-2.5 space-y-2">
                    <p className="text-amber-400 font-medium">
                      {t("desktopOfflineTitle")}
                    </p>
                    <p className="text-text-secondary">
                      {t("desktopOfflineAutostart")}
                    </p>
                    <code className="block font-mono text-[11px] bg-bg-tertiary border border-border-dim rounded px-2 py-1.5 overflow-x-auto">
                      ./install.sh
                    </code>
                    <p className="text-text-secondary">
                      {t("desktopOfflineMount")}
                    </p>
                    <code className="block font-mono text-[11px] bg-bg-tertiary border border-border-dim rounded px-2 py-1.5 overflow-x-auto">
                      ELY_INDEX_PATH=/chemin/vers/ton/dossier
                    </code>
                  </div>
                )}

                {/* Sandbox dirs */}
                <div className="space-y-2">
                  <span className="text-xs text-text-muted uppercase tracking-wider">
                    {t("allowedDirs")}
                  </span>

                  {sandboxDirs.length === 0 && (
                    <p className="text-[11px] text-text-muted italic">
                      {t("noDirsConfigured")}
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
                          aria-label={t("delete")}
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>

                  {/* Add dir input — fond surface-2, radius arrondi */}
                  <div className="field-row">
                    <input
                      type="text"
                      value={sandboxInput}
                      onChange={(e) => setSandboxInput(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleAddSandboxDir()}
                      placeholder="~/Documents ou /Users/franck/Documents"
                      className="input mono"
                    />
                    <button
                      onClick={handleAddSandboxDir}
                      className="btn"
                      title={t("add")}
                    >
                      <Plus size={14} />
                    </button>
                  </div>

                  {/* Quick shortcuts — browsers can't pop a native folder
                      picker that returns an absolute path (security model
                      forbids it). Clicking a chip prefills the input with
                      the ~-prefixed equivalent; the daemon expands ~ at
                      runtime to the actual home directory. User can edit
                      then validate with + or Enter. */}
                  <div className="flex flex-wrap items-center gap-1.5 pt-1">
                    <span className="text-[10px] text-text-muted uppercase tracking-wider mr-1">
                      {t("dirShortcuts")}
                    </span>
                    {[
                      "~/Documents",
                      "~/Downloads",
                      "~/Desktop",
                      "~/Pictures",
                    ].map((shortcut) => (
                      <button
                        key={shortcut}
                        onClick={() => setSandboxInput(shortcut)}
                        className="text-[10px] px-2 py-0.5 rounded border border-border-dim text-text-muted hover:text-cyber-cyan hover:border-cyber-cyan/40 transition-colors mono"
                        title={t("dirShortcutTooltip", { path: shortcut })}
                      >
                        {shortcut}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Save button — width égal au bouton « Télécharger ely-config.json »
                    alignSelf:flex-start évite le stretch full-width imposé par .section-block (flex column). */}
                <button
                  onClick={handleSaveDesktopConfig}
                  disabled={savingDesktop}
                  className="btn primary"
                  style={{ minWidth: 280, justifyContent: "center", alignSelf: "flex-start" }}
                >
                  <Check size={14} />
                  {savingDesktop ? t("saving") : t("save")}
                </button>

                {/* Download config */}
                <div className="pt-3 space-y-2" style={{ borderTop: "1px solid var(--border-subtle)" }}>
                  <p className="tab-intro" style={{ marginBottom: 8 }}>
                    {t("desktopDownloadDesc")}
                  </p>
                  <button
                    onClick={handleDownloadConfig}
                    className="btn primary"
                    style={{ minWidth: 280, justifyContent: "center" }}
                  >
                    <Download size={14} />
                    {t("downloadConfig")}
                  </button>
                </div>

                {/* Binaries — fond surface-2, radius arrondi, border accent au hover */}
                {desktopBinaries.length > 0 && (
                  <div className="pt-3 space-y-2" style={{ borderTop: "1px solid var(--border-subtle)" }}>
                    <span className="text-xs text-text-muted uppercase tracking-wider">
                      {t("downloadDaemon")}
                    </span>
                    <div className="vstack" style={{ gap: 6 }}>
                      {desktopBinaries.map((b) => (
                        <a
                          key={b.filename}
                          href={b.url}
                          download={b.filename}
                          className="daemon-bin"
                        >
                          <Download size={14} className="daemon-bin-icon" />
                          <span className="mono daemon-bin-name">
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
                        {t("installInstructions")}
                      </summary>
                      <ol className="mt-2 space-y-1 pl-3 list-decimal">
                        <li>{t("installStep1")}</li>
                        <li>{t.rich("installStep2", { code: (chunks) => <code className="text-cyber-cyan">{chunks}</code> })}</li>
                        <li>{t("installStep3")}</li>
                        <li>
                          {t.rich("installStep4", { code: (chunks) => <code className="text-cyber-cyan">{chunks}</code> })}
                        </li>
                        <li>{t.rich("installStep5", { code: (chunks) => <code className="text-cyber-cyan">{chunks}</code> })}</li>
                        <li>{t("installStep6")}</li>
                      </ol>
                    </details>
                  </div>
                )}

              </div>
              </div>
            </section>
            )}

            {/* ----------------------------------------------------------------
                Browser Extension — in "integrations" tab
                Sprint 0.5: long-lived tokens replace the DevTools bidouille.
            ---------------------------------------------------------------- */}
            {activeTab === "integrations" && (
              <section style={{ marginTop: 16 }}>
                <div className="section-block">
                  <div className="section-block-head">
                    <h3>
                      <Plug size={16} /> Extension navigateur ELY
                    </h3>
                  </div>
                  <div className="vstack" style={{ gap: 12 }}>
                    <p className="text-xs text-text-muted">
                      L’extension Chrome permet à Ely d’agir directement dans
                      vos onglets (lire le DOM, cliquer, remplir des champs,
                      avec confirmation HITL avant chaque action destructive).
                      Pour la connecter sans avoir à copier un JWT depuis les
                      DevTools, générez un token longue durée.
                    </p>
                    <a
                      href="/settings/extension"
                      className="btn primary"
                      style={{ minWidth: 280, justifyContent: "center", alignSelf: "flex-start" }}
                    >
                      <KeyRound size={14} />
                      Gérer les tokens d’extension
                    </a>
                  </div>
                </div>

                <div className="section-block" style={{ marginTop: 16 }}>
                  <div className="section-block-head">
                    <h3>
                      <KeyRound size={16} /> Clés API / serveur MCP
                    </h3>
                  </div>
                  <div className="vstack" style={{ gap: 12 }}>
                    <p className="text-xs text-text-muted">
                      Exposez Ely comme serveur MCP : connectez Claude Desktop ou
                      tout autre client MCP à votre instance pour discuter avec
                      Ely, piloter ses tâches planifiées et fouiller sa mémoire.
                      L’authentification se fait via une clé API personnelle
                      longue durée.
                    </p>
                    <a
                      href="/settings/api-keys"
                      className="btn primary"
                      style={{ minWidth: 280, justifyContent: "center", alignSelf: "flex-start" }}
                    >
                      <KeyRound size={14} />
                      Gérer les clés API
                    </a>
                  </div>
                </div>
              </section>
            )}

            {/* ----------------------------------------------------------------
                Mon compte — changement de mot de passe
            ---------------------------------------------------------------- */}
            {activeTab === "compte" && (() => {
              const strength = newPwd ? checkPasswordStrength(newPwd) : null;
              const mismatch = confirmPwd && newPwd !== confirmPwd;

              return (
                <section>
                  <div className="flex items-center gap-2 mb-4">
                    <Lock className="w-4 h-4 text-cyber-cyan" />
                    <h2 className="text-sm font-medium text-text-primary">{t("myAccount")}</h2>
                  </div>

                  <div className="section-block">
                    <p className="text-xs text-text-muted">
                      {t("accountIntro")}
                    </p>

                    {/* Mot de passe actuel */}
                    <div className="space-y-1">
                      <label className="text-xs text-text-secondary">{t("currentPassword")}</label>
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
                      <label className="text-xs text-text-secondary">{t("newPassword")}</label>
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
                              {t(strength.labelKey as never)}
                            </span>
                          </div>
                          {strength.hintKeys.length > 0 && (
                            <ul className="space-y-0.5">
                              {strength.hintKeys.map((h) => (
                                <li key={h} className="text-[10px] text-text-muted flex items-center gap-1">
                                  <XCircle className="w-3 h-3 text-red-400 shrink-0" />
                                  {t(h as never)}
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Confirmation */}
                    <div className="space-y-1">
                      <label className="text-xs text-text-secondary">{t("confirmNewPassword")}</label>
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
                          <XCircle className="w-3 h-3" /> {t("pwdMismatchInline")}
                        </p>
                      )}
                    </div>

                    <button
                      onClick={handleChangePassword}
                      disabled={savingPwd || !currentPwd || !newPwd || !confirmPwd}
                      className="btn primary"
                      style={{ width: "100%", justifyContent: "center" }}
                    >
                      {savingPwd ? t("pwdChanging") : t("changePassword")}
                    </button>
                  </div>

                  {/* ── Onboarding personnalisé ── */}
                  <div className="mt-6 section-block">
                    <div className="flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-cyber-cyan" />
                      <h3 className="text-sm font-medium text-text-primary">Onboarding personnalisé</h3>
                    </div>
                    <p className="text-xs text-text-muted">
                      Refais le tour des questions pour qu'Éli apprenne (ou réapprenne) ton vocabulaire,
                      tes catégories Gmail, tes habitudes. Tes réponses précédentes sont conservées —
                      cette action ne fait que rouvrir le flux dans la page <code>/chat</code>.
                    </p>
                    <button
                      onClick={async () => {
                        try {
                          await api.restartOnboarding();
                          window.location.href = "/chat";
                        } catch (e) {
                          console.error("Restart onboarding failed:", e);
                        }
                      }}
                      className="btn primary"
                      style={{ width: "100%", justifyContent: "center" }}
                    >
                      Refaire l'onboarding
                    </button>
                  </div>
                </section>
              );
            })()}

          </div>{/* max-w-3xl */}
          </div>{/* overflow-y-auto tab content */}
          </main>
        </div>
        </div>
      </div>

      {/* ================================================================
          Modal — Ajouter une instance LLM
      ================================================================ */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-bg-secondary border border-border-dim rounded-xl shadow-2xl w-full max-w-md mx-4 p-6 space-y-5">
            {/* Modal header */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Cpu className="w-4 h-4 text-cyber-cyan" />
                <h3 className="text-sm font-medium text-text-primary">
                  {editingInstanceId ? t("editModel") : t("addModel")}
                </h3>
              </div>
              <button
                onClick={closeModal}
                className="text-text-muted hover:text-text-secondary transition-colors"
              >
                <XCircle className="w-4 h-4" />
              </button>
            </div>

            {/* Step 1: Provider — locked in edit mode (PATCH backend
                doesn't accept provider changes) */}
            <div className="space-y-2">
              <label className="text-xs text-text-muted uppercase tracking-wider">{t("providerLabel")}</label>
              <div className="grid grid-cols-2 gap-2">
                {PROVIDERS.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => !editingInstanceId && setModalProvider(p.id)}
                    disabled={!!editingInstanceId}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-xs transition-all ${
                      modalProvider === p.id
                        ? "bg-cyber-cyan/5 border-cyber-cyan/30 text-text-primary"
                        : "bg-bg-primary border-border-dim text-text-muted hover:border-text-muted"
                    } ${editingInstanceId ? "opacity-50 cursor-not-allowed" : ""}`}
                  >
                    <span className="text-sm">{p.flag}</span>
                    <span className="truncate">{p.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Step 2: Model */}
            <div className="space-y-2">
              <label className="text-xs text-text-muted uppercase tracking-wider">{t("modelLabel")}</label>
              {modalProvider === "ollama" ? (
                modalOllamaModels.length > 0 ? (
                  <select
                    value={modalModel}
                    onChange={(e) => setModalModel(e.target.value)}
                    className="w-full text-xs bg-bg-primary border border-border-dim rounded px-3 py-2 text-text-primary focus:outline-none focus:border-cyber-cyan/40"
                  >
                    {modalOllamaModels.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                ) : (
                  <div className="space-y-2">
                    <input
                      type="text"
                      value={modalModel}
                      onChange={(e) => setModalModel(e.target.value)}
                      placeholder={t("ollamaModelPlaceholder")}
                      className="input"
                    />
                    <p className="text-[10px] text-text-muted">{t("ollamaUnreachable")}</p>
                  </div>
                )
              ) : (
                <input
                  type="text"
                  value={modalModel}
                  onChange={(e) => setModalModel(e.target.value)}
                  placeholder={selectedModalProvider?.defaultModel ?? t("modelNamePlaceholder")}
                  className="input"
                />
              )}
            </div>

            {/* Step 3 bis: openai_codex n'a PAS de clé — connexion par la
                carte « Abonnement ChatGPT » de l'onglet Modèles */}
            {modalProvider === "openai_codex" && (
              <p className={`text-[10px] ${codexConnected ? "text-text-muted" : "text-cyber-yellow"}`}>
                {codexConnected ? t("codexModalHintConnected") : t("codexModalHintNotConnected")}
              </p>
            )}

            {/* Step 3: API Key (cloud providers only) */}
            {selectedModalProvider?.needsKey && (
              <div className="space-y-2">
                <label className="text-xs text-text-muted uppercase tracking-wider">{t("apiKey")}</label>
                <input
                  type="password"
                  value={modalApiKey}
                  onChange={(e) => setModalApiKey(e.target.value)}
                  placeholder={editingInstanceId ? t("apiKeyEditPlaceholder") : "sk-••••••••"}
                  autoComplete="new-password"
                  className="input"
                />
                <p className="text-[10px] text-text-muted">
                  {editingInstanceId ? t("apiKeyEditHint") : t("apiKeyOptional")}
                </p>
              </div>
            )}

            {/* Step 3 ter: fenêtre et tarifs, portés par l'instance (#272).
                Avant, ces valeurs vivaient dans des tables du code : ajouter un
                modèle ici ne les mettait pas à jour, Ely tronquait à 8 192
                tokens et facturait un tarif générique inventé, en silence. */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <label className="text-xs text-text-muted uppercase tracking-wider">
                  Fenêtre de contexte
                </label>
                <input
                  type="number"
                  min={0}
                  value={modalCtxWindow}
                  onChange={(e) => setModalCtxWindow(e.target.value)}
                  placeholder="ex. 1000000"
                  className="input"
                />
                <p className="text-[10px] text-text-muted">
                  En tokens. Vide = valeur par défaut du code, puis 8 192.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-xs text-text-muted uppercase tracking-wider">
                  Tokens max en sortie
                </label>
                <input
                  type="number"
                  min={0}
                  value={modalMaxOut}
                  onChange={(e) => setModalMaxOut(e.target.value)}
                  placeholder="ex. 65536"
                  className="input"
                />
                <p className="text-[10px] text-text-muted">
                  Vide = 4 096, et les réponses longues sont coupées en
                  silence. Sur un modèle local, cette valeur est prélevée sur
                  la fenêtre.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-xs text-text-muted uppercase tracking-wider">
                  Tarif entrée (USD / M)
                </label>
                <input
                  type="number"
                  min={0}
                  step="0.001"
                  value={modalInPrice}
                  onChange={(e) => setModalInPrice(e.target.value)}
                  placeholder="ex. 0.30"
                  className="input"
                />
                <p className="text-[10px] text-text-muted">
                  En dollars, tel que publié. La conversion en euros est un
                  réglage d&apos;affichage.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-xs text-text-muted uppercase tracking-wider">
                  Tarif sortie (USD / M)
                </label>
                <input
                  type="number"
                  min={0}
                  step="0.001"
                  value={modalOutPrice}
                  onChange={(e) => setModalOutPrice(e.target.value)}
                  placeholder="ex. 2.50"
                  className="input"
                />
                <p className="text-[10px] text-text-muted">
                  0 pour un modèle local ou consommé au forfait.
                </p>
              </div>
            </div>

            {/* Step 4: Label */}
            <div className="space-y-2">
              <label className="text-xs text-text-muted uppercase tracking-wider">{t("nameLabel")}</label>
              <input
                type="text"
                value={modalLabel}
                onChange={(e) => setModalLabel(e.target.value)}
                placeholder={t("namePlaceholder")}
                className="input"
              />
            </div>

            {/* Actions */}
            <div className="flex items-center gap-3 pt-2">
              <button
                onClick={closeModal}
                className="flex-1 text-xs py-2 rounded border border-border-dim text-text-muted hover:text-text-secondary transition-all"
              >
                {tc("cancel")}
              </button>
              <button
                onClick={handleSubmitInstance}
                disabled={modalSaving || !modalLabel.trim() || !modalModel.trim()}
                className="flex-1 text-xs py-2 rounded border border-cyber-cyan/30 bg-cyber-cyan/10 text-cyber-cyan hover:bg-cyber-cyan/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {modalSaving
                  ? (editingInstanceId ? t("savingInstance") : t("creatingInstance"))
                  : (editingInstanceId ? t("saveInstance") : t("createInstance"))}
              </button>
            </div>
          </div>
        </div>
      )}

    </AuthGuard>
  );
}
