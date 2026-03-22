import type { Metadata } from "next";
import "@/styles/globals.css";
import { THEME_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = {
  title: "ELY Agent",
  description: "AI Agent Interface",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" suppressHydrationWarning>
      {/* Anti-FOUC: applies saved theme class before first paint */}
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-screen bg-bg-primary text-text-primary antialiased">
        <div className="fixed inset-0 bg-grid scanline pointer-events-none z-0" />
        <div className="relative z-10">{children}</div>
      </body>
    </html>
  );
}
