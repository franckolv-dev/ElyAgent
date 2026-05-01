/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/layout.tsx
 * @brief      Root layout — global providers, fonts, and metadata
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
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
import type { Metadata, Viewport } from "next";
import "@/styles/globals.css";
import { THEME_SCRIPT } from "@/lib/theme";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getLocale } from "next-intl/server";
import { InstallPrompt } from "@/components/pwa/InstallPrompt";
import { ServiceWorkerRegister } from "@/components/pwa/ServiceWorkerRegister";

export const metadata: Metadata = {
  title: "ELY Agent",
  description: "Agent IA personnel sécurisé — chat, voix, Google Workspace, base de connaissances.",
  applicationName: "ELY",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    title: "ELY",
    statusBarStyle: "black-translucent",
  },
  icons: {
    icon: [{ url: "/icons/icon.svg", type: "image/svg+xml" }],
    apple: [{ url: "/icons/icon.svg" }],
  },
};

export const viewport: Viewport = {
  themeColor: "#00e5ff",
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    <html lang={locale} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-screen bg-bg-primary text-text-primary antialiased">
        {/* Background grid retiré (refonte mai 2026) — surfaces étagées */}
        <NextIntlClientProvider messages={messages}>
          <div className="relative z-10">{children}</div>
          <ServiceWorkerRegister />
          <InstallPrompt />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
