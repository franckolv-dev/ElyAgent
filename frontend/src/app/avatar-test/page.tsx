"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/app/avatar-test/page.tsx
 * @brief      Avatar test page — 3D avatar rendering sandbox
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
