import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    // BACKEND_INTERNAL_URL  = URL joignable depuis le container Next.js
    //   → Docker : http://backend:8000  (nom du service Docker)
    //   → Dev local sans Docker : http://localhost:8000
    // NEXT_PUBLIC_API_URL   = URL joignable depuis le navigateur (client-side WS)
    const backendUrl =
      process.env.BACKEND_INTERNAL_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default withNextIntl(nextConfig);
