import type { Metadata } from "next";
import "@/styles/globals.css";
import { THEME_SCRIPT } from "@/lib/theme";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getLocale } from "next-intl/server";

export const metadata: Metadata = {
  title: "ELY Agent",
  description: "AI Agent Interface",
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
        <div className="fixed inset-0 bg-grid scanline pointer-events-none z-0" />
        <NextIntlClientProvider messages={messages}>
          <div className="relative z-10">{children}</div>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
