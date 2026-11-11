// The hook must read the initial preference and follow changes while mounted.
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { usePrefersReducedMotion } from "../src/lib/usePrefersReducedMotion";

type Listener = (event: { matches: boolean }) => void;

function mockMatchMedia(initialMatches: boolean) {
  const listeners = new Set<Listener>();
  const mediaQuery = {
    matches: initialMatches,
    media: "(prefers-reduced-motion: reduce)",
    addEventListener: (_type: string, listener: Listener) => listeners.add(listener),
    removeEventListener: (_type: string, listener: Listener) => listeners.delete(listener),
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => mediaQuery),
  );
  return {
    emit(matches: boolean) {
      mediaQuery.matches = matches;
      for (const listener of listeners) listener({ matches });
    },
    listeners,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("usePrefersReducedMotion", () => {
  it("reads the initial preference", () => {
    mockMatchMedia(true);
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(true);
  });

  it("follows changes to the preference", () => {
    const media = mockMatchMedia(false);
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(false);
    act(() => media.emit(true));
    expect(result.current).toBe(true);
    act(() => media.emit(false));
    expect(result.current).toBe(false);
  });

  it("removes the listener on unmount", () => {
    const media = mockMatchMedia(false);
    const { unmount } = renderHook(() => usePrefersReducedMotion());
    expect(media.listeners.size).toBe(1);
    unmount();
    expect(media.listeners.size).toBe(0);
  });

  it("defaults to no reduction when matchMedia is unavailable", () => {
    vi.stubGlobal("matchMedia", undefined);
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(false);
  });
});
