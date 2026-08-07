import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { motion, useReducedMotion } from "framer-motion";
import type { UploadStatus } from "../hooks/useDocuments";
import { STAGE_COLOR, WARN_COLOR } from "../lib/stages";
import type { DocumentInfo } from "../types";
import { Skeleton } from "./ui";

interface DocumentRailProps {
  documents: DocumentInfo[] | null;
  error: string | null;
  uploads: UploadStatus[];
  onUpload: (files: FileList | File[]) => void;
  onDelete: (id: string) => void;
}

export function DocumentRail({
  documents,
  error,
  uploads,
  onUpload,
  onDelete,
}: DocumentRailProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const reducedMotion = useReducedMotion();

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length > 0) onUpload(e.dataTransfer.files);
  };

  const handlePick = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) onUpload(e.target.files);
    e.target.value = "";
  };

  return (
    <div className="flex h-full flex-col gap-3">
      {/* dropzone */}
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload documents"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className="cursor-pointer rounded-md border border-dashed px-3 py-5 text-center transition-[box-shadow,border-color,background-color] duration-200"
        style={{
          borderColor: dragOver ? STAGE_COLOR.generate : "#263354",
          backgroundColor: dragOver ? "#1A2540" : "transparent",
          boxShadow: dragOver
            ? `0 0 18px -4px ${STAGE_COLOR.generate}44, inset 0 1px 0 0 rgba(221,228,242,0.055)`
            : "inset 0 1px 0 0 rgba(221,228,242,0.04)",
        }}
      >
        <p className="font-display text-sm text-ink-100">Upload documents</p>
        <p className="mt-1 text-xs text-ink-300">
          Drop files here or click to browse
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handlePick}
        />
      </div>

      {/* per-file upload status */}
      {uploads.length > 0 && (
        <ul className="space-y-1">
          {uploads.map((u) => (
            <li
              key={u.name}
              className="flex items-center justify-between gap-2 rounded border border-ink-700 bg-ink-800/60 px-2 py-1.5 text-xs shadow-panel surface-edge"
            >
              <span className="min-w-0 truncate text-ink-100">{u.name}</span>
              {u.status === "uploading" && (
                <span className="shrink-0 font-mono text-[10px] text-ink-300">
                  uploading…
                </span>
              )}
              {u.status === "done" && (
                <span
                  className="shrink-0 font-mono text-[10px]"
                  style={{ color: STAGE_COLOR.embed }}
                >
                  done
                </span>
              )}
              {u.status === "error" && (
                <span
                  className="shrink-0 font-mono text-[10px]"
                  style={{ color: WARN_COLOR }}
                  title={u.message}
                >
                  failed
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* document list */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <p className="label-caps mb-2 px-1">Documents</p>

        {documents === null && (
          <div className="space-y-2 px-1">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-5/6" />
          </div>
        )}

        {error && documents !== null && (
          <p className="px-1 text-xs" style={{ color: WARN_COLOR }}>
            {error}
          </p>
        )}

        {documents !== null && documents.length === 0 && !error && (
          <p className="px-1 text-xs leading-relaxed text-ink-300">
            No documents yet. Upload a file above to give your questions
            context.
          </p>
        )}

        {documents !== null && documents.length > 0 && (
          <ul className="space-y-1.5">
            {documents.map((doc, i) => (
              <motion.li
                key={doc.id}
                initial={reducedMotion ? false : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  duration: 0.28,
                  delay: Math.min(i, 8) * 0.04,
                  ease: [0.16, 1, 0.3, 1],
                }}
                className="group flex items-center gap-2 rounded border border-ink-700 bg-ink-800/40 px-2.5 py-2 shadow-panel surface-edge transition-[box-shadow,border-color] duration-120 hover:border-ink-300/20 hover:shadow-raised"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-ink-100">
                    {doc.filename}
                  </p>
                  <p className="mt-0.5 font-mono text-[10px] text-ink-300">
                    {doc.chunk_count} chunks
                    {doc.status !== "ready" && (
                      <span className="ml-1.5 text-ink-300">· {doc.status}</span>
                    )}
                  </p>
                </div>
                <button
                  type="button"
                  aria-label={`Delete ${doc.filename}`}
                  onClick={() => onDelete(doc.id)}
                  className="shrink-0 rounded px-1.5 py-0.5 text-sm leading-none text-ink-300 opacity-60 transition-colors hover:bg-ink-700 hover:text-ink-100 group-hover:opacity-100"
                >
                  ×
                </button>
              </motion.li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
