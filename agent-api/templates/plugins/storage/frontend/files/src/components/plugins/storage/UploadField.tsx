"use client";

import { ImageUp, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { app } from "@/components/app/app";
import { useOperationMutation } from "@/components/app/bindings";
import { errorMessage } from "@/components/app/errors";
import type { TUploadField } from "@/components/app/plugin-types";
import { signal } from "@/components/app/signals";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

type TTarget = { key: string; uploadUrl: string; method?: string; headers?: Record<string, string> };

/** The presigned `PUT`, with its progress (fetch has none for uploads). */
function put(target: TTarget, file: File, onProgress: (percent: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(target.method ?? "PUT", target.uploadUrl);
    for (const [name, value] of Object.entries(target.headers ?? {})) xhr.setRequestHeader(name, value);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(`The upload failed (${xhr.status})`)));
    xhr.onerror = () => reject(new Error("The upload failed"));
    xhr.send(file);
  });
}

function accepts(accept: string[] | undefined, type: string): boolean {
  if (!accept?.length) return true;
  return accept.some((pattern) => (pattern.endsWith("/*") ? type.startsWith(pattern.slice(0, -1)) : pattern === type));
}

function size(bytes: number): string {
  return bytes >= 1_048_576 ? `${(bytes / 1_048_576).toFixed(bytes >= 10_485_760 ? 0 : 1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

/** A file or image field (Story 22.7, storage): drop a file or choose one; it goes up through the presigned URL with
 *  its progress, an image shows its preview, and the form sends the object's key. Replace and remove (an edit sends
 *  `null` for a removed file). */
export const UploadField: TUploadField = ({ field, id, value, onChange, invalid, record }) => {
  const upload = field.upload!;
  const presign = useOperationMutation(upload.presign);
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ url: string; name: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const image = upload.kind === "image";
  const urlField = app.entities[upload.entity]?.fields?.[upload.field]?.urlField;
  const saved = urlField && value && value === record?.[field.name] ? (record?.[urlField] as string | undefined) : undefined;
  const shown = preview?.url ?? saved;
  const key = typeof value === "string" && value ? value : null;

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview.url);
  }, [preview]);

  async function take(file: File | undefined) {
    if (!file) return;
    setProblem(null);
    if (!accepts(upload.accept, file.type)) return setProblem(`This type of file is not accepted (${upload.accept?.join(", ")})`);
    if (upload.maxSize && file.size > upload.maxSize) return setProblem(`The file is larger than ${size(upload.maxSize)}`);
    try {
      setProgress(0);
      const body = { entity: upload.entity, field: upload.field, contentType: file.type || "application/octet-stream", size: file.size, filename: file.name };
      const target = (await presign.mutateAsync({ params: {}, body })) as TTarget;
      await put(target, file, setProgress);
      setPreview({ url: URL.createObjectURL(file), name: file.name });
      onChange(target.key);
      signal("operation", { operationId: upload.presign, record: target.key }); // Story 28.1: the file is up
    } catch (error) {
      setProblem(error instanceof Error && !("code" in error) ? error.message : errorMessage(upload.presign, error));
    } finally {
      setProgress(null);
      if (input.current) input.current.value = "";
    }
  }

  const busy = progress !== null;
  return (
    <div className="flex flex-col gap-2" data-bga-input="upload">
      <input
        ref={input}
        id={id}
        type="file"
        className="sr-only"
        accept={upload.accept?.join(",") || undefined}
        aria-invalid={invalid || Boolean(problem) || undefined}
        disabled={busy}
        onChange={(event) => take(event.target.files?.[0])}
      />
      {key && !busy ? (
        <div className="flex items-center gap-3 rounded-lg border p-2">
          {image && shown ? (
            // eslint-disable-next-line @next/next/no-img-element -- a local preview or a signed URL
            <img src={shown} alt="" className="size-16 shrink-0 rounded-md object-cover" />
          ) : (
            <span className="flex size-16 shrink-0 items-center justify-center rounded-md bg-muted">
              <Upload aria-hidden className="size-5 text-muted-foreground" />
            </span>
          )}
          <span className="min-w-0 flex-1 truncate text-sm">{preview?.name ?? key.split("/").pop()}</span>
          <Button type="button" variant="outline" size="sm" onClick={() => input.current?.click()}>
            Replace
          </Button>
          <Button type="button" variant="ghost" size="icon-sm" aria-label={`Remove ${field.label ?? field.name}`} onClick={() => { setPreview(null); onChange(null); }}>
            <X aria-hidden />
          </Button>
        </div>
      ) : (
        <button
          type="button"
          disabled={busy}
          onClick={() => input.current?.click()}
          onDragOver={(event) => {
            event.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setOver(false);
            take(event.dataTransfer.files?.[0]);
          }}
          className={cn(
            "flex w-full flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground transition-colors hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
            over && "border-primary bg-muted/50",
            (invalid || problem) && "border-destructive",
          )}
        >
          {busy ? (
            <span className="flex w-full max-w-xs flex-col gap-2" aria-live="polite">
              <span>Uploading… {progress}%</span>
              <Progress value={progress ?? 0} />
            </span>
          ) : (
            <>
              {image ? <ImageUp aria-hidden className="size-6" /> : <Upload aria-hidden className="size-6" />}
              <span className="font-medium text-foreground">{image ? "Drop an image or choose one" : "Drop a file or choose one"}</span>
              {upload.maxSize && <span className="text-xs">Up to {size(upload.maxSize)}</span>}
            </>
          )}
        </button>
      )}
      {problem && <p className="text-sm text-destructive">{problem}</p>}
    </div>
  );
};
