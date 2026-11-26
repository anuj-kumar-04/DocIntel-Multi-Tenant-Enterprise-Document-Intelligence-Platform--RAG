"use client";

import { useState, useRef, useEffect, ReactNode } from "react";
import { Send, Bot, User as UserIcon, Loader2, Sparkles, Database, FileText, Lock } from "lucide-react";
import { Citation, useSSE } from "../lib/useSSE";
import { CitationBadge, CitationDrawer } from "./CitationCard";

export interface ScopedDocumentOption {
  id: string;
  filename: string;
  page_count?: number;
}

interface MessageItem {
  id?: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    cost_usd?: number;
    cached?: boolean;
    model?: string;
  };
}

interface ChatStreamProps {
  conversationId: string;
  initialMessages?: MessageItem[];
  documents?: ScopedDocumentOption[];
  scopedDocIds?: string[] | null;
  onChangeScope?: (docIds: string[]) => Promise<void> | void;
}

export default function ChatStream({
  conversationId,
  initialMessages = [],
  documents = [],
  scopedDocIds = null,
  onChangeScope,
}: ChatStreamProps) {
  const [messages, setMessages] = useState<MessageItem[]>(initialMessages);
  const [inputQuery, setInputQuery] = useState("");
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<string>("v3");
  const [updatingScope, setUpdatingScope] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { streamQuestion, isStreaming } = useSSE();

  useEffect(() => {
    setMessages(initialMessages);
  }, [initialMessages]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  const activeDocId = scopedDocIds && scopedDocIds.length === 1 ? scopedDocIds[0] : "";
  const activeDoc = documents.find((d) => d.id === activeDocId);

  const handleScopeSelect = async (newDocId: string) => {
    if (!onChangeScope) return;
    setUpdatingScope(true);
    try {
      await onChangeScope(newDocId ? [newDocId] : []);
    } finally {
      setUpdatingScope(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputQuery.trim() || isStreaming) return;

    const userText = inputQuery.trim();
    setInputQuery("");

    const userMsg: MessageItem = { role: "user", content: userText };
    setMessages((prev) => [...prev, userMsg]);

    const assistantIndex = messages.length + 1;
    let accumulatedText = "";
    let capturedCitations: Citation[] = [];

    const requestDocIds = activeDocId ? [activeDocId] : [];

    await streamQuestion(
      conversationId,
      userText,
      selectedVersion,
      {
        onToken: (token) => {
          accumulatedText += token;
          setMessages((prev) => {
            const next = [...prev];
            next[assistantIndex] = {
              role: "assistant",
              content: accumulatedText,
              citations: capturedCitations,
            };
            return next;
          });
        },
        onCitations: (citations) => {
          capturedCitations = citations;
          setMessages((prev) => {
            const next = [...prev];
            if (next[assistantIndex]) {
              next[assistantIndex].citations = citations;
            }
            return next;
          });
        },
        onUsage: (usage) => {
          setMessages((prev) => {
            const next = [...prev];
            if (next[assistantIndex]) {
              next[assistantIndex].usage = usage;
            }
            return next;
          });
        },
        onError: (err) => {
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              content: `Error: ${err}`,
            },
          ]);
        },
      },
      requestDocIds
    );
  };

  const renderContentWithCitations = (content: string, citations: Citation[] = []): ReactNode => {
    const parts = content.split(/(\[\d+\])/g);
    const citeMap = new Map<number, Citation>();
    citations.forEach((c) => citeMap.set(c.index, c));

    return parts.map((part, i) => {
      const match = part.match(/^\[(\d+)\]$/);
      if (match) {
        const citeIndex = parseInt(match[1], 10);
        const citeObj = citeMap.get(citeIndex);
        return (
          <CitationBadge
            key={i}
            index={citeIndex}
            onClick={() =>
              setSelectedCitation(
                citeObj || {
                  index: citeIndex,
                  chunk_id: "",
                  document_id: "",
                  filename: "Document Source",
                  page: 1,
                  snippet: "Verified context segment from pgvector store.",
                }
              )
            }
          />
        );
      }
      return <span key={i}>{part}</span>;
    });
  };

  return (
    <div className="flex flex-col h-full bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden relative">
      {/* Header Pipeline & PDF Scope Selector */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-b border-slate-800 bg-slate-900/60">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center space-x-2">
            <FileText className="h-4 w-4 text-emerald-400" />
            <span className="text-xs font-semibold text-slate-300">Source PDF:</span>
            <select
              value={activeDocId}
              disabled={isStreaming || updatingScope}
              onChange={(e) => handleScopeSelect(e.target.value)}
              className="bg-slate-950 border border-slate-700 text-xs text-slate-200 rounded-lg px-2.5 py-1 max-w-[230px] focus:ring-1 focus:ring-emerald-500"
            >
              <option value="">All Tenant Documents ({documents.length})</option>
              {documents.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  Only: {doc.filename}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center space-x-2">
            <Sparkles className="h-4 w-4 text-blue-400" />
            <span className="text-xs font-semibold text-slate-300">Pipeline:</span>
            <select
              value={selectedVersion}
              onChange={(e) => setSelectedVersion(e.target.value)}
              className="bg-slate-950 border border-slate-700 text-xs text-slate-200 rounded-lg px-2.5 py-1 focus:ring-1 focus:ring-blue-500"
            >
              <option value="v3">v3 Full Stack (BM25 + Dense + Rerank)</option>
              <option value="v2">v2 Hybrid (Dense + BM25 + RRF)</option>
              <option value="v1">v1 Naive Baseline (Dense-Only)</option>
            </select>
          </div>
        </div>

        <div className="flex items-center space-x-2 text-xs">
          {activeDoc ? (
            <span className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 font-medium">
              <Lock className="h-3 w-3" />
              <span className="truncate max-w-[220px]">Strict PDF: {activeDoc.filename}</span>
            </span>
          ) : (
            <span className="inline-flex items-center space-x-1.5 text-slate-400">
              <Database className="h-3.5 w-3.5 text-blue-400" />
              <span>Workspace-Wide (Tenant Isolated)</span>
            </span>
          )}
        </div>
      </div>

      {/* Messages Feed */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-slate-500 space-y-3">
            <Bot className="h-12 w-12 text-slate-700" />
            <p className="text-sm font-medium text-slate-400">
              {activeDoc
                ? `Ask anything strictly from "${activeDoc.filename}".`
                : "Ask anything about your uploaded corporate filings, policies, or contracts."}
            </p>
            <p className="text-xs text-slate-600 max-w-md">
              {activeDoc
                ? "Complete-policy mode active: the complete selected PDF is checked and answers outside it are refused."
                : "Tip: Select a specific PDF in Source PDF above to lock answers strictly to that single file."}
            </p>
          </div>
        ) : (
          messages.map((m, idx) => (
            <div
              key={idx}
              className={`flex items-start space-x-3 ${
                m.role === "user" ? "flex-row-reverse space-x-reverse" : "flex-row"
              }`}
            >
              <div
                className={`p-2 rounded-xl shrink-0 ${
                  m.role === "user"
                    ? "bg-blue-600 text-white"
                    : "bg-slate-800 text-blue-400 border border-slate-700"
                }`}
              >
                {m.role === "user" ? <UserIcon className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
              </div>

              <div
                className={`max-w-2xl rounded-2xl p-4 text-sm leading-relaxed ${
                  m.role === "user"
                    ? "bg-blue-600 text-white rounded-tr-none"
                    : "bg-slate-900 border border-slate-800 text-slate-200 rounded-tl-none"
                }`}
              >
                <div className="whitespace-pre-wrap">
                  {m.role === "assistant"
                    ? renderContentWithCitations(m.content, m.citations)
                    : m.content}
                </div>

                {m.usage && (
                  <div className="mt-3 pt-2 border-t border-slate-800/80 flex items-center space-x-3 text-[11px] text-slate-400">
                    {m.usage.cached && (
                      <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-semibold">
                        ⚡ Cached Hit
                      </span>
                    )}
                    <span>Model: {m.usage.model || "LiteLLM"}</span>
                    {m.usage.cost_usd !== undefined && (
                      <span>Cost: ${m.usage.cost_usd.toFixed(4)}</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Field */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-slate-800 bg-slate-900/50">
        <div className="flex items-center space-x-2">
          <input
            type="text"
            value={inputQuery}
            onChange={(e) => setInputQuery(e.target.value)}
            placeholder={
              activeDoc
                ? `Ask strictly about ${activeDoc.filename}...`
                : "Ask a natural-language question over your documents..."
            }
            disabled={isStreaming}
            className="flex-1 bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={isStreaming || !inputQuery.trim()}
            className="p-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-xl transition"
          >
            {isStreaming ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
          </button>
        </div>
      </form>

      {/* Slide-out Citation Drawer */}
      <CitationDrawer
        citation={selectedCitation}
        onClose={() => setSelectedCitation(null)}
      />
    </div>
  );
}
