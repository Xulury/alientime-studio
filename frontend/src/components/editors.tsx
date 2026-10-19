import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Region } from "../lib/types";
import { cx } from "./ui";

/** Keeps an image "contained" in its box, at a chosen zoom, and reports the displayed size. */
function useFit(box: React.RefObject<HTMLDivElement | null>, natural: { w: number; h: number } | null, zoom: number) {
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    if (!box.current || !natural) return;
    const el = box.current;
    const update = () => {
      const pad = 48;
      const s = Math.min((el.clientWidth - pad) / natural.w, (el.clientHeight - pad) / natural.h);
      setSize({ w: natural.w * s * zoom, h: natural.h * s * zoom });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [box, natural, zoom]);
  return size;
}

type Drag =
  | { kind: "draw"; x0: number; y0: number }
  | { kind: "move"; idx: number; dx: number; dy: number }
  | { kind: "resize"; idx: number };

/** Draw, move, resize and delete redaction rectangles (normalised 0..1 coordinates). */
export function RedactionEditor({ src, regions, onChange, selected, onSelect, zoom }: {
  src: string; regions: Region[]; onChange: (r: Region[]) => void; selected: number | null; onSelect: (i: number | null) => void; zoom: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const surface = useRef<HTMLDivElement>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const size = useFit(box, natural, zoom);
  const drag = useRef<Drag | null>(null);
  const [draft, setDraft] = useState<Region | null>(null);

  const pt = (e: React.MouseEvent | MouseEvent) => {
    const r = surface.current!.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  };
  const onMove = useCallback((e: MouseEvent) => {
    const d = drag.current;
    if (!d) return;
    const p = pt(e);
    if (d.kind === "draw") {
      setDraft({ x: Math.min(d.x0, p.x), y: Math.min(d.y0, p.y), w: Math.abs(p.x - d.x0), h: Math.abs(p.y - d.y0), enabled: true });
    } else {
      const next = regions.map((r) => ({ ...r }));
      const r = next[d.idx];
      if (d.kind === "move") {
        r.x = Math.min(1 - r.w, Math.max(0, p.x - d.dx));
        r.y = Math.min(1 - r.h, Math.max(0, p.y - d.dy));
      } else {
        r.w = Math.max(0.005, Math.min(1 - r.x, p.x - r.x));
        r.h = Math.max(0.005, Math.min(1 - r.y, p.y - r.y));
      }
      onChange(next);
    }
  }, [regions, onChange]);
  const onUp = useCallback(() => {
    const d = drag.current;
    drag.current = null;
    if (d?.kind === "draw" && draft && draft.w > 0.006 && draft.h > 0.004) {
      onChange([...regions, draft]);
      onSelect(regions.length);
    }
    setDraft(null);
  }, [draft, regions, onChange, onSelect]);
  useEffect(() => {
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, [onMove, onUp]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === "Delete" || e.key === "Backspace") && selected !== null && !(e.target as HTMLElement).closest("input,textarea")) {
        onChange(regions.filter((_, i) => i !== selected));
        onSelect(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, regions, onChange, onSelect]);

  return (
    <div ref={box} className="size-full overflow-auto scroll-thin grid place-items-center">
      <img src={src} alt="" className="hidden" onLoad={(e) => setNatural({ w: (e.target as HTMLImageElement).naturalWidth, h: (e.target as HTMLImageElement).naturalHeight })} />
      {natural && (
        <div ref={surface} className="relative cursor-crosshair m-6 shrink-0" style={{ width: size.w, height: size.h }}
          onMouseDown={(e) => {
            if (e.button !== 0) return;
            const p = pt(e);
            drag.current = { kind: "draw", x0: p.x, y0: p.y };
            onSelect(null);
          }}>
          <img src={src} alt="Photo with redaction areas" draggable={false} className="absolute inset-0 size-full select-none" />
          {regions.map((r, i) => (
            <div key={r.id ?? `n${i}`}
              className={cx("absolute border-2", r.enabled ? "bg-[#262626]/85" : "bg-transparent border-dashed",
                selected === i ? "border-white z-10" : r.source === "ocr" ? "border-brass-100" : "border-velvet-100")}
              style={{ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%`, cursor: "move" }}
              onMouseDown={(e) => {
                e.stopPropagation();
                const p = pt(e);
                onSelect(i);
                drag.current = { kind: "move", idx: i, dx: p.x - r.x, dy: p.y - r.y };
              }}>
              {selected === i && (
                <span className="absolute -right-1.5 -bottom-1.5 size-3 bg-white border border-ink cursor-nwse-resize"
                  onMouseDown={(e) => { e.stopPropagation(); drag.current = { kind: "resize", idx: i }; }} />
              )}
            </div>
          ))}
          {draft && <div className="absolute border-2 border-white bg-white/20" style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, width: `${draft.w * 100}%`, height: `${draft.h * 100}%` }} />}
        </div>
      )}
    </div>
  );
}

/** Brush editor for the cutout mask. Keep paints the watch back in; Remove erases background. */
export function MaskEditor({ imageSrc, maskSrc, mode, brush, showOverlay, zoom, editorRef }: {
  imageSrc: string; maskSrc: string; mode: "keep" | "remove"; brush: number; showOverlay: boolean; zoom: number;
  editorRef: React.MutableRefObject<{ exportPng: () => Promise<Blob | null>; undo: () => void; dirty: () => boolean } | null>;
}) {
  const box = useRef<HTMLDivElement>(null);
  const view = useRef<HTMLCanvasElement>(null);
  const maskCanvas = useRef<HTMLCanvasElement | null>(null);
  const img = useRef<HTMLImageElement | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const size = useFit(box, natural, zoom);
  const painting = useRef(false);
  const last = useRef<{ x: number; y: number } | null>(null);
  const history = useRef<ImageData[]>([]);
  const changed = useRef(false);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);

  // load image + mask into an editing canvas (max 1600 px long edge; the server rescales)
  useEffect(() => {
    let alive = true;
    const a = new Image();
    const m = new Image();
    let loaded = 0;
    const done = () => {
      if (++loaded < 2 || !alive) return;
      const scale = Math.min(1, 1600 / Math.max(a.naturalWidth, a.naturalHeight));
      const w = Math.round(a.naturalWidth * scale);
      const h = Math.round(a.naturalHeight * scale);
      const mc = document.createElement("canvas");
      mc.width = w;
      mc.height = h;
      const ctx = mc.getContext("2d")!;
      ctx.drawImage(m, 0, 0, w, h);
      const data = ctx.getImageData(0, 0, w, h);
      for (let i = 0; i < data.data.length; i += 4) {
        const v = data.data[i];
        data.data[i] = data.data[i + 1] = data.data[i + 2] = 255;
        data.data[i + 3] = v;
      }
      ctx.putImageData(data, 0, 0);
      maskCanvas.current = mc;
      img.current = a;
      history.current = [];
      changed.current = false;
      setNatural({ w, h });
    };
    a.onload = done;
    m.onload = done;
    a.src = imageSrc;
    m.src = maskSrc;
    return () => { alive = false; };
  }, [imageSrc, maskSrc]);

  const redraw = useCallback(() => {
    const c = view.current;
    const mc = maskCanvas.current;
    if (!c || !mc || !img.current) return;
    c.width = mc.width;
    c.height = mc.height;
    const ctx = c.getContext("2d")!;
    ctx.drawImage(img.current, 0, 0, mc.width, mc.height);
    if (showOverlay) {
      const o = document.createElement("canvas");
      o.width = mc.width;
      o.height = mc.height;
      const octx = o.getContext("2d")!;
      octx.fillStyle = "rgba(205, 52, 40, 0.55)";
      octx.fillRect(0, 0, o.width, o.height);
      octx.globalCompositeOperation = "destination-out";
      octx.drawImage(mc, 0, 0);
      ctx.drawImage(o, 0, 0);
    }
  }, [showOverlay]);
  useEffect(() => { redraw(); }, [redraw, natural]);

  const toCanvas = (e: React.MouseEvent) => {
    const r = view.current!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * view.current!.width, y: ((e.clientY - r.top) / r.height) * view.current!.height };
  };
  const stroke = (from: { x: number; y: number }, to: { x: number; y: number }) => {
    const mc = maskCanvas.current!;
    const ctx = mc.getContext("2d")!;
    const radius = (brush / 100) * Math.max(mc.width, mc.height) * 0.06 + 2;
    ctx.save();
    ctx.globalCompositeOperation = mode === "keep" ? "source-over" : "destination-out";
    ctx.strokeStyle = "rgba(255,255,255,1)";
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = radius * 2;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x + 0.01, to.y + 0.01);
    ctx.stroke();
    ctx.restore();
    changed.current = true;
    redraw();
  };

  editorRef.current = {
    dirty: () => changed.current,
    undo: () => {
      const prev = history.current.pop();
      if (prev && maskCanvas.current) {
        maskCanvas.current.getContext("2d")!.putImageData(prev, 0, 0);
        changed.current = history.current.length > 0;
        redraw();
      }
    },
    exportPng: () => new Promise((resolve) => {
      const mc = maskCanvas.current;
      if (!mc) return resolve(null);
      const out = document.createElement("canvas");
      out.width = mc.width;
      out.height = mc.height;
      const src = mc.getContext("2d")!.getImageData(0, 0, mc.width, mc.height);
      const ctx = out.getContext("2d")!;
      const dst = ctx.createImageData(mc.width, mc.height);
      for (let i = 0; i < src.data.length; i += 4) {
        const a = src.data[i + 3];
        dst.data[i] = dst.data[i + 1] = dst.data[i + 2] = a;
        dst.data[i + 3] = 255;
      }
      ctx.putImageData(dst, 0, 0);
      out.toBlob((b) => resolve(b), "image/png");
    }),
  };

  const radiusPx = natural && size.w ? ((brush / 100) * Math.max(natural.w, natural.h) * 0.06 + 2) * (size.w / natural.w) : 10;
  return (
    <div ref={box} className="size-full overflow-auto scroll-thin grid place-items-center">
      {natural ? (
        <div className="relative m-6 shrink-0" style={{ width: size.w, height: size.h }}>
          <canvas ref={view} className="size-full cursor-none" style={{ imageRendering: "auto" }}
            onMouseDown={(e) => {
              const mc = maskCanvas.current!;
              history.current.push(mc.getContext("2d")!.getImageData(0, 0, mc.width, mc.height));
              if (history.current.length > 15) history.current.shift();
              painting.current = true;
              last.current = toCanvas(e);
              stroke(last.current, last.current);
            }}
            onMouseMove={(e) => {
              const r = view.current!.getBoundingClientRect();
              setCursor({ x: e.clientX - r.left, y: e.clientY - r.top });
              if (!painting.current) return;
              const p = toCanvas(e);
              stroke(last.current!, p);
              last.current = p;
            }}
            onMouseUp={() => { painting.current = false; }}
            onMouseLeave={() => { painting.current = false; setCursor(null); }} />
          {cursor && <div className={cx("pointer-events-none absolute rounded-full border-2", mode === "keep" ? "border-white" : "border-[#ff8a7a]")}
            style={{ left: cursor.x - radiusPx, top: cursor.y - radiusPx, width: radiusPx * 2, height: radiusPx * 2 }} />}
        </div>
      ) : <div className="text-white/60 text-[13px]">Loading cutout…</div>}
    </div>
  );
}
