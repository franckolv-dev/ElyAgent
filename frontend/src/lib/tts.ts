/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/tts.ts
 * @brief      TTS client — text-to-speech streaming helpers
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 */
import { getAccessToken } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type TTSState = "idle" | "loading" | "playing" | "error";

type StateCallback = (state: TTSState) => void;

export class TTSPlayer {
  private audio: HTMLAudioElement | null = null;
  private blobUrl: string | null = null;
  private onStateChange: StateCallback;
  private enabled: boolean = true;

  constructor(onStateChange: StateCallback) {
    this.onStateChange = onStateChange;
  }

  setEnabled(enabled: boolean) {
    this.enabled = enabled;
    if (!enabled) this.stop();
  }

  async speak(text: string, voice?: string): Promise<void> {
    if (!this.enabled || !text.trim()) return;

    this.stop();
    this.onStateChange("loading");

    try {
      // Use the shared helper so the correct localStorage key is always used
      const token = getAccessToken();
      const res = await fetch(`${API_URL}/tts/speak`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ text, voice }),
      });

      if (!res.ok) throw new Error(`TTS ${res.status}`);

      const blob = await res.blob();
      this.blobUrl = URL.createObjectURL(blob);

      this.audio = new Audio(this.blobUrl);
      this.audio.onplay = () => this.onStateChange("playing");
      this.audio.onended = () => this._cleanup("idle");
      this.audio.onerror = () => this._cleanup("idle");

      await this.audio.play();
    } catch {
      this.onStateChange("idle");
    }
  }

  stop() {
    if (this.audio) {
      this.audio.pause();
      this.audio = null;
    }
    this._cleanup("idle");
  }

  private _cleanup(nextState: TTSState) {
    if (this.blobUrl) {
      URL.revokeObjectURL(this.blobUrl);
      this.blobUrl = null;
    }
    this.onStateChange(nextState);
  }
}
