export interface User {
  id: string;
  username: string;
  email: string;
  role: "admin" | "user";
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface WSMessage {
  type: "start" | "message" | "error" | "stream" | "hitl_pending" | "hitl_resolved";
  content?: string;
  role?: string;
  conversation_id?: string;
  // HITL fields
  action_id?: string;
  description?: string;
  decision?: string;
  reason?: string;
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
