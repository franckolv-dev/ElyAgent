/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/types.ts
 * @brief      Shared TypeScript types — domain model interfaces
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
  file_id: string;
  filename: string;
  path: string;
  size: number;
  mime_type: string;
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
  type: "start" | "message" | "error" | "stream" | "token" | "hitl_pending" | "hitl_resolved" | "browser_frame" | "tool_start" | "tool_end" | "stopped";
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
