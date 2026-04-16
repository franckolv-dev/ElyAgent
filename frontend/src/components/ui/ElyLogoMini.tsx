"use client";
/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/ui/ElyLogoMini.tsx
 * @brief      Eli logo mini — compact SVG brand logo
 *
 * @author     Franck OLLIVIER <franck.olv@gmail.com>
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

import { useEffect, useRef } from "react";

// Lightweight 2D canvas mini-face logo for the login screen
// Mirrors the aesthetics of the 3D avatar without loading Three.js / GLB
export function ElyLogoMini({ size = 56, color = "#00e5ff" }: { size?: number; color?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cvs = ref.current;
    if (!cvs) return;
    const ctx = cvs.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    cvs.width  = size * dpr;
    cvs.height = size * dpr;
    cvs.style.width  = `${size}px`;
    cvs.style.height = `${size}px`;
    ctx.scale(dpr, dpr);

    let raf = 0;
    const loop = (ts: number) => {
      const t = ts / 1000;
      const S = size;
      const cx = S / 2, cy = S / 2 - 2;

      ctx.clearRect(0, 0, S, S);

      // ── Face oval ──
      const rx = S * 0.36, ry = S * 0.44;

      // Clip to face oval for grid lines
      ctx.save();
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
      ctx.clip();

      // Horizontal grid lines
      const hLines = 7;
      ctx.strokeStyle = color;
      ctx.lineWidth = 0.5;
      ctx.globalAlpha = 0.35;
      for (let i = 0; i <= hLines; i++) {
        const yy = cy - ry + (i / hLines) * ry * 2;
        // Width of ellipse at this y
        const dy = yy - cy;
        const hw = rx * Math.sqrt(Math.max(0, 1 - (dy / ry) ** 2));
        ctx.beginPath();
        ctx.moveTo(cx - hw, yy);
        ctx.lineTo(cx + hw, yy);
        ctx.stroke();
      }

      // Vertical meridian lines
      const vLines = 5;
      for (let i = 0; i <= vLines; i++) {
        const angle = (i / vLines) * Math.PI; // 0 → π  (left to right)
        const xx = cx + rx * Math.cos(angle);
        ctx.beginPath();
        ctx.moveTo(cx, cy - ry);
        // Simple straight approximation: just draw from top to bottom at this x offset
        ctx.moveTo(xx, cy - ry * Math.sin(Math.acos((xx - cx) / rx)));
        ctx.lineTo(xx, cy + ry * Math.sin(Math.acos(Math.abs((xx - cx) / rx))));
        ctx.stroke();
      }
      ctx.restore();

      // ── Face oval outline ──
      ctx.shadowBlur = 8 + Math.sin(t * 1.2) * 2;
      ctx.shadowColor = color;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.2;
      ctx.globalAlpha = 0.9;
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
      ctx.stroke();

      // ── Eyes ──
      const eyeY  = cy - ry * 0.18;
      const eyeRx = rx * 0.28;
      const eyeRy = ry * 0.10 * (Math.sin(t * 0.3) > 0.96 ? 0.1 : 1); // blink
      [-1, 1].forEach((side) => {
        const ex = cx + side * rx * 0.42;
        ctx.shadowBlur = 6;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.0;
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.ellipse(ex, eyeY, eyeRx, Math.max(0.5, eyeRy), 0, 0, Math.PI * 2);
        ctx.stroke();
      });

      // ── Scan line ──
      const scanY = cy - ry + ((t * 0.5) % 1) * ry * 2;
      ctx.shadowBlur = 4;
      ctx.strokeStyle = color;
      ctx.lineWidth = 0.8;
      ctx.globalAlpha = 0.5;
      ctx.save();
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
      ctx.clip();
      ctx.beginPath();
      ctx.moveTo(cx - rx, scanY);
      ctx.lineTo(cx + rx, scanY);
      ctx.stroke();
      ctx.restore();

      ctx.globalAlpha = 1;
      ctx.shadowBlur = 0;

      raf = requestAnimationFrame(loop);
    };

    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [size, color]);

  return <canvas ref={ref} style={{ display: "block" }} />;
}
