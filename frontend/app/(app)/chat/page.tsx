"use client";

import { useState, useEffect } from "react";
import Navbar from "../../../components/Navbar";
import ChatStream from "../../../components/ChatStream";
import { apiRequest } from "../../../lib/api";
import { MessageSquare, Plus, Trash2, Loader2, Sparkles } from "lucide-react";

interface ConversationItem {
  id: string;
  title: string;
  updated_at: string;
}

export default function ChatPage() {
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [messages, setMessages] = useState<any[]>([]);

  useEffect(() => {
    loadConversations();
  }, []);

  const loadConversations = async () => {
    try {
      const data = await apiRequest<ConversationItem[]>("/api/v1/chat/conversations");
      setConversations(data || []);
      if (data && data.length > 0 && !activeConvId) {
        selectConversation(data[0].id);
      } else if (!data || data.length === 0) {
        // Auto-create initial conversation if empty
        createNewConversation();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const selectConversation = async (convId: string) => {
    setActiveConvId(convId);
    try {
      const fullConv = await apiRequest(`/api/v1/chat/conversations/${convId}`);
      setMessages(fullConv.messages || []);
    } catch (e) {
      console.error(e);
    }
  };

  const createNewConversation = async () => {
    try {
      const newConv = await apiRequest("/api/v1/chat/conversations", {
        method: "POST",
        body: JSON.stringify({ title: `Analysis Session ${conversations.length + 1}` }),
      });
      setConversations((prev) => [newConv, ...prev]);
      setActiveConvId(newConv.id);
      setMessages([]);
    } catch (e) {
      console.error(e);
    }
  };

  const deleteConversation = async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await apiRequest(`/api/v1/chat/conversations/${convId}`, { method: "DELETE" });
      const remaining = conversations.filter((c) => c.id !== convId);
      setConversations(remaining);
      if (activeConvId === convId) {
        if (remaining.length > 0) {
          selectConversation(remaining[0].id);
        } else {
          createNewConversation();
        }
      }
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  return (
    <div className="h-screen bg-slate-950 flex flex-col overflow-hidden">
      <Navbar />

      <div className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 flex gap-6 overflow-hidden">
        {/* Conversations Sidebar */}
        <aside className="w-72 bg-slate-900 border border-slate-800 rounded-2xl flex flex-col overflow-hidden shrink-0 shadow-xl">
          <div className="p-4 border-b border-slate-800">
            <button
              onClick={createNewConversation}
              className="w-full py-2.5 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center justify-center space-x-2 transition shadow-sm"
            >
              <Plus className="h-4 w-4" />
              <span>New Intelligence Session</span>
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-1">
            {loading ? (
              <div className="p-4 text-center text-xs text-slate-500">Loading sessions...</div>
            ) : conversations.length === 0 ? (
              <div className="p-4 text-center text-xs text-slate-500">No active sessions</div>
            ) : (
              conversations.map((c) => (
                <div
                  key={c.id}
                  onClick={() => selectConversation(c.id)}
                  className={`group flex items-center justify-between p-3 rounded-xl cursor-pointer text-xs transition ${
                    activeConvId === c.id
                      ? "bg-blue-600/15 text-blue-300 border border-blue-500/30"
                      : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
                  }`}
                >
                  <div className="flex items-center space-x-2 truncate">
                    <MessageSquare className="h-4 w-4 shrink-0 text-slate-400" />
                    <span className="truncate font-medium">{c.title}</span>
                  </div>
                  <button
                    onClick={(e) => deleteConversation(c.id, e)}
                    className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-400 rounded transition"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))
            )}
          </div>

          <div className="p-3 border-t border-slate-800/80 text-[11px] text-slate-500 text-center">
            Hybrid BM25 + pgvector + bge-reranker
          </div>
        </aside>

        {/* Main Chat Streaming View */}
        <main className="flex-1 h-full overflow-hidden">
          {activeConvId ? (
            <ChatStream conversationId={activeConvId} initialMessages={messages} />
          ) : (
            <div className="flex items-center justify-center h-full bg-slate-900/40 rounded-2xl border border-slate-800 text-slate-500 text-sm">
              <Loader2 className="h-6 w-6 animate-spin mr-2" />
              Initializing Chat Context...
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
