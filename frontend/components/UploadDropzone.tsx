"use client";

import { useState, useRef, ChangeEvent, DragEvent } from "react";
import { UploadCloud, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import { getStoredToken } from "../lib/api";

interface UploadDropzoneProps {
  onUploadSuccess: () => void;
}

export default function UploadDropzone({ onUploadSuccess }: UploadDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setIsDragging(true);
    } else if (e.type === "dragleave") {
      setIsDragging(false);
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      uploadFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      uploadFile(e.target.files[0]);
    }
  };

  const uploadFile = async (file: File) => {
    if (file.size > 50 * 1024 * 1024) {
      setUploadStatus({ type: "error", message: "File exceeds maximum 50MB size limit." });
      return;
    }

    setIsUploading(true);
    setUploadStatus(null);

    const formData = new FormData();
    formData.append("file", file);

    const token = getStoredToken();
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

    try {
      const response = await fetch(`${apiUrl}/api/v1/documents`, {
        method: "POST",
        headers: {
          Authorization: token ? `Bearer ${token}` : "",
        },
        body: formData,
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error?.message || err.detail || "Upload failed");
      }

      const data = await response.json();
      setUploadStatus({
        type: "success",
        message: data.is_duplicate
          ? "Duplicate file detected. Existing indexed document linked."
          : `Ingestion enqueued: ${file.name}`,
      });
      onUploadSuccess();
    } catch (err: any) {
      setUploadStatus({ type: "error", message: err.message || "Failed to upload document." });
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div className="w-full">
      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`relative border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all duration-200 ${
          isDragging
            ? "border-blue-500 bg-blue-500/10 scale-[1.01]"
            : "border-slate-800 bg-slate-900/50 hover:border-slate-700 hover:bg-slate-900"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.xlsx,.txt,.md"
          onChange={handleChange}
          className="hidden"
        />

        <div className="flex flex-col items-center justify-center space-y-3">
          <div className="p-4 rounded-2xl bg-blue-600/10 border border-blue-500/20 text-blue-400">
            {isUploading ? (
              <Loader2 className="h-8 w-8 animate-spin" />
            ) : (
              <UploadCloud className="h-8 w-8" />
            )}
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-200">
              {isUploading ? "Uploading & Streaming to MinIO..." : "Drop enterprise documents here, or browse"}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Supports PDF, Word (.docx), Excel (.xlsx), Markdown up to 50MB
            </p>
          </div>
        </div>
      </div>

      {uploadStatus && (
        <div
          className={`mt-4 p-3 rounded-xl text-xs flex items-center space-x-2 ${
            uploadStatus.type === "success"
              ? "bg-emerald-500/10 border border-emerald-500/20 text-emerald-300"
              : "bg-red-500/10 border border-red-500/20 text-red-300"
          }`}
        >
          {uploadStatus.type === "success" ? (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
          ) : (
            <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
          )}
          <span>{uploadStatus.message}</span>
        </div>
      )}
    </div>
  );
}
