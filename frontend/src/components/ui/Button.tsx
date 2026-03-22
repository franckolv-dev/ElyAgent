"use client";

import { forwardRef } from "react";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", className = "", children, ...props }, ref) => {
    const base = "inline-flex items-center justify-center font-medium rounded-md transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer";

    const variants = {
      primary: "bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/30 hover:bg-cyber-cyan/20 hover:border-cyber-cyan/50 hover:shadow-[0_0_15px_#00e5ff22]",
      secondary: "bg-bg-tertiary text-text-primary border border-border-dim hover:bg-bg-tertiary/80 hover:border-text-muted",
      ghost: "text-text-secondary hover:text-text-primary hover:bg-bg-tertiary",
      danger: "bg-cyber-red/10 text-cyber-red border border-cyber-red/30 hover:bg-cyber-red/20",
    };

    const sizes = {
      sm: "px-3 py-1.5 text-xs",
      md: "px-4 py-2 text-sm",
      lg: "px-6 py-3 text-base",
    };

    return (
      <button ref={ref} className={`${base} ${variants[variant]} ${sizes[size]} ${className}`} {...props}>
        {children}
      </button>
    );
  }
);

Button.displayName = "Button";
