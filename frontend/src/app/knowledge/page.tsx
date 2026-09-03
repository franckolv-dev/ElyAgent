"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/knowledge/page.tsx
 * @brief      Knowledge base UI — upload, list, delete, test search.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { motion, AnimatePresence } from "framer-motion";
import {
  BookOpen,
  UploadCloud,
  FileText,
  Trash2,
  Search,
  Loader2,
  X,
  CheckCircle2,
  AlertCircle,
  Sparkles,
} from "lucide-react";

import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { WatchedFoldersSection } from "@/components/knowledge/WatchedFoldersSection";
import { authFetch } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Keep in sync with backend `_RAG_EXTENSIONS`
const ACCEPTED_EXT = [
  ".pdf", ".txt", ".md", ".csv", ".json",
  ".doc", ".docx",
  ".xls", ".xlsx",
];
const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50 MB

type DocumentInfo = {
  document_id: string;
  title: string;
  source_file: string;
  chunk_count: number;
  created_at?: number | null;
};

type SearchResult = {
  content: string;
  title: string;
  source_file: string;
  chunk_index: number;
  score: number;
};

type Toast = { id: number; kind: "success" | "error" | "info"; text: string };

function formatDate(ts: number | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

export default function KnowledgePage() {
  const t = useTranslations("knowledge");
  const tCommon = useTranslations("common");

  // ── Documents list ────────────────────────────────────────────────────────
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // ── Upload state ──────────────────────────────────────────────────────────
  const [uploading, setUploading] = useState(false);
  const [uploadTitle, setUploadTitle] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Search test ───────────────────────────────────────────────────────────
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null);

  // ── Toasts ────────────────────────────────────────────────────────────────
  const [toasts, setToasts] = useState<Toast[]>([]);
  const showToast = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, kind, text }]);
    setTimeout(() => setToasts((prev) => prev.filter((tt) => tt.id !== id)), 4000);
  }, []);

  // ── Fetch documents ───────────────────────────────────────────────────────
  const fetchDocs = useCallback(async () => {
    setLoadingDocs(true);
    try {
      const res = await authFetch(`${API_BASE}/api/knowledge/documents`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: DocumentInfo[] = await res.json();
      setDocs(data);
    } catch {
      showToast("error", t("loadFailed"));
    } finally {
      setLoadingDocs(false);
    }
  }, [showToast, t]);

  useEffect(() => {
    fetchDocs();
  }, [fetchDocs]);

  // ── Upload ────────────────────────────────────────────────────────────────
  const doUpload = async (file: File) => {
    // Client-side validation — matches backend but avoids a pointless round-trip
    const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
    if (!ACCEPTED_EXT.includes(ext)) {
      showToast("error", t("unsupportedFormat"));
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      showToast("error", t("fileTooLarge"));
      return;
    }

    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const qs = uploadTitle.trim()
        ? `?title=${encodeURIComponent(uploadTitle.trim())}`
        : "";
      const res = await authFetch(`${API_BASE}/api/knowledge/ingest${qs}`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        throw new Error(payload?.detail ?? `HTTP ${res.status}`);
      }
      const data = await res.json();
      showToast("success", t("ingestedToast", { chunks: data.chunk_count }));
      setUploadTitle("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      fetchDocs();
    } catch (e) {
      const msg = e instanceof Error ? e.message : t("uploadFailed");
      showToast("error", `${t("uploadFailed")} — ${msg}`);
    } finally {
      setUploading(false);
    }
  };

  const onFilePicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) doUpload(f);
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) doUpload(f);
  };

  // ── Delete ────────────────────────────────────────────────────────────────
  const confirmDelete = async () => {
    if (!deletingId) return;
    try {
      const res = await authFetch(
        `${API_BASE}/api/knowledge/documents/${deletingId}`,
        { method: "DELETE" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDocs((prev) => prev.filter((d) => d.document_id !== deletingId));
      showToast("success", t("deletedToast"));
    } catch {
      showToast("error", t("uploadFailed"));
    } finally {
      setDeletingId(null);
    }
  };

  // ── Search ────────────────────────────────────────────────────────────────
  const runSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setSearchResults(null);
    try {
      const res = await authFetch(`${API_BASE}/api/knowledge/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), limit: 5 }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSearchResults(await res.json());
    } catch {
      showToast("error", t("loadFailed"));
    } finally {
      setSearching(false);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────
  const deletingDoc = deletingId ? docs.find((d) => d.document_id === deletingId) : null;

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Header />
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto p-6 space-y-6" style={{ background: "var(--bg-app)" }}>
            {/* Title */}
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-lg bg-cyber-cyan/10 border border-cyber-cyan/30 flex items-center justify-center shrink-0">
                <BookOpen className="w-5 h-5 text-cyber-cyan" />
              </div>
              <div>
                <h1 className="text-lg font-medium text-text-primary">{t("title")}</h1>
                <p className="text-sm text-text-muted">{t("subtitle")}</p>
              </div>
            </div>

            {/* Upload card */}
            <div className="bg-bg-secondary border border-border-dim rounded-lg p-5 space-y-4">
              <div className="flex items-center gap-2">
                <UploadCloud className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary uppercase tracking-wider">
                  {t("upload")}
                </h2>
              </div>

              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-text-muted mb-1">
                    {t("titleOptional")}
                  </label>
                  <input
                    type="text"
                    value={uploadTitle}
                    onChange={(e) => setUploadTitle(e.target.value)}
                    placeholder={t("titlePlaceholder")}
                    className="w-full px-3 py-2 text-sm bg-bg-tertiary border border-border-dim rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40 transition-colors"
                    disabled={uploading}
                  />
                </div>

                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOver(true);
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={onDrop}
                  onClick={() => !uploading && fileInputRef.current?.click()}
                  className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
                    dragOver
                      ? "border-cyber-cyan bg-cyber-cyan/5"
                      : uploading
                      ? "border-border-dim bg-bg-tertiary/30 cursor-wait"
                      : "border-border-dim hover:border-cyber-cyan/40 hover:bg-cyber-cyan/5"
                  }`}
                >
                  {uploading ? (
                    <div className="flex flex-col items-center gap-2 text-text-muted">
                      <Loader2 className="w-6 h-6 animate-spin text-cyber-cyan" />
                      <span className="text-sm">{t("uploading")}</span>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-2">
                      <UploadCloud className="w-8 h-8 text-text-muted" />
                      <p className="text-sm text-text-secondary">{t("dragHint")}</p>
                      <p className="text-xs text-text-muted">{t("acceptedFormats")}</p>
                    </div>
                  )}
                </div>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept={ACCEPTED_EXT.join(",")}
                  onChange={onFilePicked}
                  disabled={uploading}
                  className="hidden"
                />
              </div>
            </div>

            {/* Watched folders card — auto-index a local folder via Desktop daemon */}
            <div className="bg-bg-secondary border border-border-dim rounded-lg p-5">
              <WatchedFoldersSection />
            </div>

            {/* Documents list card */}
            <div className="bg-bg-secondary border border-border-dim rounded-lg p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-cyber-cyan" />
                  <h2 className="text-sm font-medium text-text-primary uppercase tracking-wider">
                    {t("documents")}
                  </h2>
                  <span className="text-xs text-text-muted">({docs.length})</span>
                </div>
              </div>

              {loadingDocs ? (
                <div className="py-8 flex justify-center">
                  <Loader2 className="w-5 h-5 animate-spin text-text-muted" />
                </div>
              ) : docs.length === 0 ? (
                <div className="py-8 text-center text-sm text-text-muted">{t("empty")}</div>
              ) : (
                <div className="divide-y divide-border-dim -mx-5">
                  {docs.map((d) => (
                    <div
                      key={d.document_id}
                      className="flex items-center gap-3 px-5 py-3 hover:bg-bg-tertiary/30 transition-colors"
                    >
                      <div className="w-8 h-8 rounded bg-cyber-cyan/10 flex items-center justify-center shrink-0">
                        <FileText className="w-4 h-4 text-cyber-cyan" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-text-primary truncate" title={d.title}>
                          {d.title}
                        </p>
                        <p className="text-xs text-text-muted truncate">
                          {d.source_file} · {d.chunk_count} {t("chunks")} · {formatDate(d.created_at)}
                        </p>
                      </div>
                      <button
                        onClick={() => setDeletingId(d.document_id)}
                        className="shrink-0 p-2 text-text-muted hover:text-cyber-red hover:bg-cyber-red/5 rounded transition-colors"
                        title={t("deleteButton")}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Search test card — lets admins verify RAG returns relevant chunks */}
            <div className="bg-bg-secondary border border-border-dim rounded-lg p-5 space-y-4">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-cyber-cyan" />
                <h2 className="text-sm font-medium text-text-primary uppercase tracking-wider">
                  {t("search")}
                </h2>
              </div>

              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted pointer-events-none" />
                  <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && runSearch()}
                    placeholder={t("searchPlaceholder")}
                    className="w-full pl-10 pr-3 py-2 text-sm bg-bg-tertiary border border-border-dim rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cyber-cyan/40 transition-colors"
                    disabled={searching || docs.length === 0}
                  />
                </div>
                <button
                  onClick={runSearch}
                  disabled={searching || !query.trim() || docs.length === 0}
                  className="px-4 py-2 text-sm bg-cyber-cyan text-bg-primary font-medium rounded hover:bg-cyber-cyan/80 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {searching ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    t("searchRun")
                  )}
                </button>
              </div>

              {searchResults !== null && (
                <div className="space-y-2">
                  {searchResults.length === 0 ? (
                    <p className="text-sm text-text-muted py-4 text-center">
                      {t("searchEmpty")}
                    </p>
                  ) : (
                    searchResults.map((r, i) => (
                      <div
                        key={i}
                        className="bg-bg-tertiary border border-border-dim rounded p-3 space-y-1"
                      >
                        <div className="flex items-center justify-between text-xs text-text-muted">
                          <span className="truncate">
                            {r.title} · #{r.chunk_index}
                          </span>
                          <span className="shrink-0 ml-2 font-mono">
                            {(r.score * 100).toFixed(0)}%
                          </span>
                        </div>
                        <p className="text-sm text-text-secondary leading-relaxed line-clamp-4">
                          {r.content}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </main>
        </div>
        </div>
      </div>

      {/* Delete confirmation modal */}
      <AnimatePresence>
        {deletingDoc && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
            onClick={() => setDeletingId(null)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              onClick={(e) => e.stopPropagation()}
              className="bg-bg-secondary border border-border-dim rounded-lg p-5 max-w-md shadow-xl"
            >
              <div className="flex items-start gap-3 mb-4">
                <div className="w-10 h-10 rounded-lg bg-cyber-red/10 flex items-center justify-center shrink-0">
                  <Trash2 className="w-5 h-5 text-cyber-red" />
                </div>
                <div>
                  <h3 className="text-sm font-medium text-text-primary mb-1">
                    {t("confirmDelete")}
                  </h3>
                  <p className="text-xs text-text-muted">
                    {t("confirmDeleteBody", { chunks: deletingDoc.chunk_count })}
                  </p>
                  <p className="text-xs text-text-secondary mt-2 font-medium truncate">
                    {deletingDoc.title}
                  </p>
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setDeletingId(null)}
                  className="px-3 py-1.5 text-sm text-text-secondary hover:text-text-primary bg-bg-tertiary rounded transition-colors"
                >
                  {tCommon("cancel")}
                </button>
                <button
                  onClick={confirmDelete}
                  className="px-3 py-1.5 text-sm text-white bg-cyber-red/80 hover:bg-cyber-red rounded transition-colors"
                >
                  {t("deleteButton")}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Toast stack */}
      <div className="fixed top-4 right-4 z-50 space-y-2 w-80 pointer-events-none">
        <AnimatePresence>
          {toasts.map((tt) => (
            <motion.div
              key={tt.id}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              className={`pointer-events-auto flex items-start gap-2 p-3 rounded-lg border shadow-lg ${
                tt.kind === "success"
                  ? "bg-bg-secondary border-cyber-cyan/40 text-text-primary"
                  : tt.kind === "error"
                  ? "bg-bg-secondary border-cyber-red/40 text-text-primary"
                  : "bg-bg-secondary border-border-dim text-text-primary"
              }`}
            >
              {tt.kind === "success" ? (
                <CheckCircle2 className="w-4 h-4 text-cyber-cyan shrink-0 mt-0.5" />
              ) : tt.kind === "error" ? (
                <AlertCircle className="w-4 h-4 text-cyber-red shrink-0 mt-0.5" />
              ) : (
                <Sparkles className="w-4 h-4 text-cyber-cyan shrink-0 mt-0.5" />
              )}
              <p className="text-sm flex-1">{tt.text}</p>
              <button
                onClick={() => setToasts((prev) => prev.filter((x) => x.id !== tt.id))}
                className="text-text-muted hover:text-text-primary shrink-0"
              >
                <X className="w-4 h-4" />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </AuthGuard>
  );
}
