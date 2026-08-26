import { useEffect, useRef } from "react";

type Particle = { x: number; y: number; tx: number; ty: number; phase: number; size: number; tone: number };
const rand = (min: number, max: number) => min + Math.random() * (max - min);

function drawGhost(ctx: CanvasRenderingContext2D, width: number, height: number) {
  const scale = Math.min(width / 860, height / 600);
  ctx.save();
  ctx.translate(width - 410 * scale, height * 0.46);
  ctx.scale(scale, scale);
  ctx.beginPath();
  ctx.moveTo(-170, 185);
  ctx.bezierCurveTo(-115, 110, -135, -72, -58, -170);
  ctx.bezierCurveTo(14, -262, 182, -232, 230, -113);
  ctx.bezierCurveTo(284, 21, 240, 188, 158, 250);
  ctx.bezierCurveTo(98, 295, 56, 270, 37, 220);
  ctx.bezierCurveTo(-27, 279, -106, 292, -145, 246);
  ctx.bezierCurveTo(-165, 222, -166, 199, -170, 185);
  ctx.closePath();
  ctx.fill();
  ctx.globalCompositeOperation = "destination-out";
  ctx.beginPath();
  ctx.ellipse(30, -82, 22, 39, 0, 0, Math.PI * 2);
  ctx.ellipse(116, -82, 22, 39, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function sampleTargets(width: number, height: number, mode: number) {
  const mask = document.createElement("canvas");
  mask.width = Math.max(1, Math.floor(width));
  mask.height = Math.max(1, Math.floor(height));
  const ctx = mask.getContext("2d", { willReadFrequently: true });
  if (!ctx) return [] as Array<[number, number]>;
  ctx.fillStyle = "#fff";
  if (mode % 2 === 0) {
    const size = Math.min(height * 0.52, width * 0.3);
    ctx.font = `800 ${size}px "Space Grotesk", Inter, sans-serif`;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText("KYN", width * 0.99, height * 0.48);
  } else drawGhost(ctx, width, height);
  const pixels = ctx.getImageData(0, 0, mask.width, mask.height).data;
  const step = Math.max(7, Math.round(Math.min(width, height) / 92));
  const points: Array<[number, number]> = [];
  for (let y = step; y < height - step; y += step) {
    for (let x = step; x < width - step; x += step) {
      if (pixels[(Math.floor(y) * mask.width + Math.floor(x)) * 4 + 3] > 80) points.push([x, y]);
    }
  }
  for (let i = points.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [points[i], points[j]] = [points[j], points[i]];
  }
  return points.slice(0, 1900);
}

export function PixelKiro() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let particles: Particle[] = [];
    let frame = 0;
    let mode = 0;
    let started = performance.now();
    let raf = 0;
    let visible = true;

    const retarget = (reset = false) => {
      const rect = canvas.getBoundingClientRect();
      const points = sampleTargets(rect.width, rect.height, mode);
      const old = particles;
      particles = points.map(([tx, ty], index) => {
        const previous = old[index % Math.max(old.length, 1)];
        return {
          x: reset || !previous ? rand(rect.width * 0.58, rect.width * 1.12) : previous.x,
          y: reset || !previous ? rand(-rect.height * 0.08, rect.height * 1.08) : previous.y,
          tx, ty, phase: rand(0, Math.PI * 2), size: rand(0.65, 1.75), tone: Math.random(),
        };
      });
      started = performance.now();
    };
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      retarget(true);
    };
    const draw = (time: number) => {
      if (!visible) { raf = requestAnimationFrame(draw); return; }
      const rect = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);
      const elapsed = (time - started) / 1000;
      if (!reduced.matches && elapsed > 4.8) { mode += 1; retarget(); }
      const settle = reduced.matches ? 1 : Math.min(1, elapsed / 1.45);
      for (let i = 0; i < particles.length; i += 1) {
        const p = particles[i];
        p.x += (p.tx - p.x) * (0.026 + settle * 0.045);
        p.y += (p.ty - p.y) * (0.026 + settle * 0.045);
        const x = p.x + (reduced.matches ? 0 : Math.sin(time * 0.00072 + p.phase) * 2.2);
        const y = p.y + (reduced.matches ? 0 : Math.cos(time * 0.00054 + p.phase) * 1.6);
        const alpha = 0.32 + settle * (0.38 + p.tone * 0.42);
        ctx.fillStyle = p.tone > 0.84
          ? `rgba(94,225,255,${alpha * 0.88})`
          : `rgba(${150 + Math.round(p.tone * 60)},${72 + Math.round(p.tone * 40)},255,${alpha})`;
        ctx.fillRect(x, y, p.size, p.size);
        if (!reduced.matches && i % 47 === frame % 47 && settle < 0.95) {
          ctx.strokeStyle = `rgba(167,105,255,${0.09 * (1 - settle)})`;
          ctx.lineWidth = 0.55;
          ctx.beginPath(); ctx.moveTo(rect.width + 30, y); ctx.lineTo(x, y); ctx.stroke();
        }
      }
      frame += 1;
      raf = requestAnimationFrame(draw);
    };
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; });
    const resizeObserver = new ResizeObserver(resize);
    observer.observe(canvas); resizeObserver.observe(canvas); resize();
    raf = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(raf); observer.disconnect(); resizeObserver.disconnect(); };
  }, []);
  return <canvas ref={canvasRef} className="ed-pixel-kiro" aria-hidden="true" />;
}
