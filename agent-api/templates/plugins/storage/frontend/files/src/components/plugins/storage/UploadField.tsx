"use client";

import { Captions, FileAudio, FileVideo, ImageUp, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { app } from "@/components/app/app";
import { useOperationMutation } from "@/components/app/bindings";
import { errorMessage } from "@/components/app/errors";
import { formMethods, isBlank } from "@/components/app/form/registry";
import type { TUploadField } from "@/components/app/plugin-types";
import { signal } from "@/components/app/signals";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

type TTarget = { key: string; uploadUrl: string; method?: string; headers?: Record<string, string> };

/** The presigned `PUT` through XMLHttpRequest, with its progress (fetch has none for uploads) and a cancel. */
function put(target: TTarget, file: File, onProgress: (percent: number) => void, xhr: XMLHttpRequest): Promise<void> {
  return new Promise((resolve, reject) => {
    xhr.open(target.method ?? "PUT", target.uploadUrl);
    for (const [name, value] of Object.entries(target.headers ?? {})) xhr.setRequestHeader(name, value);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(`The upload failed (${xhr.status})`)));
    xhr.onerror = () => reject(new Error("The upload failed"));
    xhr.onabort = () => reject(new Error("cancelled"));
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

/** The type of a file whose browser type is empty (`.srt` and `.vtt` often are), from its name. */
function typeOf(file: File): string {
  if (file.type) return file.type;
  const name = file.name.toLowerCase();
  if (name.endsWith(".vtt")) return "text/vtt";
  if (name.endsWith(".srt")) return "application/x-subrip";
  if (name.endsWith(".mp4") || name.endsWith(".m4v")) return "video/mp4";
  if (name.endsWith(".webm")) return "video/webm";
  if (name.endsWith(".mp3")) return "audio/mpeg";
  if (name.endsWith(".ogg")) return "audio/ogg";
  if (name.endsWith(".wav")) return "audio/wav";
  return "application/octet-stream";
}

/** The duration of a media file from its metadata (seconds), before it is uploaded; null when the browser cannot
 *  read it within a moment (the upload never waits on it). */
function readDuration(file: File, kind: string): Promise<number | null> {
  return new Promise((resolve) => {
    const element = document.createElement(kind === "audio" ? "audio" : "video");
    const url = URL.createObjectURL(file);
    let settled = false;
    const done = (value: number | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      URL.revokeObjectURL(url);
      resolve(value);
    };
    const timer = setTimeout(() => done(null), 2500);
    element.preload = "metadata";
    element.onloadedmetadata = () => done(Number.isFinite(element.duration) ? element.duration : null);
    element.onerror = () => done(null);
    element.src = url;
  });
}

const DURATION_FIELD = /duration|runtime|length/i;

/** Story 29.3: a form field that holds the duration (its name says so), when the form has one and it is empty. */
function fillDuration(formId: string, seconds: number): void {
  const form = app.forms[formId];
  const methods = formMethods(formId);
  if (!form || !methods) return;
  const field = form.fields.find((candidate) => !candidate.hidden && DURATION_FIELD.test(candidate.name) && ["integer", "number", "decimal"].includes(candidate.type));
  if (!field || !isBlank(methods.getValues()[field.name])) return;
  const value = /min/i.test(field.name) || field.unit === "min" ? Math.round(seconds / 60) : Math.round(seconds);
  methods.setValue(field.name, value, { shouldValidate: true, shouldDirty: true });
}

/** A file, image or media field (Story 22.7, Epic 29 D7): drop a file or choose one; it goes up through the
 *  presigned URL in one request, with its progress and a cancel; an image shows its preview, a video or an audio
 *  file plays before the upload (the local file), a media file's duration fills the form's duration field; the form
 *  sends the object's key. Replace and remove (an edit sends `null` for a removed file). */
export const UploadField: TUploadField = ({ field, id, value, onChange, invalid, record }) => {
  const upload = field.upload!;
  const presign = useOperationMutation(upload.presign);
  const input = useRef<HTMLInputElement>(null);
  const xhr = useRef<XMLHttpRequest | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ url: string; name: string; type: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const kind = upload.kind ?? "file";
  const image = kind === "image";
  const media = kind === "video" || kind === "audio";
  const urlField = app.entities[upload.entity]?.fields?.[upload.field]?.urlField;
  const saved = urlField && value && value === record?.[field.name] ? (record?.[urlField] as string | undefined) : undefined;
  const shown = preview?.url ?? saved;
  const key = typeof value === "string" && value ? value : null;
  const formId = id.endsWith(`-${field.name}`) ? id.slice(0, -(field.name.length + 1)) : id;

  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview.url);
  }, [preview]);

  async function take(file: File | undefined) {
    if (!file) return;
    setProblem(null);
    const type = typeOf(file);
    if (!accepts(upload.accept, type)) return setProblem(`This type of file is not accepted (${upload.accept?.join(", ")})`);
    if (upload.maxSize && file.size > upload.maxSize) return setProblem(`The file is larger than ${size(upload.maxSize)}`);
    if (media) {
      const seconds = await readDuration(file, kind);
      if (seconds) fillDuration(formId, seconds);
    }
    try {
      setProgress(0);
      const body = { entity: upload.entity, field: upload.field, contentType: type, size: file.size, filename: file.name };
      const target = (await presign.mutateAsync({ params: {}, body })) as TTarget;
      xhr.current = new XMLHttpRequest();
      await put(target, file, setProgress, xhr.current);
      setPreview({ url: URL.createObjectURL(file), name: file.name, type });
      onChange(target.key);
      signal("operation", { operationId: upload.presign, record: target.key }); // Story 28.1: the file is up
    } catch (error) {
      if (error instanceof Error && error.message === "cancelled") setProblem(null);
      else setProblem(error instanceof Error && !("code" in error) ? error.message : errorMessage(upload.presign, error));
    } finally {
      xhr.current = null;
      setProgress(null);
      if (input.current) input.current.value = "";
    }
  }

  const busy = progress !== null;
  const Icon = kind === "video" ? FileVideo : kind === "audio" ? FileAudio : kind === "subtitles" ? Captions : image ? ImageUp : Upload;
  const words = { image: "Drop an image or choose one", video: "Drop a video or choose one", audio: "Drop an audio file or choose one", subtitles: "Drop a subtitle file (.vtt or .srt) or choose one", file: "Drop a file or choose one" }[kind] ?? "Drop a file or choose one";
  return (
    <div className="flex flex-col gap-2" data-bga-input="upload" data-bga-upload={kind}>
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
        <div className="flex flex-col gap-2 rounded-lg border p-2">
          <div className="flex items-center gap-3">
            {image && shown ? (
              // eslint-disable-next-line @next/next/no-img-element -- a local preview or a signed URL
              <img src={shown} alt="" className="size-16 shrink-0 rounded-md object-cover" />
            ) : (
              <span className="flex size-16 shrink-0 items-center justify-center rounded-md bg-muted">
                <Icon aria-hidden className="size-5 text-muted-foreground" />
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
          {media && shown && (kind === "video" ? (
            <video src={shown} controls playsInline preload="metadata" className="max-h-56 w-full rounded-md bg-black" />
          ) : (
            <audio src={shown} controls preload="metadata" className="w-full" />
          ))}
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
              <span
                role="button"
                tabIndex={0}
                className="self-center text-xs underline underline-offset-4"
                onClick={(event) => {
                  event.stopPropagation();
                  xhr.current?.abort();
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    event.stopPropagation();
                    xhr.current?.abort();
                  }
                }}
                data-bga-upload-cancel
              >
                Cancel
              </span>
            </span>
          ) : (
            <>
              <Icon aria-hidden className="size-6" />
              <span className="font-medium text-foreground">{words}</span>
              {upload.maxSize && <span className="text-xs">Up to {size(upload.maxSize)}</span>}
            </>
          )}
        </button>
      )}
      {problem && <p className="text-sm text-destructive">{problem}</p>}
    </div>
  );
};
