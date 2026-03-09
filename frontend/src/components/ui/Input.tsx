"use client";

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
          className={`w-full bg-bg-primary border border-border-dim rounded-md px-4 py-2.5 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:border-cyber-green/50 focus:shadow-[0_0_10px_#00ff4111] transition-all ${
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
