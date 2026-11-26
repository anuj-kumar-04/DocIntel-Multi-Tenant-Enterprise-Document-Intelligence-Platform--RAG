"use client";

import { useState, useEffect } from "react";
import Navbar from "../../../components/Navbar";
import ChatStream, { ScopedDocumentOption } from "../../../components/ChatStream";
import { apiRequest } from "../../../lib/api";
import { MessageSquare, Plus, Trash2, Loader2, Lock } from "lucide-react";

interface ConversationItem {
  id: string;
  title: string;
  document_ids?: string[] | null;
  updated_at: string;
}

export default function ChatPage() {
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [documents, setDocuments] = useState<ScopedDocumentOption[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [messages, setMessages] = useState<any[]>([]);

  useEffect(() => {
    initializeChat();
  }, []);

  const initializeChat = async () => {
    try {
      const requestedDocId =
        typeof window !== "undefined"
          ? new URLSearchParams(window.location.search).get("doc")
          : null;

      const [convData, docsData] = await Promise.all([
        apiRequest<ConversationItem[]>("/api/v1/chat/conversations"),
        apiRequest<any[]>("/api/v1/documents").catch(() => []),
      ]);

      const readyDocs: ScopedDocumentOption[] = (docsData || [])
        .filter((d) => d.status === "ready")
        .map((d) => ({ id: d.id, filename: d.filename, page_count: d.page_count }));
      setDocuments(readyDocs);

      const list = convData || [];
      setConversations(list);

      if (requestedDocId && readyDocs.some((d) => d.id === requestedDocId)) {
        const targetDoc = readyDocs.find((d) => d.id === requestedDocId);
        const existingScoped = list.find(
          (c) => c.document_ids && c.document_ids.includes(requestedDocId)
        );
        if (existingScoped) {
          await selectConversation(existingScoped.id);
        } else {
          await createNewConversation([requestedDocId], targetDoc?.filename);
        }
      } else if (list.length > 0 && !activeConvId) {
        await selectConversation(list[0].id);
      } else if (list.length === 0) {
        const defaultIds = readyDocs.length > 0 ? [readyDocs[0].id] : undefined;
        await createNewConversation(defaultIds, readyDocs[0]?.filename);
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
      setConversations((prev) =>
        prev.map((c) => (c.id === convId ? { ...c, document_ids: fullConv.document_ids } : c))
      );
    } catch (e) {
      console.error(e);
    }
  };

  const createNewConversation = async (docIds?: string[], docName?: string) => {
    try {
      const title = docName
        ? `PDF: ${docName.slice(0, 40)}`
        : `Analysis Session ${conversations.length + 1}`;
      const newConv = await apiRequest<ConversationItem>("/api/v1/chat/conversations", {
        method: "POST",
        body: JSON.stringify({
          title,
          document_ids: docIds && docIds.length > 0 ? docIds : null,
        }),
      });
      setConversations((prev) => [newConv, ...prev]);
      setActiveConvId(newConv.id);
      setMessages([]);
    } catch (e) {
      console.error(e);
    }
  };

  const updateConversationScope = async (convId: string, docIds: string[]) => {
    try {
      const targetDoc =
        docIds.length === 1 ? documents.find((d) => d.id === docIds[0]) : undefined;
      const updated = await apiRequest<ConversationItem>(
        `/api/v1/chat/conversations/${convId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ document_ids: docIds }),
        }
      );
      setConversations((prev) =>
        prev.map((c) =>
          c.id === convId
            ? {
                ...c,
                document_ids: updated.document_ids,
                title: targetDoc && c.title.startsWith("Analysis Session") ? c.title : c.title,
              }
            : c
        )
      );
    } catch (e) {
      console.error("Failed to update PDF scope", e);
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

  const activeConv = conversations.find((c) => c.id === activeConvId);
  const currentScopedIds = activeConv?.document_ids ?? null;

  return (
    <div className="h-screen bg-slate-950 flex flex-col overflow-hidden">
      <Navbar />

      <div className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 flex gap-6 overflow-hidden">
        {/* Conversations Sidebar */}
        <aside className="w-72 bg-slate-900 border border-slate-800 rounded-2xl flex flex-col overflow-hidden shrink-0 shadow-xl">
          <div className="p-4 border-b border-slate-800">
            <button
              onClick={() =>
                createNewConversation(
                  currentScopedIds && currentScopedIds.length > 0 ? currentScopedIds : undefined,
                  currentScopedIds && currentScopedIds.length === 1
                    ? documents.find((d) => d.id === currentScopedIds[0])?.filename
                    : undefined
                )
              }
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
              conversations.map((c) => {
                const pinnedDoc =
                  c.document_ids && c.document_ids.length === 1
                    ? documents.find((d) => d.id === c.document_ids?.[0])
                    : undefined;
                return (
                  <div
                    key={c.id}
                    onClick={() => selectConversation(c.id)}
                    className={`group flex items-center justify-between p-3 rounded-xl cursor-pointer text-xs transition ${
                      activeConvId === c.id
                        ? "bg-blue-600/15 text-blue-300 border border-blue-500/30"
                        : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
                    }`}
                  >
                    <div className="min-w-0 flex-1 pr-2">
                      <div className="flex items-center space-x-2 truncate">
                        <MessageSquare className="h-4 w-4 shrink-0 text-slate-400" />
                        <span className="truncate font-medium">{c.title}</span>
                      </div>
                      {pinnedDoc && (
                        <div className="mt-1 ml-6 flex items-center space-x-1 text-[10px] text-emerald-400/90 truncate">
                          <Lock className="h-2.5 w-2.5 shrink-0" />
                          <span className="truncate">{pinnedDoc.filename}</span>
                        </div>
                      )}
                    </div>
                    <button
                      onClick={(e) => deleteConversation(c.id, e)}
                      className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-400 rounded transition shrink-0"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                );
              })
            )}
          </div>

          <div className="p-3 border-t border-slate-800/80 text-[11px] text-slate-500 text-center">
            Strict PDF Scoping &amp; Complete Policy Check
          </div>
        </aside>

        {/* Main Chat Streaming View */}
        <main className="flex-1 h-full overflow-hidden">
          {activeConvId ? (
            <ChatStream
              conversationId={activeConvId}
              initialMessages={messages}
              documents={documents}
              scopedDocIds={currentScopedIds}
              onChangeScope={(docIds) => updateConversationScope(activeConvId, docIds)}
            />
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
