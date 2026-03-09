import type { WSMessage } from "./types";
import { getAccessToken } from "./auth";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

export class AgentWebSocket {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private onMessageCallback: ((msg: WSMessage) => void) | null = null;
  private onStatusCallback: ((status: "connected" | "disconnected" | "connecting") => void) | null = null;

  connect() {
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
      this.tryReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private tryReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
      setTimeout(() => this.connect(), delay);
    }
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
    this.maxReconnectAttempts = 0;
    this.ws?.close();
    this.ws = null;
  }
}
