"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/arena/page.tsx
 * @brief      Arena page — blind LLM comparison with ELO ranking
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

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { api } from "@/lib/api";
import { Swords, Trophy, Timer, Send, Check, X as XIcon } from "lucide-react";

interface ArenaMatch {
  match_id: string;
  model_a: string;
  model_b: string;
  response_a: string;
  response_b: string;
  latency_a_ms: number;
  latency_b_ms: number;
}

interface EloRow {
  model: string;
  elo: number;
  wins: number;
  losses: number;
  ties: number;
  matches: number;
}

type VoteValue = "a" | "b" | "tie" | "both_bad";

export default function ArenaPage() {
  const t = useTranslations("arena");
  const [prompt, setPrompt] = useState("");
  const [match, setMatch] = useState<ArenaMatch | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reveal, setReveal] = useState(false);
  const [leaderboard, setLeaderboard] = useState<EloRow[]>([]);
  const [voted, setVoted] = useState<VoteValue | null>(null);

  const fetchLeaderboard = async () => {
    try {
      const data = await api.arenaLeaderboard();
      setLeaderboard(data.leaderboard || []);
    } catch (e: unknown) {
      console.warn("leaderboard fetch failed", e);
    }
  };

  useEffect(() => {
    fetchLeaderboard();
  }, []);

  const runMatch = async () => {
    if (!prompt.trim() || loading) return;
    setLoading(true);
    setError(null);
    setMatch(null);
    setReveal(false);
    setVoted(null);
    try {
      const result = await api.arenaCreateMatch(prompt.trim());
      setMatch(result);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : t("unknownError");
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const castVote = async (vote: VoteValue) => {
    if (!match || voted) return;
    try {
      await api.arenaVote(match.match_id, vote);
      setVoted(vote);
      setReveal(true);
      fetchLeaderboard();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : t("unknownError");
      setError(msg);
    }
  };

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden bg-bg-primary text-text-primary">
        <Sidebar />
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden">

          <main className="flex-1 overflow-y-auto p-6 space-y-6" style={{ background: "var(--bg-app)" }}>
            {/* Intro */}
            <div className="flex items-start gap-3">
              <Swords className="w-6 h-6 text-cyber-cyan shrink-0 mt-1" />
              <div>
                <h1 className="text-2xl font-bold text-cyber-cyan glow-cyan-text">
                  {t("title")}
                </h1>
                <p className="text-sm text-text-secondary mt-1 max-w-2xl">
                  {t("subtitle")}
                </p>
              </div>
            </div>

            {/* Prompt input */}
            <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
              <label className="text-xs text-text-muted uppercase tracking-wider">
                {t("promptLabel")}
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                placeholder={t("promptPlaceholder")}
                className="w-full mt-2 p-3 bg-bg-tertiary border border-border-dim rounded text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40 transition-colors resize-none"
                disabled={loading}
              />
              <div className="flex items-center justify-end mt-3">
                <button
                  onClick={runMatch}
                  disabled={!prompt.trim() || loading}
                  className="flex items-center gap-2 px-4 py-2 text-sm rounded bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/30 hover:bg-cyber-cyan/20 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                >
                  <Send className="w-4 h-4" />
                  {loading ? t("duelInProgress") : t("launchDuel")}
                </button>
              </div>
              {error && (
                <p className="text-xs text-cyber-red mt-2">{error}</p>
              )}
            </div>

            {/* Match results */}
            {match && (
              <div className="grid md:grid-cols-2 gap-4">
                {(["a", "b"] as const).map((side) => {
                  const label = side === "a" ? match.model_a : match.model_b;
                  const response =
                    side === "a" ? match.response_a : match.response_b;
                  const latency =
                    side === "a" ? match.latency_a_ms : match.latency_b_ms;
                  const isWinner = voted === side;
                  return (
                    <div
                      key={side}
                      className={`bg-bg-secondary border rounded-lg p-4 flex flex-col ${
                        isWinner
                          ? "border-cyber-cyan/60"
                          : "border-border-dim"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-xs text-text-muted uppercase tracking-wider">
                          {reveal ? label : t("modelLabel", { side: side.toUpperCase() })}
                        </span>
                        <span className="flex items-center gap-1 text-[10px] text-text-muted">
                          <Timer className="w-3 h-3" />
                          {latency} ms
                        </span>
                      </div>
                      <div className="text-sm text-text-primary whitespace-pre-wrap flex-1">
                        {response}
                      </div>
                      {!voted && (
                        <button
                          onClick={() => castVote(side)}
                          className="mt-3 py-2 text-xs rounded bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/30 hover:bg-cyber-cyan/20 transition-all"
                        >
                          {t("voteFor", { side: side.toUpperCase() })}
                        </button>
                      )}
                    </div>
                  );
                })}
                {!voted && (
                  <div className="md:col-span-2 flex gap-2 justify-center mt-2">
                    <button
                      onClick={() => castVote("tie")}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-bg-tertiary border border-border-dim text-text-secondary hover:text-text-primary transition-colors"
                    >
                      <Check className="w-3 h-3" /> {t("tie")}
                    </button>
                    <button
                      onClick={() => castVote("both_bad")}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-bg-tertiary border border-border-dim text-text-secondary hover:text-cyber-red transition-colors"
                    >
                      <XIcon className="w-3 h-3" /> {t("bothBad")}
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Leaderboard */}
            <div className="bg-bg-secondary border border-border-dim rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <Trophy className="w-5 h-5 text-cyber-cyan" />
                <h2 className="text-lg font-bold text-cyber-cyan">
                  {t("leaderboardTitle")}
                </h2>
              </div>
              {leaderboard.length === 0 ? (
                <p className="text-xs text-text-muted py-4 text-center">
                  {t("noVotes")}
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-[10px] text-text-muted uppercase tracking-wider border-b border-border-dim">
                        <th className="text-left py-2">{t("colRank")}</th>
                        <th className="text-left py-2">{t("colModel")}</th>
                        <th className="text-right py-2">{t("colElo")}</th>
                        <th className="text-right py-2">{t("colWins")}</th>
                        <th className="text-right py-2">{t("colLosses")}</th>
                        <th className="text-right py-2">{t("colTies")}</th>
                        <th className="text-right py-2">{t("colMatches")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {leaderboard.map((row, idx) => (
                        <tr
                          key={row.model}
                          className="border-b border-border-dim/50 hover:bg-bg-tertiary/50 transition-colors"
                        >
                          <td className="py-2 text-text-muted">{idx + 1}</td>
                          <td className="py-2 font-mono text-xs text-text-primary">
                            {row.model}
                          </td>
                          <td className="py-2 text-right text-cyber-cyan font-bold">
                            {row.elo.toFixed(0)}
                          </td>
                          <td className="py-2 text-right text-text-secondary">
                            {row.wins}
                          </td>
                          <td className="py-2 text-right text-text-secondary">
                            {row.losses}
                          </td>
                          <td className="py-2 text-right text-text-secondary">
                            {row.ties}
                          </td>
                          <td className="py-2 text-right text-text-muted">
                            {row.matches}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </main>
        </div>
        </div>
      </div>
    </AuthGuard>
  );
}
