import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Stick-to-bottom scroll physics: pinned while the user is at the bottom,
 * released the moment they scroll up. Returns [ref, stuck, scrollToLatest].
 * Scroll handling is rAF-batched; consumers notify via `bump()` when content
 * grows so we re-pin without per-token scroll thrash.
 */
export function useStickToBottom(threshold = 80) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stuckRef = useRef(true);
  const rafRef = useRef(0);
  const [stuck, setStuck] = useState(true);

  const measure = useCallback(() => {
    const node = containerRef.current;
    if (!node) return;
    const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
    const nowStuck = distance <= threshold;
    if (nowStuck !== stuckRef.current) {
      stuckRef.current = nowStuck;
      setStuck(nowStuck);
    }
  }, [threshold]);

  const onScroll = useCallback(() => {
    if (rafRef.current) return;
    rafRef.current = window.requestAnimationFrame(() => {
      rafRef.current = 0;
      measure();
    });
  }, [measure]);

  const scrollToLatest = useCallback((behavior: ScrollBehavior = "smooth") => {
    const node = containerRef.current;
    if (!node) return;
    node.scrollTo({ top: node.scrollHeight, behavior });
    stuckRef.current = true;
    setStuck(true);
  }, []);

  /** Re-pin the view if the user hasn't scrolled away. Call after content changes. */
  const bump = useCallback(() => {
    if (stuckRef.current) scrollToLatest("auto");
  }, [scrollToLatest]);

  useEffect(() => () => {
    if (rafRef.current) window.cancelAnimationFrame(rafRef.current);
  }, []);

  return { containerRef, stuck, onScroll, bump, scrollToLatest };
}
