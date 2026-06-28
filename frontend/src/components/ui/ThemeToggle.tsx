"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/ui/ThemeToggle.tsx
 * @brief      Theme toggle — dark / light mode switcher
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
 *   - INTERDIT : Revente comme SaaS / service managé à des tiers.
 *   - INTERDIT : Suppression des notices de copyright ou de licence.
 */

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { getTheme, toggleTheme, type Theme } from "@/lib/theme";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("dark");

  // Sync with actual DOM after hydration
  useEffect(() => {
    setTheme(getTheme());
  }, []);

  const handleToggle = () => {
    const next = toggleTheme();
    setTheme(next);
  };

  return (
    <button
      onClick={handleToggle}
      title={theme === "dark" ? "Passer en mode clair" : "Passer en mode sombre"}
      className="icon-btn"
    >
      {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}
