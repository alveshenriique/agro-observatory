// Every meaningful JavaScript animation (the map timeline, chart transitions) must
// consult this hook: decorative CSS motion is already suppressed globally (technique
// C39 in global.css), but canvas and JS-driven animation only stops if the code asks.
// With reduced motion, "play" must advance in discrete steps instead of tweening.
import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function initialValue(): boolean {
  // matchMedia is absent in some non-browser environments; default to reduced motion
  // being off only when the preference is genuinely unknown.
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(QUERY).matches;
}

export function usePrefersReducedMotion(): boolean {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(initialValue);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      return;
    }
    const mediaQuery = window.matchMedia(QUERY);
    const onChange = (event: MediaQueryListEvent) => {
      setPrefersReducedMotion(event.matches);
    };
    mediaQuery.addEventListener("change", onChange);
    return () => mediaQuery.removeEventListener("change", onChange);
  }, []);

  return prefersReducedMotion;
}
