"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageSquare, LayoutDashboard, Settings, Shield, LogOut, Cpu } from "lucide-react";
import { clearTokens } from "@/lib/auth";
import { useRouter } from "next/navigation";

const navItems = [
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/admin", label: "Admin", icon: Shield },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  const handleLogout = () => {
    clearTokens();
    router.push("/login");
  };

  return (
    <aside className="w-16 lg:w-56 h-screen bg-bg-secondary border-r border-border-dim flex flex-col shrink-0">
      <div className="p-4 border-b border-border-dim">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-cyber-green/10 border border-cyber-green/30 flex items-center justify-center">
            <Cpu className="w-4 h-4 text-cyber-green" />
          </div>
          <span className="hidden lg:block text-sm font-bold text-cyber-green glow-green-text tracking-wider">
            CYBER-ENTITY
          </span>
        </div>
      </div>

      <nav className="flex-1 p-2 space-y-1">
        {navItems.map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-all ${
                isActive
                  ? "bg-cyber-green/10 text-cyber-green border border-cyber-green/20"
                  : "text-text-secondary hover:text-text-primary hover:bg-bg-tertiary"
              }`}
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span className="hidden lg:block">{label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="p-2 border-t border-border-dim">
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-text-secondary hover:text-cyber-red hover:bg-cyber-red/5 transition-all w-full"
        >
          <LogOut className="w-4 h-4 shrink-0" />
          <span className="hidden lg:block">Logout</span>
        </button>
      </div>
    </aside>
  );
}
