import { useCallback, useEffect, useRef, useState } from "react";
import { deleteDocument, fetchDocuments, uploadDocument } from "../lib/api";
import type { DocumentInfo } from "../types";

export interface UploadStatus {
  name: string;
  status: "uploading" | "done" | "error";
  message?: string;
}

export function useDocuments() {
  const [documents, setDocuments] = useState<DocumentInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadStatus[]>([]);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const docs = await fetchDocuments();
      if (!mounted.current) return;
      setDocuments(docs);
      setError(null);
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : "Failed to load documents");
      setDocuments((d) => d ?? []);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
    };
  }, [refresh]);

  // Poll while any document is still processing.
  useEffect(() => {
    const processing = documents?.some(
      (d) => d.status !== "ready" && d.status !== "failed" && d.status !== "error",
    );
    if (!processing) return;
    const id = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(id);
  }, [documents, refresh]);

  const upload = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      for (const file of list) {
        setUploads((u) => [
          ...u.filter((x) => x.name !== file.name),
          { name: file.name, status: "uploading" },
        ]);
        try {
          await uploadDocument(file);
          if (!mounted.current) return;
          setUploads((u) =>
            u.map((x) =>
              x.name === file.name ? { ...x, status: "done" as const } : x,
            ),
          );
          window.setTimeout(() => {
            if (mounted.current)
              setUploads((u) => u.filter((x) => x.name !== file.name));
          }, 2500);
        } catch (e) {
          if (!mounted.current) return;
          setUploads((u) =>
            u.map((x) =>
              x.name === file.name
                ? {
                    ...x,
                    status: "error" as const,
                    message: e instanceof Error ? e.message : "Upload failed",
                  }
                : x,
            ),
          );
        }
        await refresh();
      }
    },
    [refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      // Optimistic removal, restore on failure via refresh.
      setDocuments((docs) => docs?.filter((d) => d.id !== id) ?? docs);
      try {
        await deleteDocument(id);
      } catch {
        /* fall through to refresh */
      }
      await refresh();
    },
    [refresh],
  );

  return { documents, error, uploads, upload, remove, refresh };
}
