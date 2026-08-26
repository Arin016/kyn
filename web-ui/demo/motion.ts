/** Lightweight easing helpers for browser-recorded demo (no Remotion). */

export function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

export function interpolate(
  value: number,
  inputRange: number[],
  outputRange: number[],
  easing?: (t: number) => number,
): number {
  if (inputRange.length !== outputRange.length || inputRange.length < 2) {
    throw new Error("inputRange and outputRange must have the same length (>= 2)");
  }
  if (value <= inputRange[0]) return outputRange[0];
  const last = inputRange.length - 1;
  if (value >= inputRange[last]) return outputRange[last];
  for (let i = 0; i < last; i++) {
    const a = inputRange[i];
    const b = inputRange[i + 1];
    if (value >= a && value <= b) {
      const t = clamp01((value - a) / (b - a));
      const eased = easing ? easing(t) : t;
      return outputRange[i] + (outputRange[i + 1] - outputRange[i]) * eased;
    }
  }
  return outputRange[last];
}

export function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/** Cheap spring-ish curve keyed by frames since trigger. */
export function springProgress(frameSince: number, fps: number): number {
  if (frameSince <= 0) return 0;
  const t = frameSince / fps;
  const omega = 12;
  const decay = 6;
  return clamp01(1 - Math.exp(-decay * t) * Math.cos(omega * t));
}
