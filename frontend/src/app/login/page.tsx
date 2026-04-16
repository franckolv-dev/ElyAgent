"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/login/page.tsx
 * @brief      Login page — user authentication form
 *
 * @author     Franck OLLIVIER <franck.olv@gmail.com>
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

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Eye, EyeOff, LogIn } from "lucide-react";
import { api } from "@/lib/api";
import { saveTokens } from "@/lib/auth";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { GlowOrb } from "@/components/ui/GlowEffect";
import { CyberpunkAvatar } from "@/components/avatar/CyberpunkAvatar";

export default function LoginPage() {
  const router = useRouter();
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ username: "", password: "" });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const tokens = await api.login(form.username, form.password);
      saveTokens(tokens);
      router.push("/chat");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden">
      <GlowOrb className="w-96 h-96 bg-cyber-cyan -top-32 -left-32" />
      <GlowOrb className="w-80 h-80 bg-cyber-cyan -bottom-20 -right-20" />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-sm"
      >
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="w-28 h-36 mx-auto mb-4 rounded-xl overflow-hidden border border-cyber-cyan/25 bg-[#060c16]">
            <CyberpunkAvatar state="idle" minimal className="w-full h-full" />
          </div>
          <h1 className="text-2xl font-bold text-cyber-cyan glow-cyan-text tracking-widest">
            ELY
          </h1>
          <p className="text-xs text-text-muted mt-1 uppercase tracking-wider">
            Secure Assistant
          </p>
        </div>

        {/* Card */}
        <div className="bg-bg-secondary border border-border-dim rounded-xl p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label="Username"
              value={form.username}
              onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              placeholder="your_username"
              required
              autoComplete="username"
            />

            <div className="space-y-1.5">
              <label className="block text-xs text-text-secondary uppercase tracking-wider">
                Password
              </label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={form.password}
                  onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                  placeholder="••••••••"
                  required
                  autoComplete="current-password"
                  className="w-full bg-bg-primary border border-border-dim rounded-md px-4 py-2.5 pr-10 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:border-cyber-cyan/50 focus:shadow-[0_0_10px_rgba(0,229,255,0.1)] transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {error && (
              <p className="text-xs text-cyber-red bg-cyber-red/5 border border-cyber-red/20 rounded-md px-3 py-2">
                {error}
              </p>
            )}

            <Button
              type="submit"
              size="lg"
              className="w-full !bg-cyber-cyan/10 !text-cyber-cyan !border-cyber-cyan/30 hover:!bg-cyber-cyan/20"
              disabled={loading}
            >
              {loading ? (
                <span className="flex items-center gap-2">
                  <span className="w-3.5 h-3.5 border-2 border-cyber-cyan/30 border-t-cyber-cyan rounded-full animate-spin" />
                  Authenticating...
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <LogIn className="w-3.5 h-3.5" />
                  Access System
                </span>
              )}
            </Button>
          </form>
        </div>

        <p className="text-center text-[10px] text-text-muted mt-4 uppercase tracking-widest">
          Authorized Access Only
        </p>
      </motion.div>
    </div>
  );
}
