import type { WSMessage } from "./types";
import { getAccessToken } from "./auth";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

/**
 * Persistent WebSocket client with unlimited auto-reconnect.
 *
 * Backoff strategy:
 *   attempt 1 → 2 s
 *   attempt 2 → 4 s
 *   attempt 3 → 8 s
 *   attempt 4 → 16 s
 *   attempt 5+ → 30 s  (stays at 30 s forever until connection succeeds)
 *
 * Calling disconnect() stops all reconnect attempts permanently.
 */
export class AgentWebSocket {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;
  private onMessageCallback: ((msg: WSMessage) => void) | null = null;
  private onStatusCallback:  ((status: "connected" | "disconnected" | "connecting") => void) | null = null;

  connect() {
    if (this.destroyed) return;

    const token = getAccessToken();
    if (!token) return;

    this.onStatusCallback?.("connecting");
    this.ws = new WebSocket(`${WS_URL}/ws/chat?token=${token}`);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;   // reset backoff on successful connection
      this.onStatusCallback?.("connected");
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        this.onMessageCallback?.(msg);
      } catch {
        // ignore malformed frames
      }
    };

    this.ws.onclose = () => {
      this.onStatusCallback?.("disconnected");
      if (!this.destroyed) this.tryReconnect();
    };

    this.ws.onerror = () => {
      // onclose fires immediately after onerror
      this.ws?.close();
    };
  }

  private tryReconnect() {
    if (this.destroyed) return;

    // Cap attempt counter at 5 so the delay plateaus at 30 s instead of growing forever
    this.reconnectAttempts = Math.min(this.reconnectAttempts + 1, 5);
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30_000);

    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer);
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

  onMessage(cb: (msg: WSMessage) => void)  { this.onMessageCallback = cb; }
  onStatus(cb:  (status: "connected" | "disconnected" | "connecting") => void) {
    this.onStatusCallback = cb;
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
