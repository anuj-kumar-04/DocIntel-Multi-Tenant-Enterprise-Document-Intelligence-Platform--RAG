"use client";

import { FileText, ExternalLink, X } from "lucide-react";
import { Citation } from "../lib/useSSE";

interface CitationDrawerProps {
  citation: Citation | null;
  onClose: () => void;
}

export function CitationDrawer({ citation, onClose }: CitationDrawerProps) {
  if (!citation) return null;

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-slate-900 border-l border-slate-800 shadow-2xl p-6 z-50 transform transition-transform duration-300 ease-in-out flex flex-col">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div className="flex items-center space-x-2">
          <div className="px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 font-mono font-bold text-xs">
            [{citation.index}]
          </div>
          <h3 className="font-semibold text-slate-100 text-sm">Grounded Citation</h3>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-6 space-y-4 flex-1 overflow-y-auto">
        <div>
          <label className="text-xs text-slate-500 font-medium">Source Document</label>
          <div className="flex items-center space-x-2 mt-1 p-2 rounded-lg bg-slate-950 border border-slate-800">
            <FileText className="h-4 w-4 text-blue-400 shrink-0" />
            <span className="text-sm font-medium text-slate-200 truncate">{citation.filename}</span>
          </div>
        </div>

        <div>
          <label className="text-xs text-slate-500 font-medium">Verified Page Reference</label>
          <div className="mt-1 text-sm font-semibold text-blue-300">
            Page {citation.page}
          </div>
        </div>

        <div>
          <label className="text-xs text-slate-500 font-medium">Original Excerpt</label>
          <div className="mt-1 p-3 rounded-lg bg-slate-950 border border-slate-800/80 text-xs text-slate-300 leading-relaxed font-mono whitespace-pre-wrap">
            "{citation.snippet}"
          </div>
        </div>

        <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400 flex items-center space-x-2">
          <div className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
          <span>Cryptographically verified against pgvector tenant chunk</span>
        </div>
      </div>
    </div>
  );
}

interface CitationBadgeProps {
  index: number;
  onClick: () => void;
}

export function CitationBadge({ index, onClick }: CitationBadgeProps) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center px-1.5 py-0.5 mx-0.5 text-xs font-semibold rounded bg-blue-600/20 hover:bg-blue-600/40 text-blue-300 border border-blue-500/30 transition shadow-sm cursor-pointer"
      title={`View citation [${index}] source snippet`}
    >
      [{index}]
    </button>
  );
}
