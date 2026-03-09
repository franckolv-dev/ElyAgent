"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Cpu, Eye, EyeOff, LogIn } from "lucide-react";
import { api } from "@/lib/api";
import { saveTokens } from "@/lib/auth";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { GlowOrb } from "@/components/ui/GlowEffect";

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"login" | "register">("login");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ username: "", email: "", password: "" });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      if (tab === "login") {
        const tokens = await api.login(form.username, form.password);
        saveTokens(tokens);
      } else {
        await api.register(form.username, form.email, form.password);
        const tokens = await api.login(form.username, form.password);
        saveTokens(tokens);
      }
      router.push("/chat");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden">
      <GlowOrb className="w-96 h-96 bg-cyber-green -top-32 -left-32" />
      <GlowOrb className="w-80 h-80 bg-cyber-cyan -bottom-20 -right-20" />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-sm"
      >
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-xl bg-cyber-green/10 border border-cyber-green/30 mb-4">
            <Cpu className="w-7 h-7 text-cyber-green" />
          </div>
          <h1 className="text-2xl font-bold text-cyber-green glow-green-text tracking-widest">
            CYBER-ENTITY
          </h1>
          <p className="text-xs text-text-muted mt-1 uppercase tracking-wider">AI Agent Interface</p>
        </div>

        {/* Card */}
        <div className="bg-bg-secondary border border-border-dim rounded-xl p-6">
          {/* Tabs */}
          <div className="flex rounded-lg bg-bg-primary p-1 mb-6">
            {(["login", "register"] as const).map((t) => (
              <button
                key={t}
                onClick={() => { setTab(t); setError(""); }}
                className={`flex-1 py-1.5 text-xs rounded-md capitalize transition-all ${
                  tab === t
                    ? "bg-cyber-green/10 text-cyber-green border border-cyber-green/20"
                    : "text-text-muted hover:text-text-secondary"
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label="Username"
              value={form.username}
              onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              placeholder="your_username"
              required
              autoComplete="username"
            />

            {tab === "register" && (
              <Input
                label="Email"
                type="email"
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                placeholder="you@example.com"
                required
              />
            )}

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
                  autoComplete={tab === "login" ? "current-password" : "new-password"}
                  className="w-full bg-bg-primary border border-border-dim rounded-md px-4 py-2.5 pr-10 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:border-cyber-green/50 focus:shadow-[0_0_10px_#00ff4111] transition-all"
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

            <Button type="submit" size="lg" className="w-full" disabled={loading}>
              {loading ? (
                <span className="flex items-center gap-2">
                  <span className="w-3.5 h-3.5 border-2 border-cyber-green/30 border-t-cyber-green rounded-full animate-spin" />
                  {tab === "login" ? "Authenticating..." : "Creating account..."}
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <LogIn className="w-3.5 h-3.5" />
                  {tab === "login" ? "Access System" : "Create Account"}
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
