"use client";

import { useQuery, type QueryClient } from "@tanstack/react-query";
import { app, type TRecord, type TSession } from "@/components/app/app";
import { ApiError, request } from "@/lib/api/client";
import { clearToken, readToken, storeToken } from "@/lib/auth/token";
import { loadRuntimeConfig } from "@/lib/runtime-config";

/** The React Query key of the signed-in user (`auth.me`). */
export const SESSION_KEY = ["session"] as const;

/** `cookie` mode on the live API (decision P8): the Next server holds the token; the browser never sees it. On the
 *  mock API both modes keep it in the browser (MSW cannot set httpOnly cookies). */
async function cookieMode(): Promise<boolean> {
  const config = await loadRuntimeConfig();
  return !config.mockApi && config.authTokenStorage === "cookie";
}

/** `cookie` mode: whether the server set a session (its readable marker; the token itself is httpOnly). */
function signedInMarker(): boolean {
  return typeof document !== "undefined" && document.cookie.split("; ").includes("bga_signed_in=1");
}

async function me(): Promise<TRecord | null> {
  const auth = app.auth;
  if (!auth) return null;
  const hasSession = (await cookieMode()) ? signedInMarker() : Boolean(readToken());
  if (!hasSession) return null; // signed out: nothing to ask the backend
  try {
    return await request<TRecord>("GET", auth.me.path);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      clearToken();
      return null;
    }
    throw error;
  }
}

/** The signed-in user (`auth.me`), shared by the whole app. */
export function useSession(): TSession {
  const query = useQuery({ queryKey: SESSION_KEY, queryFn: me, staleTime: 60_000, retry: false });
  return { enabled: true, ready: !query.isPending, user: (query.data as TSession["user"]) ?? null };
}

/** A call to the Next server's auth routes (`cookie` mode); its errors are the backend's. */
async function serverAuth(path: string, body?: Record<string, unknown>): Promise<void> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string; details?: unknown } } | null;
    const error = payload?.error;
    throw new ApiError(response.status, error?.code ?? "HTTP_ERROR", error?.message ?? response.statusText, error?.details ?? null);
  }
}

export async function signIn(values: Record<string, unknown>): Promise<void> {
  const auth = app.auth;
  if (!auth) return;
  if (await cookieMode()) return serverAuth("/api/auth/login", values);
  const token = await request<{ accessToken: string }>("POST", auth.login.path, { body: values });
  storeToken(token.accessToken);
}

/** A new account, then signed in with it. */
export async function signUp(values: Record<string, unknown>): Promise<void> {
  const auth = app.auth;
  if (!auth?.register.path) return;
  if (await cookieMode()) return serverAuth("/api/auth/register", values);
  await request("POST", auth.register.path, { body: values });
  await signIn({ [auth.loginField]: values[auth.loginField], password: values.password });
}

export async function signOut(): Promise<void> {
  if (await cookieMode()) await serverAuth("/api/auth/logout");
  clearToken();
}

/** Where to go after signing in: the page the user was sent from, never another site. */
/** Story 23.10: where a signed-in user lands without a `next`: the home of the area their role belongs to. */
export async function homePath(queryClient: QueryClient): Promise<string> {
  const user = await queryClient.fetchQuery({ queryKey: SESSION_KEY, queryFn: me }).catch(() => null);
  const role = user && typeof user.role === "string" ? user.role : null;
  const area = role ? (app.areas ?? []).find((candidate) => candidate.roles.includes(role)) : undefined;
  return area?.prefix ?? "/";
}

export function nextPath(fallback = "/"): string {
  if (typeof window === "undefined") return fallback;
  const next = new URLSearchParams(window.location.search).get("next");
  return next && next.startsWith("/") && !next.startsWith("//") ? next : fallback;
}

/** Story 28.5 ("Continue as <role>"): signs in as one of the demo accounts the sign-in page lists, so a demo can
 *  follow a workflow across roles in one browser. False when the app has no demo accounts or the sign-in failed. */
export async function signInDemo(login: string, queryClient: QueryClient): Promise<boolean> {
  const auth = app.auth;
  const user = auth?.demoUsers.find((candidate) => candidate.login === login);
  if (!auth || !user || !auth.password) return false;
  try {
    await signOut();
    await signIn({ [auth.loginField]: user.login, password: auth.password });
    await queryClient.invalidateQueries();
    return true;
  } catch {
    return false;
  }
}
