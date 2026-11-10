"use client";

import { useQueryClient } from "@tanstack/react-query";
import { MessageCircle } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { canUse, type TAppSection, type TRecord, type TRouteParams } from "../app";
import { useOperationMutation, useOperationQuery } from "../bindings";
import { errorMessage } from "../errors";
import { useSession } from "../plugins";
import { recordOf, signal } from "../signals";

type TThread = NonNullable<NonNullable<TAppSection["content"]>["thread"]>;

function when(value: unknown): string {
  const date = typeof value === "string" ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  const minutes = Math.round((Date.now() - date.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
  return date.toLocaleDateString();
}

/** The box that writes a comment, or a reply under one (`parent`). */
function Composer({ thread, target, parent, onDone, autoFocus }: {
  thread: TThread;
  target: unknown;
  parent?: unknown;
  onDone?: () => void;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const queryClient = useQueryClient();
  const create = useOperationMutation(thread.create);
  const label = parent ? "Reply" : "Post";
  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    const body: TRecord = { [thread.target]: target, [thread.text]: text.trim() };
    if (parent) body[thread.parent] = parent;
    create.mutate(
      { params: {}, body },
      {
        onSuccess: (result) => {
          setText("");
          signal("operation", { operationId: thread.create, record: recordOf({}, result) });
          void queryClient.invalidateQueries(); // the thread and the record's comment count
          onDone?.();
        },
        onError: (error) => toast.error(errorMessage(thread.create, error)),
      },
    );
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-2" data-bga-composer={parent ? "reply" : "comment"}>
      <Textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={parent ? "Write a reply…" : "Add a comment…"}
        aria-label={parent ? "Reply" : "Comment"}
        rows={parent ? 2 : 3}
        maxLength={2000}
        autoFocus={autoFocus}
      />
      <div className="flex justify-end gap-2">
        {onDone && parent !== undefined && (
          <Button type="button" variant="ghost" size="sm" onClick={onDone}>
            Cancel
          </Button>
        )}
        <Button type="submit" size="sm" disabled={create.isPending || !text.trim()}>
          {label}
        </Button>
      </div>
    </form>
  );
}

function Comment({ comment, thread, mine, onReply, onDelete }: {
  comment: TRecord;
  thread: TThread;
  mine: boolean;
  onReply?: () => void;
  onDelete?: () => void;
}) {
  return (
    <div className="flex flex-col gap-1" data-bga-comment={String(comment.id)}>
      <div className="text-muted-foreground flex items-baseline gap-2 text-xs">
        <span className="text-foreground font-medium">{mine ? "You" : "Member"}</span>
        <span>{when(comment.createdAt)}</span>
      </div>
      <p className="text-sm whitespace-pre-wrap break-words">{String(comment[thread.text] ?? "")}</p>
      <div className="flex gap-3 text-xs">
        {onReply && (
          <button type="button" className="text-muted-foreground hover:text-foreground font-medium" onClick={onReply}>
            Reply
          </button>
        )}
        {mine && onDelete && (
          <button type="button" className="text-muted-foreground hover:text-destructive" onClick={onDelete}>
            Delete
          </button>
        )}
      </div>
    </div>
  );
}

/** Epic 33 (the comments feature): a record's comments with replies, written and answered where the person is.
 *  Replies sit one level under the comment they answer; answering a reply answers its comment. */
export function CommentThread({ section }: { section: TAppSection }) {
  const thread = section.content?.thread;
  const route = (useParams() ?? {}) as TRouteParams;
  const session = useSession();
  const queryClient = useQueryClient();
  const target = route.id;
  const query = useOperationQuery(thread?.list, thread ? { [thread.target]: target, limit: thread.maxLimit ?? 100 } : {});
  const remove = useOperationMutation(thread?.remove);
  const [replying, setReplying] = useState<unknown>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (!thread) return null;
  const items = ((query.data as { items?: TRecord[] } | undefined)?.items ?? []) as TRecord[];
  const top = items.filter((item) => item[thread.parent] === null || item[thread.parent] === undefined);
  const replies = (id: unknown) => items.filter((item) => item[thread.parent] === id);
  const me = session.user?.id;
  const canWrite = canUse(thread.create, session) && (!session.enabled || Boolean(session.user));

  function del(comment: TRecord) {
    remove.mutate(
      { params: { id: comment.id }, body: {} },
      {
        onSuccess: () => {
          if (thread?.remove) signal("operation", { operationId: thread.remove, record: comment.id });
          void queryClient.invalidateQueries();
        },
        onError: (error) => toast.error(errorMessage(thread?.remove, error)),
      },
    );
  }

  return (
    <div className="flex flex-col gap-5" data-bga-thread>
      <h2 className="flex items-center gap-2 text-base font-semibold">
        <MessageCircle className="size-4" aria-hidden />
        {section.content?.title ?? "Comments"} <span className="text-muted-foreground tabular-nums">{items.length}</span>
      </h2>
      {canWrite && <Composer thread={thread} target={target} />}
      {query.isLoading && <p className="text-muted-foreground text-sm">Loading comments…</p>}
      {!query.isLoading && top.length === 0 && (
        <p className="text-muted-foreground text-sm">No comments yet. Be the first to write one.</p>
      )}
      <ul className="flex flex-col gap-5">
        {top.map((comment) => {
          const answers = replies(comment.id);
          const shown = open[String(comment.id)] ? answers : answers.slice(0, 1);
          return (
            <li key={String(comment.id)} className="flex flex-col gap-3">
              <Comment
                comment={comment}
                thread={thread}
                mine={me !== undefined && comment[thread.owner] === me}
                onReply={canWrite ? () => setReplying(comment.id) : undefined}
                onDelete={thread.remove ? () => del(comment) : undefined}
              />
              {(shown.length > 0 || replying === comment.id) && (
                <div className="border-border ml-4 flex flex-col gap-3 border-l pl-4">
                  {shown.map((reply) => (
                    <Comment
                      key={String(reply.id)}
                      comment={reply}
                      thread={thread}
                      mine={me !== undefined && reply[thread.owner] === me}
                      onReply={canWrite ? () => setReplying(comment.id) : undefined}
                      onDelete={thread.remove ? () => del(reply) : undefined}
                    />
                  ))}
                  {answers.length > shown.length && (
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-foreground w-fit text-xs font-medium"
                      onClick={() => setOpen({ ...open, [String(comment.id)]: true })}
                    >
                      View {answers.length - shown.length} more {answers.length - shown.length === 1 ? "reply" : "replies"}
                    </button>
                  )}
                  {replying === comment.id && (
                    <Composer thread={thread} target={target} parent={comment.id} onDone={() => setReplying(null)} autoFocus />
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
