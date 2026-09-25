"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Cpu, Lock, Mail, Building, User, ArrowRight, Loader2, CheckCircle2 } from "lucide-react";
import { apiRequest, setStoredTokens } from "../../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [isRegistering, setIsRegistering] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form states
  const [email, setEmail] = useState("admin@acme.com");
  const [password, setPassword] = useState("Password123!");
  const [fullName, setFullName] = useState("");
  const [orgName, setOrgName] = useState("");

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      if (isRegistering) {
        const res = await apiRequest("/api/v1/auth/register", {
          method: "POST",
          body: JSON.stringify({
            email,
            password,
            full_name: fullName,
            org_name: orgName,
          }),
        });
        setStoredTokens(res.tokens.access_token, res.tokens.refresh_token);
      } else {
        const res = await apiRequest("/api/v1/auth/login", {
          method: "POST",
          body: JSON.stringify({ email, password }),
        });
        setStoredTokens(res.tokens.access_token, res.tokens.refresh_token);
      }
      router.push("/chat");
    } catch (err: any) {
      setError(err.message || "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  const setDemoCredentials = (demoEmail: string, demoOrg: string) => {
    setEmail(demoEmail);
    setPassword("Password123!");
    setIsRegistering(false);
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col justify-center py-12 sm:px-6 lg:px-8 relative overflow-hidden">
      {/* Background glow effects */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-10 right-10 w-80 h-80 bg-purple-600/10 rounded-full blur-3xl pointer-events-none" />

      <div className="sm:mx-auto sm:w-full sm:max-w-md relative z-10">
        <div className="flex justify-center">
          <div className="p-3 rounded-2xl bg-blue-600/20 border border-blue-500/30 text-blue-400">
            <Cpu className="h-8 w-8" />
          </div>
        </div>
        <h2 className="mt-4 text-center text-3xl font-extrabold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-indigo-200 to-purple-400">
          DocIntel
        </h2>
        <p className="mt-2 text-center text-xs text-slate-400 max-w-sm mx-auto">
          Multi-Tenant Enterprise Document Intelligence Platform
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md relative z-10 px-4">
        <div className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 py-8 px-6 shadow-2xl rounded-2xl sm:px-10">
          <form className="space-y-4" onSubmit={handleAuth}>
            {isRegistering && (
              <>
                <div>
                  <label className="block text-xs font-medium text-slate-300">Full Name</label>
                  <div className="mt-1 relative rounded-xl shadow-sm">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <User className="h-4 w-4 text-slate-500" />
                    </div>
                    <input
                      type="text"
                      required
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      placeholder="Jane Doe"
                      className="block w-full pl-10 pr-3 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300">Organization Name</label>
                  <div className="mt-1 relative rounded-xl shadow-sm">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <Building className="h-4 w-4 text-slate-500" />
                    </div>
                    <input
                      type="text"
                      required
                      value={orgName}
                      onChange={(e) => setOrgName(e.target.value)}
                      placeholder="Acme Global Inc"
                      className="block w-full pl-10 pr-3 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                </div>
              </>
            )}

            <div>
              <label className="block text-xs font-medium text-slate-300">Corporate Email</label>
              <div className="mt-1 relative rounded-xl shadow-sm">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Mail className="h-4 w-4 text-slate-500" />
                </div>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@acme.com"
                  className="block w-full pl-10 pr-3 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300">Password</label>
              <div className="mt-1 relative rounded-xl shadow-sm">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Lock className="h-4 w-4 text-slate-500" />
                </div>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="block w-full pl-10 pr-3 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            {error && (
              <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-400">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center py-2.5 px-4 rounded-xl shadow-sm text-sm font-semibold text-white bg-blue-600 hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  <span>{isRegistering ? "Create Organization" : "Sign In to Platform"}</span>
                  <ArrowRight className="ml-2 h-4 w-4" />
                </>
              )}
            </button>
          </form>

          <div className="mt-4 text-center">
            <button
              onClick={() => setIsRegistering(!isRegistering)}
              className="text-xs text-slate-400 hover:text-blue-400 transition"
            >
              {isRegistering
                ? "Already have an account? Sign In"
                : "New organization? Create tenant account"}
            </button>
          </div>

          {/* Quick Demo Logins for Reviewers / Interviewers */}
          <div className="mt-6 pt-4 border-t border-slate-800/80">
            <p className="text-[11px] font-semibold text-slate-400 mb-2">
              ⚡ Pre-seeded Demo Tenancy Accounts:
            </p>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <button
                type="button"
                onClick={() => setDemoCredentials("admin@acme.com", "Acme Corp")}
                className="p-2 rounded-lg bg-slate-950 border border-slate-800 hover:border-blue-500/50 text-left transition"
              >
                <div className="font-semibold text-slate-200">Tenant A (Acme)</div>
                <div className="text-[10px] text-slate-400">admin@acme.com</div>
              </button>
              <button
                type="button"
                onClick={() => setDemoCredentials("admin@zephyr.com", "Zephyr")}
                className="p-2 rounded-lg bg-slate-950 border border-slate-800 hover:border-purple-500/50 text-left transition"
              >
                <div className="font-semibold text-slate-200">Tenant B (Zephyr)</div>
                <div className="text-[10px] text-slate-400">admin@zephyr.com</div>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
