/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/i18n/request.ts
 * @brief      i18n request config — next-intl locale resolution
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
import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";

type Locale = "en" | "fr";

async function detectLocale(): Promise<Locale> {
  const cookieStore = await cookies();
  const localeCookie = cookieStore.get("NEXT_LOCALE")?.value;
  if (localeCookie === "fr" || localeCookie === "en") return localeCookie;

  const headersList = await headers();
  const acceptLang = (headersList.get("accept-language") || "").toLowerCase();
  if (acceptLang.startsWith("fr")) return "fr";
  return "en";
}

export default getRequestConfig(async () => {
  const locale = await detectLocale();
  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
