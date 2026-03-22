import type { WSMessage } from "./types";
import { getAccessToken } from "./auth";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
const MAX_RECONNECT_ATTEMPTS = 5;

export class AgentWebSocket {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  // Set to true by disconnect() to prevent any further reconnect attempts.
  private destroyed = false;
  private onMessageCallback: ((msg: WSMessage) => void) | null = null;
  private onStatusCallback: ((status: "connected" | "disconnected" | "connecting") => void) | null = null;

  connect() {
    if (this.destroyed) return;

    const token = getAccessToken();
    if (!token) return;

    this.onStatusCallback?.("connecting");
    this.ws = new WebSocket(`${WS_URL}/ws/chat?token=${token}`);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.onStatusCallback?.("connected");
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        this.onMessageCallback?.(msg);
      } catch {
        // ignore parse errors
      }
    };

    this.ws.onclose = () => {
      this.onStatusCallback?.("disconnected");
      if (!this.destroyed) {
        this.tryReconnect();
      }
    };

    this.ws.onerror = () => {
      // onclose fires immediately after onerror; just close the socket here.
      this.ws?.close();
    };
  }

  private tryReconnect() {
    if (this.destroyed) return;
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return;

    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
    // Cancel any previously queued reconnect before scheduling a new one
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  send(content: string, conversationId?: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ content, conversation_id: conversationId }));
    }
  }

  onMessage(callback: (msg: WSMessage) => void) {
    this.onMessageCallback = callback;
  }

  onStatus(callback: (status: "connected" | "disconnected" | "connecting") => void) {
    this.onStatusCallback = callback;
  }

  disconnect() {
    this.destroyed = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }
}
