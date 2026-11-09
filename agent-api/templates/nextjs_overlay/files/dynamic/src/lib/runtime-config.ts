/** Read at runtime from the server environment (`MOCK_TEST_API`, `API_BASE_URL`, `AUTH_TOKEN_STORAGE`), so switching
 *  the frontend from mocks to the live API needs a restart, not a rebuild. */
export type TRuntimeConfig = {
  mockApi: boolean;
  apiBaseUrl: string;
  /** Story 22.7 (decision P8): where a signed-in user's token lives: `local` (localStorage, a bearer header) or
   *  `cookie` (an httpOnly cookie the Next server sets; calls go through its `/api/backend` proxy). */
  authTokenStorage: "local" | "cookie";
};

let pending: Promise<TRuntimeConfig> | null = null;

/** Story 28.6: a browser that must run on the mock API whatever the server says (the evaluation plays the guided
 *  tour without creating real records). Set only by the agent's own browser, never by the app. */
export const MOCK_API_OVERRIDE = "bga-mock-api";

function forcedMocks(): boolean {
  try {
    return typeof window !== "undefined" && window.localStorage.getItem(MOCK_API_OVERRIDE) === "1";
  } catch {
    return false;
  }
}

export function loadRuntimeConfig(): Promise<TRuntimeConfig> {
  pending ??= fetch("/api/runtime-config", { cache: "no-store" })
    .then((response) => response.json() as Promise<TRuntimeConfig>)
    .catch(() => ({ mockApi: true, apiBaseUrl: "", authTokenStorage: "local" as const }))
    .then((config) => (forcedMocks() ? { ...config, mockApi: true, apiBaseUrl: "", authTokenStorage: "local" as const } : config));
  return pending;
}
