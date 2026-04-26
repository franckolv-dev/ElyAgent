"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/ui/Input.tsx
 * @brief      Input — reusable styled text input component
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

import { forwardRef } from "react";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className = "", ...props }, ref) => {
    return (
      <div className="space-y-1.5">
        {label && (
          <label className="block text-xs text-text-secondary uppercase tracking-wider">
            {label}
          </label>
        )}
        <input
          ref={ref}
          className={`w-full bg-bg-primary border border-border-dim rounded-md px-4 py-2.5 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:border-cyber-cyan/50 focus:shadow-[0_0_10px_#00e5ff11] transition-all ${
            error ? "border-cyber-red/50" : ""
          } ${className}`}
          {...props}
        />
        {error && <p className="text-xs text-cyber-red">{error}</p>}
      </div>
    );
  }
);

Input.displayName = "Input";
