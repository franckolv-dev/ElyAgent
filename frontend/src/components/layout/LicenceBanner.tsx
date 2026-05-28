"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/LicenceBanner.tsx
 * @brief      Global licence banner — no-op since the Elastic v2 pivot
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
 * @license    Elastic License 2.0
 *             https://www.elastic.co/licensing/elastic-license
 *
 * Pre-2026-05-28 this component showed blocking banners when the
 * licence was missing or the user count hit the cap. After Franck's
 * licence pivot of 22 May 2026 (PolyForm + paid tiers → single Elastic
 * License v2 with no activation, no tiers, no user cap), none of those
 * conditions exist anymore.
 *
 * Kept as a no-op rather than fully deleted so the import sites in the
 * page layouts don't need to change. If a future need arises (e.g. an
 * upgrade nag for outdated desktop daemons), the scaffolding is here.
 */
export function LicenceBanner() {
  return null;
}
