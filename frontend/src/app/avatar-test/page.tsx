"use client";
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
