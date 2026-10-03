"use client";

import { useEffect, useState } from "react";
import Navbar from "../../../components/Navbar";
import { apiRequest } from "../../../lib/api";
import { Shield, Zap, DollarSign, Users, Database, ArrowUpRight, UserPlus, CheckCircle2, UserX } from "lucide-react";

interface UsageData {
  org_id: string;
  org_name: string;
  monthly_token_budget: number;
  tokens_used_this_month: number;
  budget_utilized_percent: number;
  total_cost_usd: number;
  documents_count: number;
  chunks_count: number;
  conversations_count: number;
  messages_count: number;
  top_users: Array<{ email: string; full_name: string; tokens: number }>;
}

interface Member {
  id: string;
  email: string;
  full_name: string;
  role: string;
  created_at: string;
}

export default function AdminPage() {
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);

  // Invite modal state
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [invitePassword, setInvitePassword] = useState("TempPassword123!");
  const [lastInvitedCreds, setLastInvitedCreds] = useState<{ email: string; pass: string } | null>(null);
  const [inviteSuccess, setInviteSuccess] = useState(false);

  // Current authenticated user & action states
  const [currentUser, setCurrentUser] = useState<{ id: string; email: string; role: string } | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    loadAdminData();
  }, []);

  const loadAdminData = async () => {
    try {
      const [uData, mData, meData] = await Promise.all([
        apiRequest<UsageData>("/api/v1/admin/usage"),
        apiRequest<Member[]>("/api/v1/admin/members"),
        apiRequest<{ id: string; email: string; role: string }>("/api/v1/auth/me").catch(() => null),
      ]);
      setUsage(uData);
      setMembers(mData || []);
      if (meData) setCurrentUser(meData);
    } catch (e) {
      console.error("Failed to load admin data", e);
    } finally {
      setLoading(false);
    }
  };

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const passToUse = invitePassword || "TempPassword123!";
      await apiRequest("/api/v1/admin/members", {
        method: "POST",
        body: JSON.stringify({
          email: inviteEmail,
          full_name: inviteName,
          role: inviteRole,
          password: passToUse,
        }),
      });
      setLastInvitedCreds({ email: inviteEmail, pass: passToUse });
      setInviteSuccess(true);
      setInviteEmail("");
      setInviteName("");
      setInvitePassword("TempPassword123!");
      loadAdminData();
      setTimeout(() => setInviteSuccess(false), 12000);
    } catch (err: any) {
      alert(`Invite failed: ${err.message}`);
    }
  };

  const handleDeleteMember = async (memberId: string, memberName: string) => {
    const confirmed = window.confirm(
      `Are you sure you want to remove "${memberName}" from the organization? They will immediately lose access.`
    );
    if (!confirmed) return;

    setDeletingId(memberId);
    try {
      await apiRequest(`/api/v1/admin/members/${memberId}`, {
        method: "DELETE",
      });
      setMembers((prev) => prev.filter((m) => m.id !== memberId));
    } catch (err: any) {
      alert(`Failed to remove member: ${err.message}`);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      <Navbar />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Tenant Operations & Governance</h1>
          <p className="text-xs text-slate-400 mt-1">
            Real-time token budgeting, cost auditing, and role-based access for{" "}
            <span className="text-blue-400 font-semibold">{usage?.org_name || "Your Organization"}</span>
          </p>
        </div>

        {/* Top Metric Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-lg">
            <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
              <span>Token Budget Quota</span>
              <Zap className="h-4 w-4 text-amber-400" />
            </div>
            <div className="mt-3 text-2xl font-bold text-slate-100">
              {usage?.tokens_used_this_month.toLocaleString() || "0"}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              of {usage?.monthly_token_budget.toLocaleString() || "1,000,000"} tokens
            </div>
            {/* Progress bar */}
            <div className="mt-3 w-full bg-slate-800 h-2 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  (usage?.budget_utilized_percent || 0) > 85
                    ? "bg-red-500"
                    : "bg-blue-500"
                }`}
                style={{ width: `${Math.min(100, usage?.budget_utilized_percent || 0)}%` }}
              />
            </div>
            <div className="mt-1.5 text-right text-[11px] text-slate-400">
              {usage?.budget_utilized_percent || 0}% utilized
            </div>
          </div>

          <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-lg">
            <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
              <span>Audited LLM Spend</span>
              <DollarSign className="h-4 w-4 text-emerald-400" />
            </div>
            <div className="mt-3 text-2xl font-bold text-slate-100">
              ${usage?.total_cost_usd.toFixed(4) || "0.0000"}
            </div>
            <div className="mt-1 text-xs text-slate-500">Tracked via LiteLLM router</div>
          </div>

          <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-lg">
            <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
              <span>Document Vector Chunks</span>
              <Database className="h-4 w-4 text-blue-400" />
            </div>
            <div className="mt-3 text-2xl font-bold text-slate-100">
              {usage?.chunks_count.toLocaleString() || "0"}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              Across {usage?.documents_count || 0} indexed files
            </div>
          </div>

          <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 shadow-lg">
            <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
              <span>Organization Members</span>
              <Users className="h-4 w-4 text-purple-400" />
            </div>
            <div className="mt-3 text-2xl font-bold text-slate-100">
              {members.length}
            </div>
            <div className="mt-1 text-xs text-slate-500">Active enterprise users</div>
          </div>
        </div>

        {/* Member Management & Invitation */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-200">Organization Members & Roles</h2>
              <span className="text-xs text-slate-500">Tenant Scoped</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm text-slate-300">
                <thead className="bg-slate-950/50 text-xs uppercase text-slate-500 border-b border-slate-800">
                  <tr>
                    <th className="px-6 py-3">Member</th>
                    <th className="px-6 py-3">Role</th>
                    <th className="px-6 py-3">Joined Date</th>
                    <th className="px-6 py-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {members.map((m) => (
                    <tr key={m.id} className="hover:bg-slate-800/30 transition">
                      <td className="px-6 py-3.5">
                        <div className="font-medium text-slate-200">{m.full_name}</div>
                        <div className="text-xs text-slate-500">{m.email}</div>
                      </td>
                      <td className="px-6 py-3.5">
                        <span
                          className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase ${
                            m.role === "owner"
                              ? "bg-purple-500/20 text-purple-300 border border-purple-500/30"
                              : m.role === "admin"
                              ? "bg-blue-500/20 text-blue-300 border border-blue-500/30"
                              : "bg-slate-800 text-slate-400 border border-slate-700"
                          }`}
                        >
                          {m.role}
                        </span>
                      </td>
                      <td className="px-6 py-3.5 text-xs text-slate-400">
                        {new Date(m.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-6 py-3.5 text-right">
                        {m.id === currentUser?.id ? (
                          <span className="text-xs text-slate-500 italic">You</span>
                        ) : m.role === "owner" ? (
                          <span className="text-xs text-purple-400/80 font-medium">Owner (Protected)</span>
                        ) : currentUser?.role === "admin" && m.role === "admin" ? (
                          <span className="text-xs text-slate-500 italic">Admin (Protected)</span>
                        ) : (
                          <button
                            onClick={() => handleDeleteMember(m.id, m.full_name || m.email)}
                            disabled={deletingId === m.id}
                            className="inline-flex items-center space-x-1.5 px-2.5 py-1 text-xs font-medium text-rose-400 hover:text-rose-200 bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/20 hover:border-rose-500/40 rounded-lg transition disabled:opacity-50"
                            title="Remove member from company"
                          >
                            <UserX className="h-3.5 w-3.5" />
                            <span>{deletingId === m.id ? "Removing..." : "Remove"}</span>
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Member Invite Form */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
            <div className="flex items-center space-x-2 pb-4 border-b border-slate-800">
              <UserPlus className="h-5 w-5 text-blue-400" />
              <h2 className="text-sm font-semibold text-slate-200">Invite Team Member</h2>
            </div>

            <form onSubmit={handleInvite} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-400">Full Name</label>
                <input
                  type="text"
                  required
                  value={inviteName}
                  onChange={(e) => setInviteName(e.target.value)}
                  placeholder="Alex Mercer"
                  className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400">Email Address</label>
                <input
                  type="email"
                  required
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="alex@company.com"
                  className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400">Role</label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="member">Member</option>
                  <option value="admin">Admin</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400">Temporary Password</label>
                <input
                  type="text"
                  required
                  value={invitePassword}
                  onChange={(e) => setInvitePassword(e.target.value)}
                  placeholder="TempPassword123!"
                  className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                />
                <span className="text-[10px] text-slate-500 mt-1 block">
                  The invited member will use this password to log in.
                </span>
              </div>

              {inviteSuccess && lastInvitedCreds && (
                <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400 space-y-1.5">
                  <div className="flex items-center space-x-2 font-medium">
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                    <span>Member invited successfully!</span>
                  </div>
                  <div className="text-[11px] text-slate-300 bg-slate-950/80 p-2.5 rounded-lg font-mono border border-slate-800 space-y-1">
                    <div>Email: <strong className="text-white select-all">{lastInvitedCreds.email}</strong></div>
                    <div>Password: <strong className="text-emerald-400 select-all">{lastInvitedCreds.pass}</strong></div>
                  </div>
                  <div className="text-[10px] text-slate-400">
                    Log out and log in with these credentials to access this organization.
                  </div>
                </div>
              )}

              <button
                type="submit"
                className="w-full py-2.5 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition shadow-sm"
              >
                Send Invite
              </button>
            </form>
          </div>
        </div>
      </main>
    </div>
  );
}
