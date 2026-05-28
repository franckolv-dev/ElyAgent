/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/i18n/request.ts
 * @brief      i18n request config — next-intl locale resolution
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *            https://www.elastic.co/licensing/elastic-license
 * @version    1.1.0
 * @link       https://github.com/franckolv-dev/PhysicalAgent
 *
 * RÉSUMÉ DES CONDITIONS :
 *   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
 *   - AUTORISÉ : Modification et redistribution avec attribution.
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
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
