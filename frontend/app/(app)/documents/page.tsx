"use client";

import { useEffect, useState, useCallback } from "react";
import Navbar from "../../../components/Navbar";
import UploadDropzone from "../../../components/UploadDropzone";
import { apiRequest } from "../../../lib/api";
import { FileText, Trash2, CheckCircle2, Clock, AlertTriangle, Layers, BookOpen } from "lucide-react";

interface DocumentItem {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  page_count: number;
  chunk_count: number;
  status: "queued" | "parsing" | "embedding" | "ready" | "failed";
  error_message?: string;
  created_at: string;
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchDocuments = useCallback(async () => {
    try {
      const data = await apiRequest<DocumentItem[]>("/api/v1/documents");
      setDocuments(data || []);
    } catch (e) {
      console.error("Failed to load documents", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDocuments();

    // Live status polling every 2 seconds if any document is in progress
    const interval = setInterval(() => {
      fetchDocuments();
    }, 2000);

    return () => clearInterval(interval);
  }, [fetchDocuments]);

  const handleDelete = async (docId: string) => {
    if (!confirm("Are you sure you want to delete this document and all indexed chunks?")) return;
    try {
      await apiRequest(`/api/v1/documents/${docId}`, { method: "DELETE" });
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
    } catch (err: any) {
      alert(`Deletion failed: ${err.message}`);
    }
  };

  const getStatusBadge = (status: DocumentItem["status"]) => {
    switch (status) {
      case "ready":
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle2 className="h-3 w-3" />
            <span>Ready</span>
          </span>
        );
      case "parsing":
      case "embedding":
      case "queued":
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 animate-pulse">
            <Clock className="h-3 w-3" />
            <span className="capitalize">{status}...</span>
          </span>
        );
      case "failed":
        return (
          <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-500/10 text-red-400 border border-red-500/20">
            <AlertTriangle className="h-3 w-3" />
            <span>Failed</span>
          </span>
        );
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      <Navbar />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Knowledge Vault & Ingestion Pipeline</h1>
          <p className="text-xs text-slate-400 mt-1">
            Uploaded files are parsed with Docling, chunked layout-aware, embedded in batches of 64, and indexed with pgvector.
          </p>
        </div>

        {/* Upload Dropzone */}
        <UploadDropzone onUploadSuccess={fetchDocuments} />

        {/* Documents Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-200">Indexed Tenant Documents</h2>
            <span className="text-xs text-slate-400">{documents.length} files tracked</span>
          </div>

          {loading ? (
            <div className="p-8 text-center text-slate-500 text-sm">Loading document repository...</div>
          ) : documents.length === 0 ? (
            <div className="p-12 text-center text-slate-500 space-y-2">
              <FileText className="h-8 w-8 mx-auto text-slate-600" />
              <p className="text-sm">No documents uploaded yet for this organization.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm text-slate-300">
                <thead className="bg-slate-950/50 text-xs uppercase text-slate-500 border-b border-slate-800">
                  <tr>
                    <th className="px-6 py-3">Document Name</th>
                    <th className="px-6 py-3">Status</th>
                    <th className="px-6 py-3">Pages</th>
                    <th className="px-6 py-3">Chunks</th>
                    <th className="px-6 py-3">Size</th>
                    <th className="px-6 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {documents.map((doc) => (
                    <tr key={doc.id} className="hover:bg-slate-800/40 transition">
                      <td className="px-6 py-4 flex items-center space-x-3">
                        <div className="p-2 rounded-lg bg-blue-600/10 text-blue-400">
                          <FileText className="h-4 w-4" />
                        </div>
                        <div>
                          <div className="font-medium text-slate-200">{doc.filename}</div>
                          <div className="text-xs text-slate-500">{new Date(doc.created_at).toLocaleDateString()}</div>
                        </div>
                      </td>
                      <td className="px-6 py-4">{getStatusBadge(doc.status)}</td>
                      <td className="px-6 py-4">
                        <div className="flex items-center space-x-1.5 text-xs text-slate-400">
                          <BookOpen className="h-3.5 w-3.5" />
                          <span>{doc.page_count} pages</span>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center space-x-1.5 text-xs text-slate-400">
                          <Layers className="h-3.5 w-3.5" />
                          <span>{doc.chunk_count} chunks</span>
                        </div>
                      </td>
                      <td className="px-6 py-4 text-xs text-slate-400">
                        {(doc.size_bytes / 1024).toFixed(1)} KB
                      </td>
                      <td className="px-6 py-4 text-right">
                        <button
                          onClick={() => handleDelete(doc.id)}
                          className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition"
                          title="Delete Document"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
