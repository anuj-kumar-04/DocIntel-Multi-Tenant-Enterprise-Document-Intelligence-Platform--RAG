import { useState, useCallback } from "react";
import { getStoredToken } from "./api";

export interface Citation {
  index: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  page: number;
  snippet: string;
}

export interface UseSSEOptions {
  onToken?: (token: string) => void;
  onCitations?: (citations: Citation[]) => void;
  onUsage?: (usage: any) => void;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

export function useSSE() {
  const [isStreaming, setIsStreaming] = useState(false);

  const streamQuestion = useCallback(
    async (
      conversationId: string,
      question: string,
      version: string | null = null,
      options: UseSSEOptions = {}
    ) => {
      setIsStreaming(true);
      const token = getStoredToken();
      const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

      try {
        const response = await fetch(
          `${apiUrl}/api/v1/chat/conversations/${conversationId}/ask`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: token ? `Bearer ${token}` : "",
            },
            body: JSON.stringify({ question, version }),
          }
        );

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}));
          const errMsg = errData.error?.message || "Failed to initiate stream";
          options.onError?.(errMsg);
          setIsStreaming(false);
          return;
        }

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        if (!reader) return;

        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const block of lines) {
            const eventMatch = block.match(/^event:\s*(\w+)/m);
            const dataMatch = block.match(/^data:\s*(.+)$/m);

            if (eventMatch && dataMatch) {
              const eventType = eventMatch[1];
              try {
                const parsed = JSON.parse(dataMatch[1]);
                if (eventType === "token") {
                  options.onToken?.(parsed.token);
                } else if (eventType === "citations") {
                  options.onCitations?.(parsed.citations);
                } else if (eventType === "usage") {
                  options.onUsage?.(parsed);
                } else if (eventType === "done") {
                  options.onComplete?.();
                } else if (eventType === "error") {
                  options.onError?.(parsed.message || parsed.error);
                }
              } catch (e) {
                console.error("SSE parse error", e);
              }
            }
          }
        }
      } catch (err: any) {
        options.onError?.(err.message || "Network error during stream");
      } finally {
        setIsStreaming(false);
      }
    },
    []
  );

  return { streamQuestion, isStreaming };
}
