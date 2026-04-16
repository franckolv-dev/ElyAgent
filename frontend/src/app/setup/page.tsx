"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/setup/page.tsx
 * @brief      Setup page — first-run configuration wizard
 *
 * @author     Franck OLLIVIER <franck.olv@gmail.com>
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
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  CheckCircle,
  XCircle,
  ExternalLink,
  ChevronRight,
  ChevronLeft,
  Bot,
  Zap,
  Globe,
  MessageCircle,
  Rocket,
  Key,
  Loader2,
  AlertCircle,
  Check,
  Server,
} from "lucide-react";
import { isAuthenticated, authFetch } from "@/lib/auth";
import { CyberpunkAvatar } from "@/components/avatar/CyberpunkAvatar";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LLMProviderStatus {
  configured: boolean;
}

interface SetupStatus {
  google: { configured: boolean; connected: boolean };
  llm: {
    anthropic: LLMProviderStatus;
    mistral: LLMProviderStatus;
    gemini: LLMProviderStatus;
    deepseek: LLMProviderStatus;
    ollama: { available: boolean };
  };
  telegram: { configured: boolean };
  whatsapp: { configured: boolean };
  is_first_launch: boolean;
}

interface ProviderConfig {
  id: string;
  name: string;
  shortName: string;
  description: string;
  role: string;
  url: string;
  urlLabel: string;
  steps: string[];
  keyPlaceholder: string;
  color: string;
}

// ---------------------------------------------------------------------------
// Provider catalogue
// ---------------------------------------------------------------------------

const PROVIDERS: ProviderConfig[] = [
  {
    id: "anthropic",
    name: "Anthropic Claude",
    shortName: "Claude",
    description: "Tâches complexes, raisonnement avancé",
    role: "Cerveau complexe",
    url: "https://console.anthropic.com/settings/keys",
    urlLabel: "console.anthropic.com",
    steps: [
      "Créez un compte sur console.anthropic.com",
      "Allez dans Settings → API Keys",
      'Cliquez "Create Key"',
      "Copiez la clé (elle commence par sk-ant-...)",
    ],
    keyPlaceholder: "sk-ant-api03-...",
    color: "#c97d2f",
  },
  {
    id: "mistral",
    name: "Mistral AI",
    shortName: "Mistral",
    description: "Tâches moyennes, IA française RGPD",
    role: "Cerveau moyen",
    url: "https://console.mistral.ai/api-keys/",
    urlLabel: "console.mistral.ai",
    steps: [
      "Créez un compte sur console.mistral.ai",
      'Allez dans "API Keys"',
      'Cliquez "Create new key"',
      "Copiez la clé générée",
    ],
    keyPlaceholder: "...",
    color: "#ff6b35",
  },
  {
    id: "gemini",
    name: "Google Gemini",
    shortName: "Gemini",
    description: "Tâches complexes + images",
    role: "Vision & images",
    url: "https://aistudio.google.com/app/apikey",
    urlLabel: "aistudio.google.com",
    steps: [
      "Connectez-vous à aistudio.google.com",
      'Cliquez "Get API key"',
      'Puis "Create API key"',
      "Copiez la clé générée (commence par AIza...)",
    ],
    keyPlaceholder: "AIzaSy...",
    color: "#4285f4",
  },
  {
    id: "deepseek",
    name: "DeepSeek",
    shortName: "DeepSeek",
    description: "Très économique, bon rapport qualité/prix",
    role: "Option économique",
    url: "https://platform.deepseek.com/api_keys",
    urlLabel: "platform.deepseek.com",
    steps: [
      "Créez un compte sur platform.deepseek.com",
      'Allez dans "API Keys"',
      'Cliquez "Create new API key"',
      "Copiez la clé générée",
    ],
    keyPlaceholder: "sk-...",
    color: "#7c3aed",
  },
];

// ---------------------------------------------------------------------------
// Validation state per provider
// ---------------------------------------------------------------------------

type ValidationState = "idle" | "validating" | "valid" | "invalid" | "saving" | "saved";

interface ProviderState {
  key: string;
  validation: ValidationState;
  error: string | null;
  expanded: boolean;
  elyMode: boolean;
}

function makeInitialProviderState(): Record<string, ProviderState> {
  const out: Record<string, ProviderState> = {};
  for (const p of PROVIDERS) {
    out[p.id] = {
      key: "",
      validation: "idle",
      error: null,
      expanded: false,
      elyMode: false,
    };
  }
  return out;
}

// ---------------------------------------------------------------------------
// Step progress indicator
// ---------------------------------------------------------------------------

