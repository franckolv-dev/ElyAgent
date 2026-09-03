/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/types.ts
 * @brief      Shared TypeScript types — domain model interfaces
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
export interface User {
  id: string;
  username: string;
  email: string;
  role: "admin" | "user";
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  /** @deprecated refresh_token is now an HttpOnly cookie — no longer in response body */
  refresh_token?: string;
}

export interface Attachment {
  /** User-uploaded attachments have a file_id from the upload endpoint;
   *  assistant attachments (extracted from MEDIA: sentinels) don't — use
   *  ``path`` as a stable identifier instead. */
  file_id?: string;
  filename: string;
  path: string;
  size: number;
  mime_type: string;
  /** Signed-URL expiry (Unix seconds) — only set on assistant attachments
   *  produced by media_router.py. */
  exp?: number;
  /** HMAC signature over path|exp — required to fetch the file. */
  sig?: string;
}

export interface ToolImage {
  type: "image";
  mime: string;
  data: string;    // base64
  prompt?: string;
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
  attachments?: Attachment[];
  /** Images produced by tools (QR code, Imagen, etc.) */
  toolImages?: ToolImage[];
  /** "slm:qwen2.5:3b-instruct" or "llm:anthropic/claude-..." — set by backend */
  model_used?: string;
  /** IntentRouter score 0-100 — for feedback context */
  routing_score?: number;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface WSMessage {
  type:
    | "start" | "message" | "error" | "stream" | "token"
    | "hitl_pending" | "hitl_resolved"
    | "browser_frame" | "tool_start" | "tool_end" | "stopped"
    // Hotfix 2026-05-23 — explicit "turn-end" signal emitted by the
    // backend after every "message" and "stopped" event, plus on
    // receipt of a "stop" while no agent is running. Guarantees the
    // frontend can flip `isLoading=false` independently of React's
    // state-update batching timing.
    | "done"
    // Hermes Chantier 4 — fired when fallback_manager swaps providers
    // mid-conversation (rate limit, h1_hallucination, billing, …) so
    // the user sees a discreet toast instead of being confused by a
    // sudden change in latency or wording.
    | "provider.switched"
    // Le tour est reparti sur le CLOUD parce que le modèle LOCAL n'a pas
    // répondu (délai dépassé, erreur de chargement). Distinct de
    // `provider.switched` : celui-là fait AVANCER la chaîne de repli et
    // reste collant pour la conversation ; celui-ci ne décide rien, il
    // signale. Sans lui, l'utilisateur voyait « gpt-5.6-sol » répondre à
    // « bonjour » sans savoir pourquoi (21/08).
    | "slm.fallback";
  tool?: string;
  image?: ToolImage;   // present on tool_end when tool produced an image
  content?: string;
  role?: string;
  conversation_id?: string;
  // HITL fields
  action_id?: string;
  description?: string;
  decision?: string;
  reason?: string;
  // SLM/LLM routing info
  model_used?: string;
  routing_score?: number;
  // Server timestamp for messages
  created_at?: string;
  // Browser copilot fields
  data?: string;   // base64 PNG screenshot
  url?: string;
  title?: string;
  // Attachments extracted from MEDIA: sentinels by backend media_router
  attachments?: Attachment[];
  // provider.switched fields (typed strings as emitted by fallback_manager)
  from?: string;
  to?: string;
  ts?: number;
  // slm.fallback — le modèle local qui n'a pas pu répondre. `reason` (plus
  // haut) porte le pourquoi : sans lui, « repli » n'apprend rien.
  model?: string;
  // Compteurs du tour, portés par le message final. Le panneau SESSION les
  // lisait déjà — via un `as unknown as {…}` faute de les trouver ici — mais
  // le backend ne les émettait PAS : « TOKENS » affichait « — » sur tous les
  // tours depuis toujours. Le cast masquait exactement ce que le type aurait
  // signalé (21/08).
  input_tokens?: number;
  output_tokens?: number;
  // ⚠️ Vrai quand les compteurs sont ESTIMÉS (serveur local sans
  // `usage_metadata`) et non mesurés. L'affichage doit le dire — un « ~ »
  // suffit. Une estimation muette se lit comme une mesure.
  tokens_estimated?: boolean;
}

export interface BrowserFrame {
  data: string;   // base64 PNG
  url: string;
  title: string;
}

export interface SSHHost {
  hostname: string;
  port: number;
  username: string;
  allowed_commands: string[];
}

export interface AuditLog {
  id: string;
  user_id: string;
  action: string;
  target_host: string | null;
  command: string | null;
  result_code: number | null;
  details: string | null;
  created_at: string;
}
