"use client";

import { useState, useRef, useEffect, useMemo, ReactNode } from "react";
import {
  Send,
  Bot,
  User as UserIcon,
  Loader2,
  Sparkles,
  Database,
  FileText,
  Lock,
  ChevronDown,
  Check,
} from "lucide-react";
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
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);
  const pendingScopeOpsRef = useRef(0);
  const { streamQuestion, isStreaming } = useSSE();

  const docIdSet = useMemo(() => new Set(documents.map((d) => d.id)), [documents]);

  useEffect(() => {
    setMessages(initialMessages);
  }, [initialMessages]);

  useEffect(() => {
    if (pendingScopeOpsRef.current > 0) return;
    if (scopedDocIds && scopedDocIds.length > 0) {
      setSelectedDocIds(scopedDocIds.filter((id) => docIdSet.has(id)));
    } else {
      setSelectedDocIds(documents.map((d) => d.id));
    }
  }, [conversationId, scopedDocIds, documents, docIdSet]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(event.target as Node)) {
        setPickerOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPickerOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  const selectedDocs = useMemo(
    () => documents.filter((d) => selectedDocIds.includes(d.id)),
    [documents, selectedDocIds]
  );
  const isAllSelected = documents.length > 0 && selectedDocs.length === documents.length;
  const isSingleStrict = selectedDocs.length === 1;
  const isSubsetStrict =
    selectedDocs.length > 0 && (documents.length === 1 || selectedDocs.length < documents.length);

  const toBackendScope = (ids: string[]): string[] => {
    if (documents.length > 1 && ids.length >= documents.length) {
      return [];
    }
    return ids;
  };

  const applyScopeUpdate = async (nextIds: string[]) => {
    setSelectedDocIds(nextIds);
    if (!onChangeScope || nextIds.length === 0) return;
    pendingScopeOpsRef.current += 1;
    setUpdatingScope(true);
    try {
      await onChangeScope(toBackendScope(nextIds));
    } finally {
      pendingScopeOpsRef.current = Math.max(0, pendingScopeOpsRef.current - 1);
      if (pendingScopeOpsRef.current === 0) {
        setUpdatingScope(false);
      }
    }
  };

  const handleToggleDoc = (docId: string) => {
    const exists = selectedDocIds.includes(docId);
    const nextIds = exists
      ? selectedDocIds.filter((id) => id !== docId)
      : [...selectedDocIds, docId];
    void applyScopeUpdate(nextIds);
  };

  const handleSelectAllDocs = () => {
    void applyScopeUpdate(documents.map((d) => d.id));
  };

  const handleClearDocs = () => {
    setSelectedDocIds([]);
  };

  const handleOnlyDoc = (docId: string) => {
    void applyScopeUpdate([docId]);
    setPickerOpen(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const noSelection = documents.length > 0 && selectedDocs.length === 0;
    if (!inputQuery.trim() || isStreaming || noSelection) return;

    const userText = inputQuery.trim();
    setInputQuery("");

    const userMsg: MessageItem = { role: "user", content: userText };
    setMessages((prev) => [...prev, userMsg]);

    const assistantIndex = messages.length + 1;
    let accumulatedText = "";
    let capturedCitations: Citation[] = [];

    const requestDocIds = toBackendScope(selectedDocs.map((d) => d.id));

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
          <div className="relative flex items-center space-x-2" ref={pickerRef}>
            <FileText className="h-4 w-4 text-emerald-400" />
            <span className="text-xs font-semibold text-slate-300">Source PDFs:</span>
            <button
              type="button"
              disabled={isStreaming || documents.length === 0}
              onClick={() => setPickerOpen((prev) => !prev)}
              aria-expanded={pickerOpen}
              aria-label="Select source PDF documents"
              className={`inline-flex items-center space-x-2 bg-slate-950 border text-xs rounded-lg px-2.5 py-1.5 max-w-[260px] transition focus:ring-1 focus:ring-emerald-500 disabled:opacity-50 ${documents.length > 0 && selectedDocs.length === 0
                  ? "border-amber-500/60 text-amber-300"
                  : "border-slate-700 text-slate-200 hover:border-slate-600"
                }`}
            >
              <span className="truncate">
                {documents.length === 0
                  ? "No Ready PDFs"
                  : selectedDocs.length === 0
                    ? `0 of ${documents.length} PDFs Selected`
                    : isSingleStrict
                      ? selectedDocs[0].filename
                      : `${selectedDocs.length} of ${documents.length} PDFs`}
              </span>
              {updatingScope ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-emerald-400 shrink-0" />
              ) : (
                <ChevronDown
                  className={`h-3.5 w-3.5 text-slate-400 shrink-0 transition-transform ${pickerOpen ? "rotate-180" : ""
                    }`}
                />
              )}
            </button>

            {pickerOpen && documents.length > 0 && (
              <div className="absolute left-0 top-full mt-2 z-30 w-80 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden">
                <div className="px-3 py-2 border-b border-slate-800 bg-slate-950/70 flex items-center justify-between text-[11px]">
                  <span className="text-slate-400 font-medium">
                    {selectedDocs.length} of {documents.length} checked
                  </span>
                  <div className="flex items-center space-x-2">
                    <button
                      type="button"
                      onClick={handleSelectAllDocs}
                      className="text-blue-400 hover:text-blue-300 font-medium"
                    >
                      Select All
                    </button>
                    <span className="text-slate-700">·</span>
                    <button
                      type="button"
                      onClick={handleClearDocs}
                      className="text-slate-400 hover:text-slate-200 font-medium"
                    >
                      Clear
                    </button>
                  </div>
                </div>

                <div className="max-h-60 overflow-y-auto divide-y divide-slate-800/70">
                  {documents.map((doc) => {
                    const checked = selectedDocIds.includes(doc.id);
                    return (
                      <div
                        key={doc.id}
                        className="flex items-center justify-between px-3 py-2 hover:bg-slate-800/60 transition group"
                      >
                        <label className="flex items-center space-x-2.5 min-w-0 flex-1 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => handleToggleDoc(doc.id)}
                            className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-emerald-500 focus:ring-emerald-500 cursor-pointer shrink-0"
                          />
                          <span className="text-xs text-slate-200 truncate" title={doc.filename}>
                            {doc.filename}
                          </span>
                          {doc.page_count ? (
                            <span className="text-[10px] text-slate-500 shrink-0">
                              {doc.page_count}p
                            </span>
                          ) : null}
                        </label>
                        <button
                          type="button"
                          onClick={() => handleOnlyDoc(doc.id)}
                          className="ml-2 px-1.5 py-0.5 rounded text-[10px] text-slate-400 hover:text-emerald-300 hover:bg-emerald-500/10 opacity-0 group-hover:opacity-100 transition shrink-0"
                        >
                          Only
                        </button>
                      </div>
                    );
                  })}
                </div>

                <div className="px-3 py-2 border-t border-slate-800 bg-slate-950/70 flex items-center justify-between text-[11px]">
                  {selectedDocs.length === 0 ? (
                    <span className="text-amber-300">Select at least 1 PDF above</span>
                  ) : (
                    <span className="text-slate-400 truncate">
                      {isAllSelected ? "All PDFs checked" : `Scoped to ${selectedDocs.length} PDF(s)`}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => setPickerOpen(false)}
                    className="inline-flex items-center space-x-1 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium"
                  >
                    <Check className="h-3 w-3 text-emerald-400" />
                    <span>Done</span>
                  </button>
                </div>
              </div>
            )}
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
          {documents.length > 0 && selectedDocs.length === 0 ? (
            <span className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-300 font-medium">
              <span>Select 1+ PDFs in Source PDFs</span>
            </span>
          ) : isSingleStrict ? (
            <span className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 font-medium">
              <Lock className="h-3 w-3 shrink-0" />
              <span className="truncate max-w-[220px]">Strict PDF: {selectedDocs[0].filename}</span>
            </span>
          ) : isSubsetStrict ? (
            <span
              className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 font-medium"
              title={selectedDocs.map((d) => d.filename).join(", ")}
            >
              <Lock className="h-3 w-3 shrink-0" />
              <span className="truncate max-w-[240px]">
                Strict ({selectedDocs.length}/{documents.length}):{" "}
                {selectedDocs.map((d) => d.filename).join(", ")}
              </span>
            </span>
          ) : (
            <span className="inline-flex items-center space-x-1.5 text-slate-400">
              <Database className="h-3.5 w-3.5 text-blue-400" />
              <span>All PDFs Selected ({documents.length})</span>
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
              {selectedDocs.length === 0 && documents.length > 0
                ? "Select one or more PDFs above to begin."
                : isSingleStrict
                  ? `Ask anything strictly from "${selectedDocs[0].filename}".`
                  : isSubsetStrict
                    ? `Ask anything strictly across your ${selectedDocs.length} selected PDFs.`
                    : "Ask anything across all selected documents in your workspace."}
            </p>
            <p className="text-xs text-slate-600 max-w-md">
              {isSubsetStrict
                ? "Scoped mode active: answers cite only the checked PDFs and exclude unchecked files."
                : "Tip: Open Source PDFs above to check 1, 2, or 3 specific PDFs instead of all documents."}
            </p>
          </div>
        ) : (
          messages.map((m, idx) => (
            <div
              key={idx}
              className={`flex items-start space-x-3 ${m.role === "user" ? "flex-row-reverse space-x-reverse" : "flex-row"
                }`}
            >
              <div
                className={`p-2 rounded-xl shrink-0 ${m.role === "user"
                    ? "bg-blue-600 text-white"
                    : "bg-slate-800 text-blue-400 border border-slate-700"
                  }`}
              >
                {m.role === "user" ? <UserIcon className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
              </div>

              <div
                className={`max-w-2xl rounded-2xl p-4 text-sm leading-relaxed ${m.role === "user"
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
              documents.length > 0 && selectedDocs.length === 0
                ? "Check at least 1 PDF in Source PDFs above before asking..."
                : isSingleStrict
                  ? `Ask strictly about ${selectedDocs[0].filename}...`
                  : isSubsetStrict
                    ? `Ask strictly across ${selectedDocs.length} selected PDFs...`
                    : "Ask a natural-language question over your selected documents..."
            }
            disabled={isStreaming}
            className="flex-1 bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={isStreaming || !inputQuery.trim() || (documents.length > 0 && selectedDocs.length === 0)}
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