function ProgressBar({ current, steps }: { current: number; steps: { label: string }[] }) {
  return (
    <div className="flex items-center gap-1 mb-8">
      {steps.map((s, i) => (
        <div key={i} className="flex items-center gap-1 flex-1 min-w-0">
          <div
            className={`flex items-center justify-center w-6 h-6 rounded-full border text-[10px] font-mono shrink-0 transition-all ${
              i < current
                ? "bg-cyber-cyan/20 border-cyber-cyan text-cyber-cyan"
                : i === current
                ? "bg-cyber-cyan/10 border-cyber-cyan/60 text-cyber-cyan animate-pulse"
                : "bg-transparent border-border-dim text-text-muted"
            }`}
          >
            {i < current ? <Check className="w-3 h-3" /> : i + 1}
          </div>
          <span
            className={`text-[10px] font-mono truncate hidden sm:block ${
              i === current ? "text-cyber-cyan" : "text-text-muted"
            }`}
          >
            {s.label}
          </span>
          {i < steps.length - 1 && (
            <div
              className={`flex-1 h-px mx-1 ${
                i < current ? "bg-cyber-cyan/40" : "bg-border-dim"
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ELY Avatar (CSS-only, no Three.js dependency for setup)
// ---------------------------------------------------------------------------


// ---------------------------------------------------------------------------
// Step 0 — Welcome
// ---------------------------------------------------------------------------

function StepWelcomeContent({ onNext, welcomeTitle, welcomeDescription, welcomeTime, startSetup }: {
  onNext: () => void;
  welcomeTitle: string;
  welcomeDescription: string;
  welcomeTime: string;
  startSetup: string;
}) {
  return (
    <div className="flex flex-col items-center text-center gap-6 py-8">
      {/* 3D cyberpunk avatar — sets the tone immediately */}
      <div style={{ width: 220, height: 264 }}>
        <CyberpunkAvatar state="idle" className="w-full h-full" minimal />
      </div>

      <div>
        <p className="text-xs font-mono text-cyber-cyan/60 tracking-widest uppercase mb-2">
          Exactly Like You
        </p>
        <h1 className="text-2xl font-bold text-text-primary mb-3">
          {welcomeTitle}
        </h1>
        <p className="text-sm text-text-secondary max-w-md">
          {welcomeDescription}{" "}
          <strong className="text-text-primary">{welcomeTime}</strong>.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 w-full max-w-lg text-left">
        {[
          { icon: Zap, label: "Modèle IA", desc: "Au moins un fournisseur" },
          { icon: Globe, label: "Google (optionnel)", desc: "Gmail, Drive, Agenda" },
          { icon: MessageCircle, label: "Telegram (optionnel)", desc: "Parlez depuis votre téléphone" },
        ].map(({ icon: Icon, label, desc }) => (
          <div
            key={label}
            className="flex flex-col gap-1 p-3 rounded-lg bg-bg-secondary border border-border-dim"
          >
            <Icon className="w-4 h-4 text-cyber-cyan mb-1" />
            <span className="text-xs font-medium text-text-primary">{label}</span>
            <span className="text-[11px] text-text-muted">{desc}</span>
          </div>
        ))}
      </div>

      <button
        onClick={onNext}
        className="flex items-center gap-2 px-6 py-3 rounded-lg bg-cyber-cyan/10 border border-cyber-cyan/40 text-cyber-cyan font-medium text-sm hover:bg-cyber-cyan/20 transition-all"
      >
        {startSetup}
        <ChevronRight className="w-4 h-4" />
      </button>
    </div>
  );
}

function StepWelcome({ onNext }: { onNext: () => void }) {
  const t = useTranslations("setup");
  return (
    <StepWelcomeContent
      onNext={onNext}
      welcomeTitle={t("welcomeTitle")}
      welcomeDescription={t("welcomeDescription")}
      welcomeTime={t("welcomeTime")}
      startSetup={t("startSetup")}
    />
  );
}

// ---------------------------------------------------------------------------
// Step 1 — LLM Providers
// ---------------------------------------------------------------------------

function ProviderCard({
  provider,
  state,
  ollamaAvailable,
  alreadyConfigured,
  onChange,
  onValidate,
  onSave,
  onToggle,
  onElyMode,
}: {
  provider: ProviderConfig;
  state: ProviderState;
  ollamaAvailable: boolean;
  alreadyConfigured: boolean;
  onChange: (key: string) => void;
  onValidate: () => void;
  onSave: () => void;
  onToggle: () => void;
  onElyMode: () => void;
}) {
  const keyInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (state.elyMode && keyInputRef.current) {
      keyInputRef.current.focus();
    }
  }, [state.elyMode]);

  const isSaved = state.validation === "saved" || alreadyConfigured;
  const isValid = state.validation === "valid";

  return (
    <div
      className={`rounded-lg border transition-all overflow-hidden ${
        isSaved
          ? "border-emerald-500/30 bg-emerald-500/5"
          : state.expanded
          ? "border-cyber-cyan/30 bg-bg-secondary"
          : "border-border-dim bg-bg-secondary hover:border-border-dim/80"
      }`}
    >
      {/* Header row */}
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 text-left"
      >
        <div className="flex items-center gap-3">
          <div
            className="w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: isSaved ? "#10b981" : provider.color }}
          />
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-medium text-text-primary">{provider.name}</span>
              <span
                className="text-[9px] px-1.5 py-0.5 rounded border font-mono"
                style={{
                  color: provider.color,
                  borderColor: `${provider.color}40`,
                  backgroundColor: `${provider.color}10`,
                }}
              >
                {provider.role}
              </span>
              {isSaved && (
                <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                  <Check className="w-2.5 h-2.5" />
                  Configuré
                </span>
              )}
            </div>
            <p className="text-[11px] text-text-muted mt-0.5">{provider.description}</p>
          </div>
        </div>
        <ChevronRight
          className={`w-4 h-4 text-text-muted shrink-0 transition-transform ${state.expanded ? "rotate-90" : ""}`}
        />
      </button>

      {/* Expanded content */}
      {state.expanded && (
        <div className="px-4 pb-4 space-y-4 border-t border-border-dim pt-4">

          {/* ELY mode banner */}
          {state.elyMode && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-cyber-cyan/5 border border-cyber-cyan/20">
              <Bot className="w-4 h-4 text-cyber-cyan shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-medium text-cyber-cyan">
                  ELY a ouvert la page de création de clé
                </p>
                <p className="text-[11px] text-text-secondary mt-1">
                  Suivez les étapes ci-dessous, copiez votre clé et collez-la dans le champ.
                </p>
                <div className="flex items-center gap-1.5 mt-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyber-cyan animate-pulse" />
                  <span className="text-[10px] text-text-muted font-mono">En attente de votre clé...</span>
                </div>
              </div>
            </div>
          )}

          {/* Steps */}
          <div>
            <p className="text-[11px] text-text-muted uppercase tracking-wider mb-2 font-mono">
              Étapes
            </p>
            <ol className="space-y-1.5">
              {provider.steps.map((step, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-text-secondary">
                  <span className="shrink-0 w-4 h-4 rounded-full border border-border-dim text-[9px] flex items-center justify-center text-text-muted font-mono">
                    {i + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap gap-2">
            <a
              href={provider.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border-dim text-text-secondary hover:border-cyber-cyan/30 hover:text-cyber-cyan transition-all"
            >
              <ExternalLink className="w-3 h-3" />
              Ouvrir {provider.urlLabel} →
            </a>
            {!state.elyMode && (
              <button
                onClick={onElyMode}
                className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-cyber-cyan/20 bg-cyber-cyan/5 text-cyber-cyan hover:bg-cyber-cyan/10 transition-all"
              >
                <Bot className="w-3 h-3" />
                ELY ouvre la page pour vous
              </button>
            )}
          </div>

          {/* Key input */}
          <div className="space-y-2">
            <div className="flex gap-2">
              <div className="flex-1 relative">
                <Key className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-text-muted" />
                <input
                  ref={keyInputRef}
                  type="password"
                  value={state.key}
                  onChange={(e) => onChange(e.target.value)}
                  placeholder={provider.keyPlaceholder}
                  autoComplete="new-password"
                  className="w-full text-xs bg-bg-primary border border-border-dim rounded pl-7 pr-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
                />
              </div>

              {/* Validate button */}
              {state.validation !== "saved" && !alreadyConfigured && (
                <button
                  onClick={onValidate}
                  disabled={!state.key.trim() || state.validation === "validating"}
                  className="text-xs px-3 py-2 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all disabled:opacity-40 shrink-0"
                >
                  {state.validation === "validating" ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    "Valider"
                  )}
                </button>
              )}
            </div>

            {/* Validation feedback */}
            {(state.validation === "valid" || state.validation === "saving") && (
              <div className="flex items-center gap-1.5 text-[11px] text-emerald-400">
                <CheckCircle className="w-3 h-3" />
                Clé valide !
                <button
                  onClick={onSave}
                  disabled={state.validation === "saving"}
                  className="ml-2 text-xs px-3 py-1 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-all disabled:opacity-40"
                >
                  {state.validation === "saving" ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    "Enregistrer"
                  )}
                </button>
              </div>
            )}
            {state.validation === "invalid" && state.error && (
              <div className="flex items-center gap-1.5 text-[11px] text-red-400">
                <XCircle className="w-3 h-3" />
                {state.error}
              </div>
            )}
            {(state.validation === "saved" || alreadyConfigured) && (
              <div className="flex items-center gap-1.5 text-[11px] text-emerald-400">
                <CheckCircle className="w-3 h-3" />
                Clé enregistrée avec succès
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function StepLLM({
  status,
  onNext,
  onBack,
}: {
  status: SetupStatus | null;
  onNext: () => void;
  onBack: () => void;
}) {
  const [providerStates, setProviderStates] = useState<Record<string, ProviderState>>(
    makeInitialProviderState
  );
  const [ollamaStatus, setOllamaStatus] = useState<{ available: boolean; models: string[] } | null>(null);

  // Test Ollama on mount
  useEffect(() => {
    authFetch(`${API_URL}/api/setup/test-ollama`, { method: "POST" })
      .then((r) => r.json())
      .then((d) => setOllamaStatus(d))
      .catch(() => setOllamaStatus({ available: false, models: [] }));
  }, []);

  const updateProvider = useCallback(
    (id: string, patch: Partial<ProviderState>) => {
      setProviderStates((prev) => ({
        ...prev,
        [id]: { ...prev[id], ...patch },
      }));
    },
    []
  );

  const handleValidate = useCallback(
    async (id: string) => {
      const s = providerStates[id];
      if (!s.key.trim()) return;
      updateProvider(id, { validation: "validating", error: null });
      try {
        const res = await authFetch(`${API_URL}/api/setup/validate-key`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: id, key: s.key.trim() }),
        });
        const data = await res.json();
        if (data.valid) {
          updateProvider(id, { validation: "valid" });
        } else {
          updateProvider(id, { validation: "invalid", error: data.error ?? "Clé invalide" });
        }
      } catch {
        updateProvider(id, { validation: "invalid", error: "Erreur réseau" });
      }
    },
    [providerStates, updateProvider]
  );

  const handleSave = useCallback(
    async (id: string) => {
      const s = providerStates[id];
      updateProvider(id, { validation: "saving" as ValidationState });
      try {
        const res = await authFetch(`${API_URL}/api/setup/save-key`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: id, key: s.key.trim() }),
        });
        if (res.ok) {
          updateProvider(id, { validation: "saved" });
        } else {
          const err = await res.json().catch(() => ({}));
          updateProvider(id, {
            validation: "invalid",
            error: err.detail ?? "Erreur lors de la sauvegarde",
          });
        }
      } catch {
        updateProvider(id, { validation: "invalid", error: "Erreur réseau" });
      }
    },
    [providerStates, updateProvider]
  );

  const handleElyMode = useCallback(
    (id: string) => {
      const p = PROVIDERS.find((x) => x.id === id);
      if (!p) return;
      window.open(p.url, "_blank");
      updateProvider(id, { elyMode: true });
    },
    [updateProvider]
  );

  const cloudLlm = status?.llm as Record<string, LLMProviderStatus> | undefined;
  const anySaved =
    ollamaStatus?.available ||
    PROVIDERS.some(
      (p) =>
        providerStates[p.id]?.validation === "saved" ||
        cloudLlm?.[p.id]?.configured
    );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-text-primary mb-1">
          Intelligence — Choisissez vos modèles IA
        </h2>
        <p className="text-sm text-text-secondary">
          ELY route chaque requête intelligemment : local pour les questions simples, puissant pour les tâches complexes.
        </p>
      </div>

      {/* Ollama card */}
      <div
        className={`p-4 rounded-lg border flex items-center justify-between ${
          ollamaStatus?.available
            ? "border-emerald-500/30 bg-emerald-500/5"
            : "border-border-dim bg-bg-secondary"
        }`}
      >
        <div className="flex items-center gap-3">
          <Server className={`w-5 h-5 ${ollamaStatus?.available ? "text-emerald-400" : "text-text-muted"}`} />
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-text-primary">Ollama (local)</span>
              <span className="text-[9px] px-1.5 py-0.5 rounded border border-border-dim text-text-muted font-mono">
                100% local
              </span>
              {ollamaStatus?.available && (
                <span className="inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                  <Check className="w-2.5 h-2.5" />
                  Disponible
                </span>
              )}
            </div>
            <p className="text-[11px] text-text-muted mt-0.5">
              {ollamaStatus === null
                ? "Détection en cours..."
                : ollamaStatus.available
                ? `Modèles : ${ollamaStatus.models.slice(0, 3).join(", ") || "aucun modèle chargé"}`
                : "Non détecté — démarrez Ollama pour l'utiliser"}
            </p>
          </div>
        </div>
        {ollamaStatus === null && <Loader2 className="w-4 h-4 text-text-muted animate-spin" />}
      </div>

      {/* Provider cards */}
      <div className="space-y-3">
        {PROVIDERS.map((p) => {
          const llmStatus = status?.llm[p.id as keyof typeof status.llm];
          const alreadyConfigured = (llmStatus as LLMProviderStatus)?.configured ?? false;
          return (
            <ProviderCard
              key={p.id}
              provider={p}
              state={providerStates[p.id]}
              ollamaAvailable={ollamaStatus?.available ?? false}
              alreadyConfigured={alreadyConfigured}
              onChange={(key) => updateProvider(p.id, { key, validation: "idle", error: null })}
              onValidate={() => handleValidate(p.id)}
              onSave={() => handleSave(p.id)}
              onToggle={() =>
                updateProvider(p.id, { expanded: !providerStates[p.id].expanded })
              }
              onElyMode={() => handleElyMode(p.id)}
            />
          );
        })}
      </div>

      {!anySaved && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs">
          <AlertCircle className="w-4 h-4 shrink-0" />
          Configurez au moins un fournisseur IA pour continuer.
        </div>
      )}

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm px-4 py-2 rounded border border-border-dim text-text-secondary hover:border-text-muted transition-all"
        >
          <ChevronLeft className="w-4 h-4" />
          Retour
        </button>
        <button
          onClick={onNext}
          disabled={!anySaved}
          className="flex items-center gap-1.5 text-sm px-5 py-2 rounded border border-cyber-cyan/40 bg-cyber-cyan/10 text-cyber-cyan hover:bg-cyber-cyan/20 transition-all disabled:opacity-40"
        >
          Continuer
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — Google
// ---------------------------------------------------------------------------

function StepGoogle({
  status,
  onNext,
  onBack,
}: {
  status: SetupStatus | null;
  onNext: () => void;
  onBack: () => void;
}) {
  const [googleLoading, setGoogleLoading] = useState(false);
  const [googleConnected, setGoogleConnected] = useState(status?.google?.connected ?? false);
  const [error, setError] = useState<string | null>(null);

  // Handle redirect-back from OAuth callback
  useEffect(() => {
    if (typeof window !== "undefined" && window.location.search.includes("google=connected")) {
      setGoogleConnected(true);
      window.history.replaceState({}, "", "/setup");
    }
  }, []);

  const handleConnect = async () => {
    setGoogleLoading(true);
    setError(null);
    try {
      const res = await authFetch(`${API_URL}/api/google/auth-url`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Erreur ${res.status}`);
      if (!data.url) throw new Error("URL OAuth manquante");
      // Save the current step so we come back here after OAuth
      localStorage.setItem("ely_setup_step", "2");
      window.location.href = data.url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur lors de la connexion Google");
    } finally {
      setGoogleLoading(false);
    }
  };

  const googleServices = [
    { label: "Gmail", desc: "Lire et envoyer des emails sur demande" },
    { label: "Google Calendar", desc: "Consulter et créer des événements" },
    { label: "Google Drive", desc: "Accéder aux documents (lecture)" },
    { label: "Google Tasks", desc: "Gérer vos listes de tâches" },
    { label: "Contacts", desc: "Retrouver vos contacts" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-text-primary mb-1">
          Google Workspace — Gmail, Drive, Agenda
        </h2>
        <p className="text-sm text-text-secondary">
          Connectez votre compte Google pour qu'ELY puisse accéder à vos outils sur demande.
        </p>
      </div>

      {/* Services list */}
      <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-3">
        <p className="text-xs text-text-muted uppercase tracking-wider font-mono">
          Ce qu'ELY peut faire avec Google
        </p>
        {googleServices.map(({ label, desc }) => (
          <div key={label} className="flex items-start gap-2 text-xs">
            <Check className="w-3.5 h-3.5 text-cyber-cyan shrink-0 mt-0.5" />
            <div>
              <span className="font-medium text-text-primary">{label}</span>
              <span className="text-text-muted"> — {desc}</span>
            </div>
          </div>
        ))}

        <p className="text-[11px] text-text-muted pt-2 border-t border-border-dim">
          ELY n'accède à ces services que sur votre demande explicite. Les tokens OAuth sont stockés localement et chiffrés.
        </p>
      </div>

      {/* Connect button / status */}
      {googleConnected ? (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
          <CheckCircle className="w-4 h-4 text-emerald-400" />
          <span className="text-sm text-emerald-400 font-medium">Google connecté</span>
        </div>
      ) : (
        <div className="space-y-3">
          {!status?.google?.configured && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>
                L'application Google OAuth n'est pas encore configurée.
                Rendez-vous dans{" "}
                <a href="/admin" className="underline">Admin → OAuth Google</a>{" "}
                pour renseigner le Client ID et Secret.
              </span>
            </div>
          )}
          {error && (
            <div className="flex items-center gap-2 text-xs text-red-400">
              <XCircle className="w-3.5 h-3.5" />
              {error}
            </div>
          )}
          <button
            onClick={handleConnect}
            disabled={googleLoading || !status?.google?.configured}
            className="flex items-center gap-2 text-sm px-4 py-2.5 rounded-lg border border-cyber-cyan/30 bg-cyber-cyan/5 text-cyber-cyan hover:bg-cyber-cyan/10 transition-all disabled:opacity-40"
          >
            <Globe className="w-4 h-4" />
            {googleLoading ? "Redirection..." : "Connecter mon compte Google"}
            <ExternalLink className="w-3.5 h-3.5 opacity-60" />
          </button>
        </div>
      )}

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm px-4 py-2 rounded border border-border-dim text-text-secondary hover:border-text-muted transition-all"
        >
          <ChevronLeft className="w-4 h-4" />
          Retour
        </button>
        <div className="flex items-center gap-3">
          <button
            onClick={onNext}
            className="text-xs text-text-muted hover:text-text-secondary transition-all"
          >
            Passer cette étape
          </button>
          {googleConnected && (
            <button
              onClick={onNext}
              className="flex items-center gap-1.5 text-sm px-5 py-2 rounded border border-cyber-cyan/40 bg-cyber-cyan/10 text-cyber-cyan hover:bg-cyber-cyan/20 transition-all"
            >
              Continuer
              <ChevronRight className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3 — Telegram
// ---------------------------------------------------------------------------

function StepTelegram({
  status,
  onNext,
  onBack,
}: {
  status: SetupStatus | null;
  onNext: () => void;
  onBack: () => void;
}) {
  const [token, setToken] = useState("");
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [valid, setValid] = useState<null | boolean>(null);
  const [botName, setBotName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(status?.telegram?.configured ?? false);

  const handleElyMode = () => {
    window.open("https://t.me/BotFather", "_blank");
  };

  const handleValidate = async () => {
    if (!token.trim()) return;
    setValidating(true);
    setError(null);
    try {
      const res = await authFetch(`${API_URL}/api/setup/validate-telegram`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token.trim() }),
      });
      const data = await res.json();
      if (data.valid) {
        setValid(true);
        setBotName(data.bot_name ?? null);
      } else {
        setValid(false);
        setError(data.error ?? "Token invalide");
      }
    } catch {
      setValid(false);
      setError("Erreur réseau");
    } finally {
      setValidating(false);
    }
  };

  const handleSave = async () => {
    if (!token.trim()) return;
    setSaving(true);
    try {
      const res = await authFetch(`${API_URL}/api/setup/save-telegram`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token.trim() }),
      });
      if (res.ok) {
        setSaved(true);
      } else {
        const err = await res.json().catch(() => ({}));
        setError(err.detail ?? "Erreur lors de la sauvegarde");
      }
    } catch {
      setError("Erreur réseau");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-text-primary mb-1">
          Telegram — Parlez à ELY depuis votre téléphone
        </h2>
        <p className="text-sm text-text-secondary">
          Créez un bot Telegram en 2 minutes avec BotFather et connectez-le à ELY.
        </p>
      </div>

      {saved ? (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
          <CheckCircle className="w-4 h-4 text-emerald-400" />
          <span className="text-sm text-emerald-400 font-medium">
            Bot Telegram connecté{botName ? ` (@${botName})` : ""}
          </span>
        </div>
      ) : (
        <div className="bg-bg-secondary border border-border-dim rounded-lg p-4 space-y-4">

          {/* Instructions */}
          <div>
            <p className="text-xs text-text-muted uppercase tracking-wider font-mono mb-3">
              Étapes avec BotFather
            </p>
            <ol className="space-y-2">
              {[
                "Ouvrez Telegram et cherchez @BotFather",
                "Envoyez la commande /newbot",
                "Choisissez un nom pour votre bot (ex : Mon ELY)",
                "Choisissez un nom d'utilisateur (doit finir par bot, ex : mon_ely_bot)",
                "Copiez le token que BotFather vous envoie",
              ].map((step, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-text-secondary">
                  <span className="shrink-0 w-4 h-4 rounded-full border border-border-dim text-[9px] flex items-center justify-center text-text-muted font-mono">
                    {i + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
          </div>

          {/* Buttons */}
          <div className="flex flex-wrap gap-2">
            <a
              href="https://t.me/BotFather"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-border-dim text-text-secondary hover:border-cyber-cyan/30 hover:text-cyber-cyan transition-all"
            >
              <ExternalLink className="w-3 h-3" />
              Ouvrir Telegram Web →
            </a>
            <button
              onClick={handleElyMode}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-cyber-cyan/20 bg-cyber-cyan/5 text-cyber-cyan hover:bg-cyber-cyan/10 transition-all"
            >
              <Bot className="w-3 h-3" />
              ELY ouvre BotFather pour vous
            </button>
          </div>

          {/* Token input */}
          <div className="space-y-2">
            <div className="flex gap-2">
              <div className="flex-1 relative">
                <Key className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-text-muted" />
                <input
                  type="password"
                  value={token}
                  onChange={(e) => {
                    setToken(e.target.value);
                    setValid(null);
                    setError(null);
                  }}
                  placeholder="1234567890:ABCDEFGHijklmnopqrstuvwxyz..."
                  autoComplete="new-password"
                  className="w-full text-xs bg-bg-primary border border-border-dim rounded pl-7 pr-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40"
                />
              </div>
              <button
                onClick={handleValidate}
                disabled={!token.trim() || validating}
                className="text-xs px-3 py-2 rounded border border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/5 transition-all disabled:opacity-40 shrink-0"
              >
                {validating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Valider"}
              </button>
            </div>

            {valid === true && (
              <div className="flex items-center gap-2 text-[11px] text-emerald-400">
                <CheckCircle className="w-3 h-3" />
                Token valide{botName ? ` — bot @${botName}` : ""} !
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="ml-1 text-xs px-3 py-1 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-all disabled:opacity-40"
                >
                  {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : "Enregistrer"}
                </button>
              </div>
            )}
            {valid === false && error && (
              <div className="flex items-center gap-1.5 text-[11px] text-red-400">
                <XCircle className="w-3 h-3" />
                {error}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm px-4 py-2 rounded border border-border-dim text-text-secondary hover:border-text-muted transition-all"
        >
          <ChevronLeft className="w-4 h-4" />
          Retour
        </button>
        <div className="flex items-center gap-3">
          <button
            onClick={onNext}
            className="text-xs text-text-muted hover:text-text-secondary transition-all"
          >
            Passer cette étape
          </button>
          {saved && (
            <button
              onClick={onNext}
              className="flex items-center gap-1.5 text-sm px-5 py-2 rounded border border-cyber-cyan/40 bg-cyber-cyan/10 text-cyber-cyan hover:bg-cyber-cyan/20 transition-all"
            >
              Continuer
              <ChevronRight className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4 — Summary & Launch
// ---------------------------------------------------------------------------

function StepSummary({
  status,
  onBack,
  onLaunch,
}: {
  status: SetupStatus | null;
  onBack: () => void;
  onLaunch: () => void;
}) {
  const llmConfigured = status
    ? Object.entries(status.llm)
        .filter(([id]) => id !== "ollama")
        .some(([, v]) => (v as LLMProviderStatus).configured) ||
      (status.llm.ollama as { available: boolean }).available
    : false;

  const items = [
    {
      label: "Intelligence IA",
      ok: llmConfigured,
      required: true,
      hint: "Au moins un fournisseur LLM configuré",
    },
    {
      label: "Google Workspace",
      ok: status?.google?.connected ?? false,
      required: false,
      hint: "Gmail, Drive, Agenda",
    },
    {
      label: "Telegram",
      ok: status?.telegram?.configured ?? false,
      required: false,
      hint: "Bot Telegram",
    },
  ];

  return (
    <div className="space-y-6">
      <div className="text-center">
        <div style={{ width: 160, height: 192 }} className="mx-auto">
          <CyberpunkAvatar state="speaking" className="w-full h-full" minimal />
        </div>
        <h2 className="text-xl font-bold text-text-primary mt-4 mb-1">
          ELY est prêt !
        </h2>
        <p className="text-sm text-text-secondary">
          Voici un résumé de votre configuration.
        </p>
      </div>

      {/* Summary cards */}
      <div className="space-y-2">
        {items.map(({ label, ok, required, hint }) => (
          <div
            key={label}
            className={`flex items-center justify-between p-3 rounded-lg border ${
              ok
                ? "border-emerald-500/20 bg-emerald-500/5"
                : required
                ? "border-red-500/20 bg-red-500/5"
                : "border-border-dim bg-bg-secondary"
            }`}
          >
            <div className="flex items-center gap-2">
              {ok ? (
                <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />
              ) : (
                <XCircle className={`w-4 h-4 shrink-0 ${required ? "text-red-400" : "text-text-muted"}`} />
              )}
              <div>
                <p className="text-xs font-medium text-text-primary">{label}</p>
                <p className="text-[11px] text-text-muted">{hint}</p>
              </div>
            </div>
            <span
              className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
                ok
                  ? "text-emerald-400 border-emerald-500/20 bg-emerald-500/10"
                  : required
                  ? "text-red-400 border-red-500/20 bg-red-500/10"
                  : "text-text-muted border-border-dim"
              }`}
            >
              {ok ? "Configuré" : required ? "Requis" : "Optionnel"}
            </span>
          </div>
        ))}
      </div>

      <p className="text-[11px] text-text-muted text-center">
        Ces paramètres peuvent être modifiés à tout moment dans les{" "}
        <a href="/settings" className="text-cyber-cyan hover:underline">
          Paramètres
        </a>
        .
      </p>

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm px-4 py-2 rounded border border-border-dim text-text-secondary hover:border-text-muted transition-all"
        >
          <ChevronLeft className="w-4 h-4" />
          Retour
        </button>
        <button
          onClick={onLaunch}
          disabled={!llmConfigured}
          className="flex items-center gap-2 text-sm px-6 py-3 rounded-lg border border-cyber-cyan/40 bg-cyber-cyan/10 text-cyber-cyan font-medium hover:bg-cyber-cyan/20 transition-all disabled:opacity-40"
        >
          <Rocket className="w-4 h-4" />
          Lancer ELY
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function SetupPage() {
  const t = useTranslations("setup");
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [step, setStep] = useState(0);
  const [status, setStatus] = useState<SetupStatus | null>(null);

  const STEPS = [
    { label: t("stepWelcome") },
    { label: t("stepAi") },
    { label: t("stepGoogle") },
    { label: t("stepTelegram") },
    { label: t("stepReady") },
  ];

  // Auth check
  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    setChecked(true);

    // Restore step if redirected back from OAuth
    const savedStep = localStorage.getItem("ely_setup_step");
    if (savedStep) {
      setStep(parseInt(savedStep, 10));
      localStorage.removeItem("ely_setup_step");
    }
  }, [router]);

  // Load setup status
  useEffect(() => {
    if (!checked) return;
    authFetch(`${API_URL}/api/setup/status/me`)
      .then((r) => r.json())
      .then((d: SetupStatus) => setStatus(d))
      .catch(() => {});
  }, [checked]);

  const handleLaunch = () => {
    localStorage.setItem("ely_setup_completed", "true");
    router.push("/chat");
  };

  if (!checked) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#060c16]">
        <div className="text-cyber-cyan animate-pulse text-sm font-mono">
          Vérification de l'accès...
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#060c16] flex items-center justify-center px-4 py-8">
      {/* Background grid effect */}
      <div
        className="fixed inset-0 pointer-events-none opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(#00d2ff 1px, transparent 1px), linear-gradient(90deg, #00d2ff 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />

      <div className="relative w-full max-w-xl">
        {/* Header */}
        <div className="text-center mb-6">
          <p className="text-xs font-mono text-cyber-cyan/60 tracking-widest uppercase">
            ELY — Assistant Setup
          </p>
        </div>

        {/* Progress */}
        {step > 0 && <ProgressBar current={step} steps={STEPS} />}

        {/* Card */}
        <div className="bg-bg-secondary/80 backdrop-blur-sm border border-border-dim rounded-xl p-6 shadow-2xl">
          {step === 0 && (
            <StepWelcome onNext={() => setStep(1)} />
          )}
          {step === 1 && (
            <StepLLM
              status={status}
              onNext={() => setStep(2)}
              onBack={() => setStep(0)}
            />
          )}
          {step === 2 && (
            <StepGoogle
              status={status}
              onNext={() => setStep(3)}
              onBack={() => setStep(1)}
            />
          )}
          {step === 3 && (
            <StepTelegram
              status={status}
              onNext={() => setStep(4)}
              onBack={() => setStep(2)}
            />
          )}
          {step === 4 && (
            <StepSummary
              status={status}
              onBack={() => setStep(3)}
              onLaunch={handleLaunch}
            />
          )}
        </div>
      </div>
    </div>
  );
}
