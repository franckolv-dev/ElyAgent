"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/avatar-test/page.tsx
 * @brief      Avatar test page — 3D avatar rendering sandbox
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
import { CyberpunkAvatar } from "@/components/avatar/CyberpunkAvatar";

export default function AvatarTestPage() {
  return (
    <div style={{ background: "#060c16", minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 320, height: 420 }}>
        <CyberpunkAvatar state="speaking" className="w-full h-full" />
      </div>
    </div>
  );
}
