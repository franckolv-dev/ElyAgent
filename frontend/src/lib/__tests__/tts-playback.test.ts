import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { speakSentences, TTSPlayer, type TTSState } from "../tts";
vi.mock("../auth", () => ({ getAccessToken: () => null }));

class FakeAudio {
  static instances: FakeAudio[] = [];
  onplay: (() => void) | null = null;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  pause = vi.fn();
  play = vi.fn(async () => { this.onplay?.(); });
  constructor() { FakeAudio.instances.push(this); }
}
const response = () => ({ ok: true, blob: async () => new Blob(["audio"]) });
beforeEach(() => {
  FakeAudio.instances = [];
  vi.stubGlobal("Audio", FakeAudio);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:ely-test");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("voice playback lifecycle", () => {
  it("reports a failed second sentence instead of silently dropping it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response()).mockResolvedValueOnce({ ok: false, status: 503 }));
    const states: TTSState[] = [];
    const playback = speakSentences("Première phrase complète. Deuxième phrase complète.", { onState: s => states.push(s) });
    const result = expect(playback).rejects.toThrow("TTS 503");
    await vi.waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
    FakeAudio.instances[0].onended?.();
    await result;
    expect(states.at(-1)).toBe("error");
    expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
  });

  it("stops audio, releases URLs and aborts the prefetched request when disabled", async () => {
    const signals: AbortSignal[] = [];
    vi.stubGlobal("fetch", vi.fn((_url, opts) => {
      signals.push(opts.signal);
      return Promise.resolve(response());
    }));
    const player = new TTSPlayer(() => {});
    const playback = player.speak("Première phrase complète. Deuxième phrase complète.");
    await vi.waitFor(() => expect(FakeAudio.instances).toHaveLength(1));
    player.setEnabled(false);
    await playback;
    expect(FakeAudio.instances[0].pause).toHaveBeenCalledOnce();
    expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
    expect(signals.every(s => s.aborted)).toBe(true);
    expect(FakeAudio.instances).toHaveLength(1);
  });

  it("ignores a late old response when a new utterance has started", async () => {
    let release!: (value: ReturnType<typeof response>) => void;
    vi.stubGlobal("fetch", vi.fn()
      .mockImplementationOnce(() => new Promise(resolve => { release = resolve; }))
      .mockResolvedValue(response()));
    const states: TTSState[] = [];
    const player = new TTSPlayer(s => states.push(s));
    const old = player.speak("Ancienne réponse complète.");
    const current = player.speak("Nouvelle réponse complète.");
    await vi.waitFor(() => expect(states.at(-1)).toBe("playing"));
    release(response());
    await old;
    expect(states.at(-1)).toBe("playing");
    expect(FakeAudio.instances).toHaveLength(1);
    FakeAudio.instances[0].onended?.();
    await current;
    expect(states.at(-1)).toBe("idle");
  });
});
