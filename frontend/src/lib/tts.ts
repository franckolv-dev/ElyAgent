/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/lib/tts.ts
 * @brief      TTS client — la voix d'Ely, phrase par phrase
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 * @version    1.2.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 */
//
// 08/09/2026 — la voix locale XTTS (voix clonée) synthétise plus vite que le
// temps réel, mais seulement phrase par phrase : une réponse de trois phrases
// demandée d'un bloc attend douze secondes, la première phrase seule une
// seconde et demie. Le client découpe donc le texte, demande chaque phrase,
// et charge la suivante pendant que l'une se joue. Le découpage suit la même
// règle que le service (voice/xtts/serveur.py : découper_en_phrases).

import { getAccessToken } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type TTSState = "idle" | "loading" | "playing" | "error";
type StateCallback = (state: TTSState) => void;

// Une frontière : ponctuation forte suivie d'une espace. « M. Dupont » et
// « 12.50 » n'en sont pas (abréviation d'une ou deux lettres, point collé à
// un chiffre).
const FRONTIERE = /(?<![A-ZÀ-Ý]\.)(?<![A-ZÀ-Ý][a-zà-ÿ]\.)(?<=[.!?…])\s+(?=\S)/u;
const MIETTE = 12;
const LONGUEUR_MAX = 300;

/** Les phrases à demander une par une : miettes recollées, longues coupées. */
export function splitSentences(text: string): string[] {
  const plat = (text ?? "").split(/\s+/).filter(Boolean).join(" ");
  if (!plat) return [];
  const brutes = plat.split(FRONTIERE).map((m) => m.trim()).filter(Boolean);

  const collees: string[] = [];
  let enCours = "";
  for (const b of brutes) {
    enCours = enCours ? `${enCours} ${b}` : b;
    if (enCours.length >= MIETTE) {
      collees.push(enCours);
      enCours = "";
    }
  }
  if (enCours) {
    if (collees.length) collees[collees.length - 1] = `${collees[collees.length - 1]} ${enCours}`;
    else collees.push(enCours);
  }

  const bornees: string[] = [];
  for (const c of collees) bornees.push(...couperLongue(c));
  return bornees;
}

function couperLongue(phrase: string): string[] {
  if (phrase.length <= LONGUEUR_MAX) return [phrase];
  const morceaux: string[] = [];
  let reste = phrase;
  while (reste.length > LONGUEUR_MAX) {
    const fenetre = reste.slice(0, LONGUEUR_MAX);
    let coupe = Math.max(fenetre.lastIndexOf(", "), fenetre.lastIndexOf("; "), fenetre.lastIndexOf(" : "));
    if (coupe < LONGUEUR_MAX / 3) coupe = fenetre.lastIndexOf(" ");
    if (coupe <= 0) coupe = LONGUEUR_MAX;
    morceaux.push(reste.slice(0, coupe).replace(/[ ,;:]+$/, ""));
    reste = reste.slice(coupe).replace(/^[ ,;:]+/, "");
  }
  if (reste) morceaux.push(reste);
  return morceaux;
}

async function fetchAudio(sentence: string, voice: string | undefined, signal: AbortSignal): Promise<Blob> {
  const token = getAccessToken();
  const res = await fetch(`${API_URL}/tts/speak`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ text: sentence, ...(voice ? { voice } : {}) }),
    signal,
  });
  if (!res.ok) throw new Error(`TTS ${res.status}`);
  return res.blob();
}

export interface SpeakOptions {
  voice?: string;
  signal?: AbortSignal;
  /** Appelé à chaque phrase avec l'élément audio, pour pouvoir l'arrêter. */
  onAudio?: (audio: HTMLAudioElement) => void;
  onState?: StateCallback;
}

/**
 * Lit `text` phrase par phrase. La phrase suivante se charge (prefetch)
 * pendant que la courante se joue ; `signal` interrompt tout.
 * Se résout quand tout est joué, ou interrompu.
 */
export async function speakSentences(text: string, opts: SpeakOptions = {}): Promise<void> {
  const phrases = splitSentences(text);
  if (!phrases.length) return;
  const signal = opts.signal ?? new AbortController().signal;
  opts.onState?.("loading");

  // Une longueur d'avance : le fetch de la suivante part avant la lecture.
  let suivante: Promise<Blob> | null = fetchAudio(phrases[0], opts.voice, signal);
  for (let i = 0; i < phrases.length; i++) {
    if (signal.aborted) break;
    const courante = suivante;
    suivante = i + 1 < phrases.length ? fetchAudio(phrases[i + 1], opts.voice, signal) : null;
    // Un prefetch qui échoue ne doit pas rester une promesse orpheline.
    suivante?.catch(() => undefined);
    let blob: Blob;
    try {
      blob = await courante!;
    } catch {
      if (signal.aborted) break;
      continue; // la phrase suivante peut réussir
    }
    if (signal.aborted) break;
    await jouer(blob, signal, opts);
  }
  opts.onState?.("idle");
}

function jouer(blob: Blob, signal: AbortSignal, opts: SpeakOptions): Promise<void> {
  return new Promise<void>((resolve) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    const fin = () => {
      URL.revokeObjectURL(url);
      signal.removeEventListener("abort", stop);
      resolve();
    };
    const stop = () => {
      audio.pause();
      fin();
    };
    signal.addEventListener("abort", stop, { once: true });
    audio.onplay = () => opts.onState?.("playing");
    audio.onended = fin;
    audio.onerror = fin;
    opts.onAudio?.(audio);
    audio.play().catch(fin);
  });
}

export class TTSPlayer {
  private controller: AbortController | null = null;
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
    this.controller = new AbortController();
    try {
      await speakSentences(text, {
        voice,
        signal: this.controller.signal,
        onState: (s) => this.onStateChange(s),
      });
    } catch {
      this.onStateChange("idle");
    }
  }

  stop() {
    if (this.controller) {
      this.controller.abort();
      this.controller = null;
    }
    this.onStateChange("idle");
  }
}
