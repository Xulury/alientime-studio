import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Maximize2, Minus, Plus } from "lucide-react";
import { cx } from "./ui";

/** Zoom (wheel / buttons) and pan (drag) shared by the viewers. */
function useZoomPan() {
  const [scale, setScale] = useState(1);
  const [tx, setTx] = useState(0);
  const [ty, setTy] = useState(0);
  const reset = useCallback(() => { setScale(1); setTx(0); setTy(0); }, []);
  const zoomAt = useCallback((factor: number, cx = 0, cy = 0) => {
    setScale((s) => {
      const next = Math.min(8, Math.max(1, s * factor));
      const k = next / s;
      setTx((x) => (next === 1 ? 0 : cx - (cx - x) * k));
      setTy((y) => (next === 1 ? 0 : cy - (cy - y) * k));
      return next;
    });
  }, []);
  return { scale, tx, ty, setTx, setTy, reset, zoomAt };
}

function ZoomControls({ scale, onIn, onOut, onReset, dark = true }: { scale: number; onIn: () => void; onOut: () => void; onReset: () => void; dark?: boolean }) {
  const btn = cx("size-8 grid place-items-center rounded-md cursor-pointer", dark ? "hover:bg-white/10 text-white/80" : "hover:bg-wash text-ink-2");
  return (
    <div className={cx("absolute bottom-3 right-3 z-10 flex items-center gap-0.5 rounded-lg p-1 backdrop-blur", dark ? "bg-stage/80 border border-stage-line" : "bg-surface/90 border border-line")}>
      <button className={btn} onClick={onOut} aria-label="Zoom out"><Minus className="size-4" /></button>
      <span className={cx("w-12 text-center text-[12px] tabular-nums", dark ? "text-white/70" : "text-steel")}>{Math.round(scale * 100)}%</span>
      <button className={btn} onClick={onIn} aria-label="Zoom in"><Plus className="size-4" /></button>
      <button className={btn} onClick={onReset} aria-label="Fit to screen"><Maximize2 className="size-4" /></button>
    </div>
  );
}

/** One image, zoomable and pannable, on the dark stage. */
export function ZoomView({ src, alt, children, checker }: { src: string; alt: string; children?: ReactNode; checker?: boolean }) {
  const z = useZoomPan();
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);
  useEffect(() => z.reset(), [src]); // eslint-disable-line
  const onWheel = (e: React.WheelEvent) => {
    const r = box.current!.getBoundingClientRect();
    z.zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2);
  };
  return (
    <div ref={box} className={cx("relative size-full overflow-hidden select-none", checker && "checker-dark", z.scale > 1 ? "cursor-grab active:cursor-grabbing" : "")}
      onWheel={onWheel}
      onMouseDown={(e) => { drag.current = { x: e.clientX - z.tx, y: e.clientY - z.ty }; }}
      onMouseMove={(e) => { if (drag.current && z.scale > 1) { z.setTx(e.clientX - drag.current.x); z.setTy(e.clientY - drag.current.y); } }}
      onMouseUp={() => (drag.current = null)} onMouseLeave={() => (drag.current = null)}>
      <div className="absolute inset-0 flex items-center justify-center p-6" style={{ transform: `translate(${z.tx}px, ${z.ty}px) scale(${z.scale})`, transformOrigin: "center" }}>
        <img src={src} alt={alt} draggable={false} className="max-w-full max-h-full object-contain shadow-[0_20px_60px_-25px_rgba(0,0,0,0.8)]" />
        {children}
      </div>
      <ZoomControls scale={z.scale} onIn={() => z.zoomAt(1.5)} onOut={() => z.zoomAt(1 / 1.5)} onReset={z.reset} />
    </div>
  );
}

