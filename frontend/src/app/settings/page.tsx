"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/settings/page.tsx
 * @brief      Settings page — user preferences and configuration
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    PolyForm Strict License 1.0.0
 *             https://polyformproject.org/licenses/strict/1.0.0/
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
 *   - INTERDIT : Toute utilisation commerciale sans accord préalable.
 *   - INTERDIT : Redistribution de versions modifiées de ce code.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { GoogleAccountsSection } from "@/components/settings/GoogleAccountsSection";
import {
  Cpu, Key, Server, ShieldCheck, Mail, Calendar, HardDrive,
  CheckCircle, XCircle, ExternalLink, Check, AlertCircle, Languages,
  Monitor, Download, Plus, Trash2, Wifi, WifiOff, Lock, Eye, EyeOff,
  GitBranch, ChevronUp, ChevronDown, Info, ToggleLeft, ToggleRight, User,
  Plug,
} from "lucide-react";
import { authFetch, isAdmin } from "@/lib/auth";
import { useTranslations } from "next-intl";
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
    { labelKey: "pwdStrengthStrong",        color: "text-emerald-400",barColor: "bg-emerald-500" },
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
  // admin is read client-side only (localStorage unavailable during SSR)
  const [admin, setAdmin] = useState(false);

  // LLM Instances state
  const [instances, setInstances]   = useState<LLMInstance[]>([]);
  const [instancesLoading, setInstancesLoading] = useState(false);

  // Add instance modal state
  const [showAddModal, setShowAddModal]       = useState(false);
  const [modalProvider, setModalProvider]     = useState("ollama");
  const [modalModel, setModalModel]           = useState("");
  const [modalLabel, setModalLabel]           = useState("");
  const [modalApiKey, setModalApiKey]         = useState("");
  const [modalOllamaModels, setModalOllamaModels] = useState<string[]>([]);
  const [modalSaving, setModalSaving]         = useState(false);

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

  // Tier routing state
  const [tierMeta, setTierMeta]           = useState<TierMeta[]>([]);
  const [tierConfig, setTierConfig]       = useState<TierConfig>({});
  const [tierProviderIds, setTierProviderIds] = useState<string[]>([]);
  const [tierInstances, setTierInstances] = useState<Array<{id: string; label: string; provider: string; model: string; has_key: boolean}>>([]);
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

  // Active tab — initialised on mount once we know the role
  const [activeTab, setActiveTab] = useState<string>("integrations");

  // Toasts — extracted early so all callbacks below can capture `push`
  // from the lexical scope. Moving this up was a defensive cleanup
  // (the original placement at the bottom worked thanks to JS closure
  // laziness, but a code reviewer flagged it as TDZ-fragile).
  const { toasts, push } = useToasts();

  // ── WhatsApp Web session state (QR-pairing adapter) ───────────────────
  const [waWebStatus, setWaWebStatus] = useState<{
    status: string;
    qr_png_b64?: string | null;
    phone?: string | null;
    last_error?: string | null;
  }>({ status: "not_started" });
  const [waWebLoading, setWaWebLoading] = useState(false);
  const waWebPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch current WhatsApp Web status (on mount + when user lands on integrations)
  const refreshWaWebStatus = useCallback(async () => {
    try {
      const res = await authFetch(`${API_URL}/api/whatsapp-web/session/status`);
      if (res.ok) setWaWebStatus(await res.json());
    } catch {/* silent */}
  }, []);

  // Start a new session (or resume) — usually triggers QR generation
  const handleWaWebStart = useCallback(async () => {
    setWaWebLoading(true);
    try {
      const res = await authFetch(`${API_URL}/api/whatsapp-web/session/start`, { method: "POST" });
      if (res.ok) {
        setWaWebStatus(await res.json());
        // Poll status every 2s while pending_qr (to detect when user scans)
        if (waWebPollRef.current) clearInterval(waWebPollRef.current);
        waWebPollRef.current = setInterval(refreshWaWebStatus, 2000);
      } else {
        push("error", t("waStartFailed"));
      }
    } catch {
      push("error", t("waNetworkError"));
    } finally {
      setWaWebLoading(false);
    }
  }, [refreshWaWebStatus, t, push]);

  // Alternative pairing: phone number → 8-char code (when QR scan fails)
  const [waPhoneInput, setWaPhoneInput] = useState("");
  const [waPairCode, setWaPairCode] = useState<string | null>(null);
  const handleWaWebPairPhone = useCallback(async () => {
    const phone = waPhoneInput.trim();
    if (!phone) {
      push("error", t("waEnterPhone"));
      return;
    }
    setWaWebLoading(true);
    setWaPairCode(null);
    try {
      const res = await authFetch(`${API_URL}/api/whatsapp-web/session/pair-phone`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone_number: phone }),
      });
      const data = await res.json();
      if (res.ok && data.code) {
        setWaPairCode(data.code);
        push("success", t("waCodeGenerated", { code: data.code }));
        // Start polling in case we weren't already
        if (waWebPollRef.current) clearInterval(waWebPollRef.current);
        waWebPollRef.current = setInterval(refreshWaWebStatus, 2000);
      } else {
        push("error", data.error || t("waCodeFailed"));
      }
    } catch {
      push("error", t("networkError"));
    } finally {
      setWaWebLoading(false);
    }
  }, [waPhoneInput, refreshWaWebStatus, t, push]);

  // Log out / unlink — wipes the local session
  const handleWaWebLogout = useCallback(async () => {
    if (!confirm(t("waLogoutConfirm"))) return;
    setWaWebLoading(true);
    try {
      const res = await authFetch(`${API_URL}/api/whatsapp-web/session/logout`, { method: "POST" });
      if (res.ok) {
        setWaWebStatus({ status: "not_started" });
        if (waWebPollRef.current) clearInterval(waWebPollRef.current);
        push("success", t("waDisconnected"));
      }
    } finally {
      setWaWebLoading(false);
    }
  }, [t, push]);

  // Stop polling when paired, clean up on unmount
  useEffect(() => {
    if (waWebStatus.status === "linked" && waWebPollRef.current) {
      clearInterval(waWebPollRef.current);
      waWebPollRef.current = null;
    }
    return () => {
      if (waWebPollRef.current) clearInterval(waWebPollRef.current);
    };
  }, [waWebStatus.status]);

  // Auto-refresh status when user switches to integrations or channels tab
  useEffect(() => {
    if (activeTab === "integrations" || activeTab === "channels") {
      refreshWaWebStatus();
    }
  }, [activeTab, refreshWaWebStatus]);

  // ── Telegram / Discord / Slack channel config state ─────────────────────
  // Each channel keeps its own status (configured? bot alive?) + form inputs.
  const [tgStatus, setTgStatus] = useState<{ configured: boolean; bot_username?: string | null; running: boolean }>({ configured: false, running: false });
  const [tgToken, setTgToken] = useState("");
  const [tgBusy, setTgBusy] = useState(false);

  const [dcStatus, setDcStatus] = useState<{ configured: boolean; running: boolean }>({ configured: false, running: false });
  const [dcToken, setDcToken] = useState("");
  const [dcBusy, setDcBusy] = useState(false);

  const [slStatus, setSlStatus] = useState<{ configured: boolean; has_bot_token: boolean; has_app_token: boolean }>({ configured: false, has_bot_token: false, has_app_token: false });
  const [slBotToken, setSlBotToken] = useState("");
  const [slAppToken, setSlAppToken] = useState("");
  const [slBusy, setSlBusy] = useState(false);

  const refreshChannelsStatus = useCallback(async () => {
    try {
      const [tg, dc, sl] = await Promise.all([
        authFetch(`${API_URL}/api/channels/telegram/status`).then((r) => r.ok ? r.json() : null).catch(() => null),
        authFetch(`${API_URL}/api/channels/discord/status`).then((r) => r.ok ? r.json() : null).catch(() => null),
        authFetch(`${API_URL}/api/channels/slack/status`).then((r) => r.ok ? r.json() : null).catch(() => null),
      ]);
      if (tg) setTgStatus(tg);
      if (dc) setDcStatus(dc);
      if (sl) setSlStatus(sl);
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

  const handleDcSave = useCallback(async () => {
    const token = dcToken.trim();
    if (!token) { push("error", t("dcPasteToken")); return; }
    setDcBusy(true);
    try {
      const res = await authFetch(`${API_URL}/api/channels/discord/save`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const data = await res.json();
      if (res.ok && data.saved) {
        push("success", t("dcConfigured", { username: data.bot_username ?? "OK" }));
        setDcToken("");
        await refreshChannelsStatus();
      } else {
        push("error", data.detail || t("invalidToken"));
      }
    } catch { push("error", t("dcNetworkError")); }
    finally { setDcBusy(false); }
  }, [dcToken, refreshChannelsStatus, t, push]);

  const handleDcDisable = useCallback(async () => {
    if (!confirm(t("dcDisableConfirm"))) return;
    setDcBusy(true);
    try {
      await authFetch(`${API_URL}/api/channels/discord/disable`, { method: "POST" });
      push("success", t("dcDisabled"));
      await refreshChannelsStatus();
    } finally { setDcBusy(false); }
  }, [refreshChannelsStatus, t, push]);

  const handleSlSave = useCallback(async () => {
    const bot = slBotToken.trim();
    const app = slAppToken.trim();
    if (!bot || !app) { push("error", t("slTokensRequired")); return; }
    setSlBusy(true);
    try {
      const res = await authFetch(`${API_URL}/api/channels/slack/save`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bot_token: bot, app_token: app }),
      });
      const data = await res.json();
      if (res.ok && data.saved) {
        push("success", t("slConfigured"));
        setSlBotToken(""); setSlAppToken("");
        await refreshChannelsStatus();
      } else {
        push("error", data.detail || t("invalidTokens"));
      }
    } catch { push("error", t("slNetworkError")); }
    finally { setSlBusy(false); }
  }, [slBotToken, slAppToken, refreshChannelsStatus, t, push]);

  const handleSlDisable = useCallback(async () => {
    if (!confirm(t("slDisableConfirm"))) return;
    setSlBusy(true);
    try {
      await authFetch(`${API_URL}/api/channels/slack/disable`, { method: "POST" });
      push("success", t("slDisabled"));
      await refreshChannelsStatus();
    } finally { setSlBusy(false); }
  }, [refreshChannelsStatus, t, push]);

  // Initialise admin role and default tab once mounted (client-side only)
  useEffect(() => {
    const a = isAdmin();
    setAdmin(a);
    setActiveTab(a ? "modeles" : "integrations");
  }, []);

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
    setModalProvider("ollama");
    setModalModel("");
    setModalLabel("");
    setModalApiKey("");
    setShowAddModal(true);
  };

  const handleCreateInstance = async () => {
    if (modalSaving || !modalLabel.trim() || !modalModel.trim()) return;
    setModalSaving(true);
    try {
      const body: { label: string; provider: string; model: string; api_key?: string } = {
        label: modalLabel.trim(),
        provider: modalProvider,
        model: modalModel.trim(),
      };
      if (modalApiKey.trim()) body.api_key = modalApiKey.trim();

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
      setShowAddModal(false);
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
    { id: "integrations", label: t("tabIntegrations"),  icon: Plug       },
    { id: "channels",     label: t("tabChannels"),       icon: Mail       },
    { id: "compte",       label: t("tabAccount"),        icon: User       },
  ];

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Header />

          {/* Toast stack */}
          <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 pointer-events-none">
            {toasts.map((toast) => (
              <div
                key={toast.id}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-lg border text-xs shadow-lg pointer-events-auto transition-all ${
                  toast.kind === "success"
                    ? "bg-emerald-900/80 border-emerald-500/30 text-emerald-300"
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
          <div className="shrink-0 border-b border-border-dim px-6">
            <nav className="flex gap-1">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setActiveTab(id)}
                  className={`flex items-center gap-2 px-4 py-3 text-xs font-medium border-b-2 transition-all -mb-px ${
                    activeTab === id
                      ? "border-cyber-cyan text-cyber-cyan"
                      : "border-transparent text-text-muted hover:text-text-secondary hover:border-border-dim"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {label}
                </button>
              ))}
            </nav>
          </div>

          {/* ── Tab content ───────────────────────────────────────────── */}
          <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-3xl space-y-6">

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
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 transition-all"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    {t("add")}
                  </button>
                </div>

                <p className="text-[11px] text-text-muted mb-3">
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
                                  <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shrink-0">
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
                          <button
                            onClick={() => handleDeleteInstance(inst.id)}
                            className="shrink-0 text-text-muted hover:text-cyber-red transition-colors"
                            title={t("delete")}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
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
                    className="text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10 transition-all disabled:opacity-50"
                  >
                    {savingTiers ? "…" : t("save")}
                  </button>
                </div>

                <p className="text-[11px] text-text-muted mb-3">
                  {t("routingDescription")}
                </p>

                {routingItems.length === 0 && (
                  <div className="mb-3 p-3 bg-amber-500/5 border border-amber-500/20 rounded-lg">
                    <p className="text-[11px] text-amber-400">
                      {t("routingNoInstances")}
                    </p>
                  </div>
                )}

                <div className="space-y-3">
                  {tierMeta.map((tier) => {
                    const entry: TierEntry = tierConfig[tier.id] ?? { providers: [], fallback_enabled: true };
                    const badgeCls = TIER_BADGE_COLORS[tier.color] ?? TIER_BADGE_COLORS.slate;
                    const availableToAdd = routingItems.filter((ri) => !entry.providers.includes(ri.id));

                    return (
                      <div key={tier.id} className="bg-bg-secondary border border-border-dim rounded-lg p-4">
                        {/* Header */}
                        <div className="flex items-start justify-between gap-2 mb-3">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border shrink-0 ${badgeCls}`}>
                              {tier.badge}
                            </span>
                            <span className="text-xs font-medium text-text-primary">{t.has(`tierLabels.${tier.id}`) ? t(`tierLabels.${tier.id}`) : tier.label}</span>
                            <button
                              onClick={() => setTierTooltip(tierTooltip === tier.id ? null : tier.id)}
                              className="text-text-muted hover:text-text-secondary transition-colors shrink-0"
                              title={t("explanation")}
                            >
                              <Info className="w-3 h-3" />
                            </button>
                          </div>
                          {/* Fallback toggle */}
                          <button
                            onClick={() => toggleTierFallback(tier.id)}
                            className="flex items-center gap-1.5 text-[10px] shrink-0 transition-colors"
                            title={entry.fallback_enabled ? t("disableFallback") : t("enableFallback")}
                          >
                            {entry.fallback_enabled
                              ? <ToggleRight className="w-4 h-4 text-cyber-cyan" />
                              : <ToggleLeft className="w-4 h-4 text-text-muted" />}
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
                        <div className="space-y-1.5">
                          {entry.providers.length === 0 && (
                            <p className="text-[11px] text-text-muted italic">{t("noTierModels")}</p>
                          )}
                          {entry.providers.map((provId, idx) => {
                            const item = resolveRoutingItem(provId);
                            return (
                              <div key={provId} className="flex items-center gap-2">
                                {/* Priority number */}
                                <span className="text-[9px] text-text-muted w-4 text-right shrink-0">{idx + 1}.</span>
                                {/* Item pill */}
                                <div className="flex-1 flex items-center gap-2 bg-bg-primary border border-border-dim rounded px-2 py-1 text-xs text-text-primary">
                                  <span className="text-base leading-none">{item.flag}</span>
                                  <span className="truncate">{item.label}</span>
                                  {item.isInstance && (
                                    <span className="ml-auto text-[8px] px-1 py-0.5 rounded bg-cyber-cyan/10 border border-cyber-cyan/20 text-cyber-cyan shrink-0">
                                      {t("instanceBadge")}
                                    </span>
                                  )}
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
            {activeTab === "integrations" && (
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
                  {GOOGLE_SERVICES.map(({ id, label, icon: Icon, scopeKey }) => (
                    <div key={id} className="flex items-center gap-3">
                      <div className={`w-7 h-7 rounded flex items-center justify-center shrink-0 ${
                        googleConnected ? "bg-emerald-500/10 border border-emerald-500/20" : "bg-bg-primary border border-border-dim"
                      }`}>
                        <Icon className={`w-3.5 h-3.5 ${googleConnected ? "text-emerald-400" : "text-text-muted"}`} />
                      </div>
                      <div>
                        <div className="text-xs font-medium text-text-primary">{label}</div>
                        <div className="text-[11px] text-text-muted">{t(scopeKey as never)}</div>
                      </div>
                    </div>
                  ))}
                </div>

                <p className="text-[11px] text-text-muted flex items-start gap-1.5 pt-2 border-t border-border-dim">
                  <ShieldCheck className="w-3 h-3 shrink-0 mt-0.5 text-emerald-400" />
                  {t("googlePrivacyNote")}
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

                {/* Multi-account section — Phase 3 of multi-Google.
                    Lists every linked GoogleAccount (alias/email/default badge),
                    lets the user add more, rename, set-default, remove. */}
                {googleConnected && (
                  <div className="pt-3 border-t border-border-dim">
                    <GoogleAccountsSection />
                  </div>
                )}

                <details className="text-[11px] text-text-muted">
                  <summary className="cursor-pointer hover:text-text-secondary">{t("howToConfigure")}</summary>
                  <ol className="mt-2 space-y-1 pl-3 list-decimal">
                    <li>{t.rich("googleStep1", { link: (chunks) => <a href="https://console.cloud.google.com/" target="_blank" rel="noopener noreferrer" className="text-cyber-cyan hover:underline">{chunks}</a> })}</li>
                    <li>{t("googleStep2")}</li>
                    <li>{t("googleStep3")}</li>
                    <li>{t.rich("googleStep4", { code: (chunks) => <code className="text-cyber-cyan">{chunks}</code> })}</li>
                    <li>{t.rich("googleStep5", { link: (chunks) => <a href="/admin" className="text-cyber-cyan hover:underline">{chunks}</a> })}</li>
                    <li>{t("googleStep6")}</li>
                  </ol>
                </details>
              </div>

            </section>
            )}

            {/* ================================================================
                TAB: Channels — WhatsApp / Telegram / Discord / Slack
                Each card: status badge · help toggle · form · action buttons
            ================================================================ */}
            {activeTab === "channels" && (
            <section className="space-y-8">
              <div>
                <h2 className="text-sm font-medium text-text-primary mb-1">{t("channelsTitle")}</h2>
                <p className="text-[11px] text-text-muted">
                  {t("channelsIntro")}
                </p>
              </div>

              {/* ── WhatsApp Web ───────────────────────────────────────── */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-4 h-4 text-emerald-400 font-bold text-sm">W</div>
                  <h3 className="text-sm font-medium text-text-primary">WhatsApp</h3>
                  {waWebStatus.status === "linked" && (
                    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                      <CheckCircle className="w-2.5 h-2.5" /> {waWebStatus.phone ? t("waLinkedPhone", { phone: waWebStatus.phone }) : t("waLinked")}
                    </span>
                  )}
                  {waWebStatus.status === "pending_qr" && (
                    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400">
                      {t("waWaitingScan")}
                    </span>
                  )}
                  {waWebStatus.status === "error" && (
                    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-red-500/10 border border-red-500/20 text-red-400">
                      <XCircle className="w-2.5 h-2.5" /> {t("waErrorBadge")}
                    </span>
                  )}
                </div>

                <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
                  <p className="text-[11px] text-text-muted">
                    {t.rich("waIntro", { strong: (chunks) => <strong>{chunks}</strong> })}
                  </p>

                  {/* Pending QR — big so iPhone cameras decode reliably */}
                  {waWebStatus.status === "pending_qr" && waWebStatus.qr_png_b64 && (
                    <div className="flex flex-col items-center gap-3 py-2">
                      <img
                        src={`data:image/png;base64,${waWebStatus.qr_png_b64}`}
                        alt={t("waQrAlt")}
                        className="w-[420px] h-[420px] max-w-full rounded bg-white p-3 border border-border-dim"
                      />
                      <p className="text-[11px] text-text-muted text-center max-w-xs">
                        {t("waQrInstructions")}
                      </p>
                    </div>
                  )}

                  {waWebStatus.status === "error" && waWebStatus.last_error && (
                    <div className="text-[11px] text-red-400 bg-red-500/10 border border-red-500/20 rounded px-2 py-1.5">
                      {waWebStatus.last_error}
                    </div>
                  )}

                  <div className="flex gap-2 pt-1">
                    {waWebStatus.status === "linked" ? (
                      <button
                        onClick={handleWaWebLogout}
                        disabled={waWebLoading}
                        className="text-xs px-3 py-1.5 rounded border border-cyber-red/30 text-cyber-red hover:bg-cyber-red/5 transition-all disabled:opacity-50"
                      >
                        {waWebLoading ? "..." : t("waDisconnect")}
                      </button>
                    ) : (
                      <button
                        onClick={handleWaWebStart}
                        disabled={waWebLoading || waWebStatus.status === "pending_qr"}
                        className="text-xs px-3 py-1.5 rounded border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/5 transition-all disabled:opacity-50"
                      >
                        {waWebLoading ? "..." : waWebStatus.status === "pending_qr" ? t("waScanInProgress") : t("waLinkMy")}
                      </button>
                    )}
                  </div>

                  {/* Alternative: pair by phone code */}
                  {waWebStatus.status !== "linked" && waWebStatus.status !== "not_started" && (
                    <details className="pt-2 border-t border-border-dim">
                      <summary className="text-[11px] text-text-muted cursor-pointer hover:text-text-secondary">
                        {t("waQrFailedTitle")}
                      </summary>
                      <div className="mt-3 space-y-2">
                        <p className="text-[11px] text-text-muted">
                          {t.rich("waPhoneIntro", {
                            code: (chunks) => <code className="text-cyber-cyan">{chunks}</code>,
                            strong: (chunks) => <strong>{chunks}</strong>,
                          })}
                        </p>
                        <div className="flex gap-2">
                          <input
                            type="tel"
                            value={waPhoneInput}
                            onChange={(e) => setWaPhoneInput(e.target.value)}
                            placeholder="33612345678"
                            className="flex-1 text-xs bg-bg-primary border border-border-dim rounded px-3 py-1.5 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-emerald-500/40"
                          />
                          <button
                            onClick={handleWaWebPairPhone}
                            disabled={waWebLoading || !waPhoneInput.trim()}
                            className="text-xs px-3 py-1.5 rounded border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/5 transition-all disabled:opacity-50 whitespace-nowrap"
                          >
                            {waWebLoading ? "..." : t("waGetCode")}
                          </button>
                        </div>
                        {waPairCode && (
                          <div className="text-center py-3 bg-emerald-500/5 border border-emerald-500/20 rounded">
                            <div className="text-[10px] uppercase tracking-wider text-emerald-400/70 mb-1">{t("waCodeLabel")}</div>
                            <div className="text-2xl font-mono font-bold text-emerald-300 tracking-widest">{waPairCode}</div>
                            <div className="text-[10px] text-text-muted mt-1">{t("waCodeValidity")}</div>
                          </div>
                        )}
                      </div>
                    </details>
                  )}

                  <details className="pt-2 border-t border-border-dim text-[11px] text-text-muted">
                    <summary className="cursor-pointer hover:text-text-secondary">{t("waHowItWorks")}</summary>
                    <ol className="mt-2 space-y-1 pl-3 list-decimal">
                      <li>{t.rich("waStep1", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
                      <li>{t("waStep2")}</li>
                      <li>{t("waStep3")}</li>
                      <li>{t.rich("waStep4", { em: (chunks) => <em>{chunks}</em> })}</li>
                    </ol>
                  </details>

                  <p className="text-[10px] text-text-muted flex items-start gap-1.5 pt-2 border-t border-border-dim">
                    <ShieldCheck className="w-3 h-3 shrink-0 mt-0.5 text-amber-400" />
                    {t("waUnofficialNote")}
                  </p>
                </div>
              </div>

              {/* ── Telegram ──────────────────────────────────────────── */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-4 h-4 text-cyan-400 font-bold text-sm">T</div>
                  <h3 className="text-sm font-medium text-text-primary">Telegram</h3>
                  {tgStatus.configured && tgStatus.running && (
                    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                      <CheckCircle className="w-2.5 h-2.5" /> {tgStatus.bot_username ? t("activeNamed", { name: tgStatus.bot_username }) : t("active")}
                    </span>
                  )}
                  {tgStatus.configured && !tgStatus.running && (
                    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400">
                      {t("configuredButStopped")}
                    </span>
                  )}
                  {!tgStatus.configured && (
                    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-text-muted/10 border border-border-dim text-text-muted">
                      {t("notConfiguredBadge")}
                    </span>
                  )}
                </div>

                <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
                  <p className="text-[11px] text-text-muted">
                    {t.rich("tgIntro", {
                      strong: (chunks) => <strong>{chunks}</strong>,
                      code: (chunks) => <code className="text-cyber-cyan">{chunks}</code>,
                    })}
                  </p>

                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={tgToken}
                      onChange={(e) => setTgToken(e.target.value)}
                      placeholder={tgStatus.configured ? t("tgTokenPlaceholderConfigured") : t("tgTokenPlaceholder")}
                      className="flex-1 text-xs bg-bg-primary border border-border-dim rounded px-3 py-1.5 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyan-500/40 font-mono"
                    />
                    <button
                      onClick={handleTgSave}
                      disabled={tgBusy || !tgToken.trim()}
                      className="text-xs px-3 py-1.5 rounded border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/5 transition-all disabled:opacity-50 whitespace-nowrap"
                    >
                      {tgBusy ? "..." : tgStatus.configured ? t("update") : t("enable")}
                    </button>
                    {tgStatus.configured && (
                      <button
                        onClick={handleTgDisable}
                        disabled={tgBusy}
                        className="text-xs px-3 py-1.5 rounded border border-cyber-red/30 text-cyber-red hover:bg-cyber-red/5 transition-all disabled:opacity-50 whitespace-nowrap"
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

              {/* ── Discord ──────────────────────────────────────────── */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-4 h-4 text-indigo-400 font-bold text-sm">D</div>
                  <h3 className="text-sm font-medium text-text-primary">Discord</h3>
                  {dcStatus.configured && dcStatus.running && (
                    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                      <CheckCircle className="w-2.5 h-2.5" /> {t("active")}
                    </span>
                  )}
                  {dcStatus.configured && !dcStatus.running && (
                    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400">
                      {t("configuredButStopped")}
                    </span>
                  )}
                  {!dcStatus.configured && (
                    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-text-muted/10 border border-border-dim text-text-muted">
                      {t("notConfiguredBadge")}
                    </span>
                  )}
                </div>

                <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
                  <p className="text-[11px] text-text-muted">
                    {t.rich("dcIntro", {
                      strong: (chunks) => <strong>{chunks}</strong>,
                      em: (chunks) => <em>{chunks}</em>,
                      code: (chunks) => <code className="text-cyber-cyan">{chunks}</code>,
                    })}
                  </p>

                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={dcToken}
                      onChange={(e) => setDcToken(e.target.value)}
                      placeholder={dcStatus.configured ? t("dcTokenPlaceholderConfigured") : t("dcTokenPlaceholder")}
                      className="flex-1 text-xs bg-bg-primary border border-border-dim rounded px-3 py-1.5 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-indigo-500/40 font-mono"
                    />
                    <button
                      onClick={handleDcSave}
                      disabled={dcBusy || !dcToken.trim()}
                      className="text-xs px-3 py-1.5 rounded border border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/5 transition-all disabled:opacity-50 whitespace-nowrap"
                    >
                      {dcBusy ? "..." : dcStatus.configured ? t("update") : t("enable")}
                    </button>
                    {dcStatus.configured && (
                      <button
                        onClick={handleDcDisable}
                        disabled={dcBusy}
                        className="text-xs px-3 py-1.5 rounded border border-cyber-red/30 text-cyber-red hover:bg-cyber-red/5 transition-all disabled:opacity-50 whitespace-nowrap"
                      >
                        {t("disable")}
                      </button>
                    )}
                  </div>

                  <details className="pt-2 border-t border-border-dim text-[11px] text-text-muted">
                    <summary className="cursor-pointer hover:text-text-secondary">{t("howToConfigure")}</summary>
                    <ol className="mt-2 space-y-1 pl-3 list-decimal">
                      <li>{t.rich("dcHelpStep1", { link: (chunks) => <a href="https://discord.com/developers/applications" target="_blank" rel="noopener noreferrer" className="text-cyber-cyan hover:underline">{chunks}</a> })}</li>
                      <li>{t.rich("dcHelpStep2", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
                      <li>{t.rich("dcHelpStep3", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
                      <li>{t.rich("dcHelpStep4", { strong: (chunks) => <strong>{chunks}</strong>, em: (chunks) => <em>{chunks}</em> })}</li>
                      <li>{t.rich("dcHelpStep5", { strong: (chunks) => <strong>{chunks}</strong>, em: (chunks) => <em>{chunks}</em> })}</li>
                      <li>{t.rich("dcHelpStep6", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
                      <li>{t.rich("dcHelpStep7", { code: (chunks) => <code className="text-cyber-cyan">{chunks}</code> })}</li>
                    </ol>
                  </details>
                </div>
              </div>

              {/* ── Slack ────────────────────────────────────────────── */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-4 h-4 text-purple-400 font-bold text-sm">S</div>
                  <h3 className="text-sm font-medium text-text-primary">Slack</h3>
                  {slStatus.configured && (
                    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                      <CheckCircle className="w-2.5 h-2.5" /> {t("configuredBadge")}
                    </span>
                  )}
                  {!slStatus.configured && (
                    <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-text-muted/10 border border-border-dim text-text-muted">
                      {t("notConfiguredBadge")}
                    </span>
                  )}
                </div>

                <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
                  <p className="text-[11px] text-text-muted">
                    {t.rich("slIntro", {
                      strong: (chunks) => <strong>{chunks}</strong>,
                      code: (chunks) => <code className="text-cyber-cyan">{chunks}</code>,
                    })}
                  </p>

                  <input
                    type="password"
                    value={slBotToken}
                    onChange={(e) => setSlBotToken(e.target.value)}
                    placeholder={slStatus.has_bot_token ? t("slBotTokenPlaceholderConfigured") : t("slBotTokenPlaceholder")}
                    className="w-full text-xs bg-bg-primary border border-border-dim rounded px-3 py-1.5 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-purple-500/40 font-mono"
                  />
                  <input
                    type="password"
                    value={slAppToken}
                    onChange={(e) => setSlAppToken(e.target.value)}
                    placeholder={slStatus.has_app_token ? t("slAppTokenPlaceholderConfigured") : t("slAppTokenPlaceholder")}
                    className="w-full text-xs bg-bg-primary border border-border-dim rounded px-3 py-1.5 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-purple-500/40 font-mono"
                  />

                  <div className="flex gap-2">
                    <button
                      onClick={handleSlSave}
                      disabled={slBusy || !slBotToken.trim() || !slAppToken.trim()}
                      className="text-xs px-3 py-1.5 rounded border border-purple-500/30 text-purple-400 hover:bg-purple-500/5 transition-all disabled:opacity-50"
                    >
                      {slBusy ? "..." : slStatus.configured ? t("update") : t("enable")}
                    </button>
                    {slStatus.configured && (
                      <button
                        onClick={handleSlDisable}
                        disabled={slBusy}
                        className="text-xs px-3 py-1.5 rounded border border-cyber-red/30 text-cyber-red hover:bg-cyber-red/5 transition-all disabled:opacity-50"
                      >
                        {t("disable")}
                      </button>
                    )}
                  </div>

                  <details className="pt-2 border-t border-border-dim text-[11px] text-text-muted">
                    <summary className="cursor-pointer hover:text-text-secondary">{t("howToConfigure")}</summary>
                    <ol className="mt-2 space-y-1 pl-3 list-decimal">
                      <li>{t.rich("slHelpStep1", {
                        link: (chunks) => <a href="https://api.slack.com/apps" target="_blank" rel="noopener noreferrer" className="text-cyber-cyan hover:underline">{chunks}</a>,
                        strong: (chunks) => <strong>{chunks}</strong>,
                        em: (chunks) => <em>{chunks}</em>,
                      })}</li>
                      <li>{t.rich("slHelpStep2", { strong: (chunks) => <strong>{chunks}</strong>, code: (chunks) => <code>{chunks}</code> })}</li>
                      <li>{t.rich("slHelpStep3", { strong: (chunks) => <strong>{chunks}</strong>, code: (chunks) => <code>{chunks}</code> })}</li>
                      <li>{t.rich("slHelpStep4", { strong: (chunks) => <strong>{chunks}</strong>, code: (chunks) => <code>{chunks}</code> })}</li>
                      <li>{t.rich("slHelpStep5", { strong: (chunks) => <strong>{chunks}</strong>, code: (chunks) => <code>{chunks}</code> })}</li>
                      <li>{t.rich("slHelpStep6", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
                      <li>{t.rich("slHelpStep7", { code: (chunks) => <code className="text-cyber-cyan">{chunks}</code> })}</li>
                    </ol>
                  </details>
                </div>
              </div>
            </section>
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
            )}

            {/* ----------------------------------------------------------------
                SSH Hosts — in "integrations" tab, admin only
            ---------------------------------------------------------------- */}
            {activeTab === "integrations" && admin && (
              <section>
                <div className="flex items-center gap-2 mb-4">
                  <Server className="w-4 h-4 text-cyber-cyan" />
                  <h2 className="text-sm font-medium text-text-primary">{t("sshHosts")}</h2>
                </div>
                <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
                  <p className="text-xs text-text-muted">
                    {t.rich("sshConfigDesc", { code: (chunks) => <code className="text-cyber-cyan">{chunks}</code> })}
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
                ELY Desktop — in "integrations" tab
            ---------------------------------------------------------------- */}
            {activeTab === "integrations" && (<section>
              <div className="flex items-center gap-2 mb-4">
                <Monitor className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary">ELY Desktop</h2>
                {desktopConnected === true && (
                  <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                    <Wifi className="w-2.5 h-2.5" /> {t("connected")}
                    {desktopPlatform && ` · ${desktopPlatform}`}
                    {desktopVersion && ` v${desktopVersion}`}
                  </span>
                )}
                {desktopConnected === false && (
                  <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-text-muted/10 border border-border-dim text-text-muted">
                    <WifiOff className="w-2.5 h-2.5" /> {t("notConnected")}
                  </span>
                )}
              </div>

              <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4">

                {/* Description */}
                <p className="text-xs text-text-muted">
                  {t("desktopDescription")}
                </p>

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
                  {savingDesktop ? t("saving") : t("save")}
                </button>

                {/* Download config */}
                <div className="pt-3 border-t border-border-dim space-y-2">
                  <p className="text-[11px] text-text-muted">
                    {t("desktopDownloadDesc")}
                  </p>
                  <button
                    onClick={handleDownloadConfig}
                    className="inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all"
                  >
                    <Download className="w-3 h-3" />
                    {t("downloadConfig")}
                  </button>
                </div>

                {/* Binaries */}
                {desktopBinaries.length > 0 && (
                  <div className="pt-3 border-t border-border-dim space-y-2">
                    <span className="text-xs text-text-muted uppercase tracking-wider">
                      {t("downloadDaemon")}
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

                  <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4">
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
                      className="w-full py-2 rounded-md text-xs font-medium bg-cyber-cyan/10 border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      {savingPwd ? t("pwdChanging") : t("changePassword")}
                    </button>
                  </div>
                </section>
              );
            })()}

          </div>{/* max-w-3xl */}
          </div>{/* overflow-y-auto tab content */}
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
                <h3 className="text-sm font-medium text-text-primary">{t("addModel")}</h3>
              </div>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-text-muted hover:text-text-secondary transition-colors"
              >
                <XCircle className="w-4 h-4" />
              </button>
            </div>

            {/* Step 1: Provider */}
            <div className="space-y-2">
              <label className="text-xs text-text-muted uppercase tracking-wider">{t("providerLabel")}</label>
              <div className="grid grid-cols-2 gap-2">
                {PROVIDERS.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setModalProvider(p.id)}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-xs transition-all ${
                      modalProvider === p.id
                        ? "bg-cyber-cyan/5 border-cyber-cyan/30 text-text-primary"
                        : "bg-bg-primary border-border-dim text-text-muted hover:border-text-muted"
                    }`}
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
                      className="w-full text-xs bg-bg-primary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
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
                  className="w-full text-xs bg-bg-primary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
                />
              )}
            </div>

            {/* Step 3: API Key (cloud providers only) */}
            {selectedModalProvider?.needsKey && (
              <div className="space-y-2">
                <label className="text-xs text-text-muted uppercase tracking-wider">{t("apiKey")}</label>
                <input
                  type="password"
                  value={modalApiKey}
                  onChange={(e) => setModalApiKey(e.target.value)}
                  placeholder="sk-••••••••"
                  autoComplete="new-password"
                  className="w-full text-xs bg-bg-primary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
                />
                <p className="text-[10px] text-text-muted">
                  {t("apiKeyOptional")}
                </p>
              </div>
            )}

            {/* Step 4: Label */}
            <div className="space-y-2">
              <label className="text-xs text-text-muted uppercase tracking-wider">{t("nameLabel")}</label>
              <input
                type="text"
                value={modalLabel}
                onChange={(e) => setModalLabel(e.target.value)}
                placeholder={t("namePlaceholder")}
                className="w-full text-xs bg-bg-primary border border-border-dim rounded px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
              />
            </div>

            {/* Actions */}
            <div className="flex items-center gap-3 pt-2">
              <button
                onClick={() => setShowAddModal(false)}
                className="flex-1 text-xs py-2 rounded border border-border-dim text-text-muted hover:text-text-secondary transition-all"
              >
                {tc("cancel")}
              </button>
              <button
                onClick={handleCreateInstance}
                disabled={modalSaving || !modalLabel.trim() || !modalModel.trim()}
                className="flex-1 text-xs py-2 rounded border border-cyber-cyan/30 bg-cyber-cyan/10 text-cyber-cyan hover:bg-cyber-cyan/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {modalSaving ? t("creatingInstance") : t("createInstance")}
              </button>
            </div>
          </div>
        </div>
      )}

    </AuthGuard>
  );
}
