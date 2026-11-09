"use client";

import { useSyncExternalStore } from "react";

/** Story 29.4: what the listening bar plays: one audio file for the whole app, so it keeps playing across pages
 *  and only one plays at a time. Compact players hand their file here; the bar owns the `<audio>` element. */
export type TListening = { src: string; title: string; href?: string | null } | null;

type TState = { current: TListening; playing: boolean };

let state: TState = { current: null, playing: false };
const listeners = new Set<() => void>();

function set(next: TState) {
  state = next;
  for (const listener of listeners) listener();
}

export function listen(next: TListening): void {
  set({ current: next, playing: next !== null });
}

export function setPlaying(value: boolean): void {
  set({ ...state, playing: value });
}

export function stopListening(): void {
  set({ current: null, playing: false });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const snapshot = () => state;

export function useListening(): TState {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