/** Before/after slider. Both images must share the same framing (the studio serves an aligned "before"). */
export function CompareView({ before, after, beforeLabel = "Original", afterLabel = "Studio" }: { before: string; after: string; beforeLabel?: string; afterLabel?: string }) {
  const z = useZoomPan();
  const [split, setSplit] = useState(50);
  const box = useRef<HTMLDivElement>(null);
  const mode = useRef<"split" | "pan" | null>(null);
  const start = useRef({ x: 0, y: 0 });
  const [ratio, setRatio] = useState<number | null>(null);
  useEffect(() => { z.reset(); setSplit(50); }, [after]); // eslint-disable-line

  const splitFromEvent = (clientX: number) => {
    const img = box.current?.querySelector("img[data-after]") as HTMLImageElement | null;
    if (!img) return;
    const r = img.getBoundingClientRect();
    setSplit(Math.min(100, Math.max(0, ((clientX - r.left) / r.width) * 100)));
  };
  return (
    <div ref={box} className="relative size-full overflow-hidden select-none"
      onWheel={(e) => {
        const r = box.current!.getBoundingClientRect();
        z.zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2);
      }}
      onMouseDown={(e) => {
        const onHandle = (e.target as HTMLElement).dataset.handle === "1";
        mode.current = onHandle || z.scale === 1 ? "split" : "pan";
        start.current = { x: e.clientX - z.tx, y: e.clientY - z.ty };
        if (mode.current === "split") splitFromEvent(e.clientX);
      }}
      onMouseMove={(e) => {
        if (mode.current === "split") splitFromEvent(e.clientX);
        else if (mode.current === "pan") { z.setTx(e.clientX - start.current.x); z.setTy(e.clientY - start.current.y); }
      }}
      onMouseUp={() => (mode.current = null)} onMouseLeave={() => (mode.current = null)}
      onTouchMove={(e) => splitFromEvent(e.touches[0].clientX)}
      tabIndex={0} role="slider" aria-label="Before and after comparison" aria-valuenow={Math.round(split)} aria-valuemin={0} aria-valuemax={100}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") setSplit((s) => Math.max(0, s - 5));
        if (e.key === "ArrowRight") setSplit((s) => Math.min(100, s + 5));
      }}>
      <div className={cx("absolute inset-0 flex items-center justify-center p-6", z.scale > 1 ? "cursor-grab" : "cursor-ew-resize")}
        style={{ transform: `translate(${z.tx}px, ${z.ty}px) scale(${z.scale})` }}>
        <div className="relative max-w-full max-h-full" style={ratio ? { aspectRatio: String(ratio), height: "100%" } : { height: "100%" }}>
          <img data-after src={after} alt="Studio image" draggable={false} className="block h-full w-auto max-w-full object-contain"
            onLoad={(e) => setRatio((e.target as HTMLImageElement).naturalWidth / (e.target as HTMLImageElement).naturalHeight)} />
          <img src={before} alt="Original photo, same framing" draggable={false} className="absolute inset-0 h-full w-full object-contain"
            style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }} />
          <div className="absolute inset-y-0" style={{ left: `${split}%` }}>
            <div className="absolute inset-y-0 -ml-px w-0.5 bg-white/90 shadow-[0_0_10px_rgba(0,0,0,0.5)]" />
            <div data-handle="1" className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 size-9 rounded-full bg-white text-ink grid place-items-center shadow-lg cursor-ew-resize text-[11px] font-semibold">
              <span data-handle="1">⟷</span>
            </div>
          </div>
        </div>
      </div>
      <div className="absolute top-3 left-3 z-10 rounded-md bg-stage/80 px-2 py-1 text-[12px] text-white/80">{beforeLabel}</div>
      <div className="absolute top-3 right-3 z-10 rounded-md bg-stage/80 px-2 py-1 text-[12px] text-white/80">{afterLabel}</div>
      <ZoomControls scale={z.scale} onIn={() => z.zoomAt(1.5)} onOut={() => z.zoomAt(1 / 1.5)} onReset={z.reset} />
    </div>
  );
}
