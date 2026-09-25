"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FileText, MessageSquare, Shield, LogOut, Cpu } from "lucide-react";
import { clearStoredTokens } from "../lib/api";

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();

  const handleLogout = () => {
    clearStoredTokens();
    router.push("/login");
  };

  const navLinks = [
    { href: "/chat", label: "Intelligence Chat", icon: MessageSquare },
    { href: "/documents", label: "Knowledge Vault", icon: FileText },
    { href: "/admin", label: "Tenant Operations", icon: Shield },
  ];

  return (
    <nav className="border-b border-slate-800 bg-slate-950/80 backdrop-blur-md sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded-xl bg-blue-600/20 border border-blue-500/30 text-blue-400">
              <Cpu className="h-6 w-6" />
            </div>
            <Link href="/chat" className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-indigo-300 to-purple-400">
              DocIntel
            </Link>
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
              Enterprise v3.0
            </span>
          </div>

          <div className="flex items-center space-x-2">
            {navLinks.map((link) => {
              const Icon = link.icon;
              const isActive = pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`flex items-center space-x-2 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                    isActive
                      ? "bg-blue-600/10 text-blue-400 border border-blue-500/30"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-900"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  <span>{link.label}</span>
                </Link>
              );
            })}

            <button
              onClick={handleLogout}
              className="flex items-center space-x-1.5 px-3 py-2 rounded-lg text-sm font-medium text-red-400/80 hover:text-red-300 hover:bg-red-500/10 transition"
              title="Sign Out"
            >
              <LogOut className="h-4 w-4" />
              <span>Exit</span>
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}
