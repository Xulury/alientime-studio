import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Brush, Check, ChevronLeft, ChevronRight, Download, Eraser, Eye, EyeOff, RefreshCw, RotateCcw, ScanText, ShieldCheck, Trash2, Undo2, X,
} from "lucide-react";
import { get, patch, post, put, uploadFiles, errorMessage } from "../lib/api";
import { keys, useAction, useWatch } from "../lib/hooks";
import { BACKGROUNDS, PHOTO_TYPES, ago, bytes } from "../lib/format";
import type { AssetDetail, Region } from "../lib/types";
import { CompareView, ZoomView } from "../components/viewers";
import { MaskEditor, RedactionEditor } from "../components/editors";
import { Pill, SAFETY_TONE, Spinner, cx, useConfirm, useToast } from "../components/ui";

type Stage = "inspect" | "privacy" | "cutout" | "studio" | "result";
const NEEDS_PRIVACY_CHECK = ["needs_review", "ocr_unavailable", "failed"];
const REGION_LABELS: Record<string, string> = {
  serial_like: "Serial-like number", numbered_marking: "Numbered marking (No. …)", edition_number: "Edition number (… / 99)",
  long_number: "Long number", dense_engraving: "Dense engraving",
};
const regionLabel = (category?: string | null) =>
  category ? category.split(/,\s*/).map((c) => REGION_LABELS[c] ?? c.replace(/_/g, " ")).join(" · ") : "Found by the serial scan";
const STAGES: Array<{ key: Stage; label: string }> = [
  { key: "inspect", label: "Inspection" }, { key: "privacy", label: "Privacy" }, { key: "cutout", label: "Cutout" },
  { key: "studio", label: "Studio" }, { key: "result", label: "Result" },
];

// ---- small dark-theme controls ------------------------------------------------------------------
function DBtn({ children, onClick, primary, disabled, loading, icon, title, danger }: {
  children?: ReactNode; onClick?: () => void; primary?: boolean; disabled?: boolean; loading?: boolean; icon?: ReactNode; title?: string; danger?: boolean;
}) {
  return (
    <button title={title} onClick={onClick} disabled={disabled || loading}
      className={cx("inline-flex items-center justify-center gap-2 h-9 px-3 rounded-md text-[13px] font-medium transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed",
        primary ? "bg-velvet hover:bg-[#25604a] text-white" : danger ? "bg-transparent border border-[#7a3027] text-[#f0a397] hover:bg-[#3a1d19]" : "bg-stage-3 hover:bg-[#2f3833] text-white/90 border border-stage-line")}>
      {loading ? <Spinner className="text-white" /> : icon}{children}
    </button>
  );
}
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="py-4 border-b border-stage-line last:border-b-0">
      <h3 className="text-[12.5px] font-semibold text-white/60 mb-2.5">{title}</h3>
      {children}
    </section>
  );
}
function Slider({ label, value, min, max, step, onChange, format }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; format?: (v: number) => string }) {
  return (
    <label className="block mb-3">
      <span className="flex justify-between text-[12.5px] text-white/70 mb-1"><span>{label}</span><span className="tabular-nums">{format ? format(value) : value}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-[#3c8a69]" />
    </label>
  );
}
function Metric({ label, value, warn }: { label: string; value: ReactNode; warn?: boolean }) {
  return <div className="flex justify-between gap-3 py-1 text-[13px]"><span className="text-white/55">{label}</span><span className={cx("tabular-nums text-right", warn ? "text-[#e7c27d]" : "text-white/90")}>{value}</span></div>;
}

const SWATCH: Record<string, string> = {
  green_velvet: "radial-gradient(circle at 35% 30%, #2f6f52, #163a2b 70%)",
  studio_white: "radial-gradient(circle, #fafaf8, #e5e5e2)",
  studio_grey: "radial-gradient(circle, #dadbd9, #b2b3b1)",
  studio_black: "radial-gradient(circle, #2c2d2f, #0b0b0c)",
  cleanup: "linear-gradient(135deg, #c8c3b9, #8d877c)",
  keep_original: "linear-gradient(135deg, #a3a19b 50%, #5e5b55 50%)",
  ai_velvet: "radial-gradient(circle at 35% 30%, #3a7d5f, #10291f 70%)",
  ai_studio: "radial-gradient(circle, #f1f1ef, #c9c9c6)",
  auto: "conic-gradient(#1e4d3a 0 50%, #e5e5e2 0)",
};

export default function StudioEditor() {
  const { id = "", assetId = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const watch = useWatch(id);
  const [params] = useSearchParams();
  const askedStage = STAGES.some((x) => x.key === params.get("stage")) ? (params.get("stage") as Stage) : null;
  const [stage, setStage] = useState<Stage>(askedStage ?? "result");
  const assetQ = useQuery({
    queryKey: keys.asset(assetId),
    queryFn: () => get<AssetDetail>(`/api/assets/${assetId}`),
    refetchInterval: (q) => (["queued", "processing"].includes(q.state.data?.pipeline_status ?? "") ? 1500 : false),
  });
  const a = assetQ.data;
  const assets = watch.data?.assets ?? [];
  const idx = assets.findIndex((x) => x.id === assetId);
  const job = watch.data?.jobs.find((j) => j.asset_id === assetId && (j.status === "pending" || j.status === "running"));
  const busy = !!job || ["queued", "processing"].includes(a?.pipeline_status ?? "");
  const wasBusy = useRef(busy);
  useEffect(() => {
    if (wasBusy.current && !busy) {
      qc.invalidateQueries({ queryKey: keys.asset(assetId) });
      qc.invalidateQueries({ queryKey: keys.watch(id) });
    }
    wasBusy.current = busy;
  }, [busy, assetId, id, qc]);
  useEffect(() => {
    if (!a) return;
    if (askedStage) setStage(askedStage);
    else if (NEEDS_PRIVACY_CHECK.includes(a.safety_status)) setStage("privacy");
    else if (!a.render) setStage(a.safety_status === "pending" ? "inspect" : "studio");
    else setStage("result");
  }, [a?.id]); // eslint-disable-line
  const go = (d: number) => {
    const n = assets[idx + d];
    if (n) navigate(`/watches/${id}/studio/${n.id}`, { replace: true });
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input,textarea,select")) return;
      if (e.key === "ArrowRight" && e.altKey) go(1);
      if (e.key === "ArrowLeft" && e.altKey) go(-1);
      if (e.key === "Escape") navigate(`/watches/${id}/photos`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  const inv = [keys.asset(assetId), keys.watch(id), keys.review(id)];

  // ---- privacy state
  const [regions, setRegions] = useState<Region[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [showRedacted, setShowRedacted] = useState(false);
  const [zoom, setZoom] = useState(1);
  useEffect(() => { setRegions(a?.regions ?? []); setSelected(null); }, [a?.id, a?.regions?.length, JSON.stringify(a?.regions)]); // eslint-disable-line
  const regionsDirty = JSON.stringify(regions.map(({ x, y, w, h, enabled }) => ({ x, y, w, h, enabled }))) !==
    JSON.stringify((a?.regions ?? []).map(({ x, y, w, h, enabled }) => ({ x, y, w, h, enabled })));
  const saveRegions = useAction(() => put(`/api/assets/${assetId}/regions`, { regions: regions.map(({ id: rid, x, y, w, h, enabled }) => ({ id: rid, x, y, w, h, enabled })) }), {
    success: "Redactions saved and re-checked. Render the photo again to use them.", invalidate: inv,
  });
  const rescan = useAction(() => post(`/api/assets/${assetId}/rescan`), { success: "Scanning again for serial numbers…", invalidate: inv });
  const checked = useAction(() => post(`/api/assets/${assetId}/privacy-review`, { confirm: true }), { success: "Marked as checked", invalidate: inv });

  // ---- cutout state
  const maskRef = useRef<{ exportPng: () => Promise<Blob | null>; undo: () => void; dirty: () => boolean } | null>(null);
  const [brushMode, setBrushMode] = useState<"keep" | "remove">("remove");
  const [brush, setBrush] = useState(30);
  const [overlay, setOverlay] = useState(true);
  const [previewCut, setPreviewCut] = useState(false);
  const [savingMask, setSavingMask] = useState(false);
  const resegment = useAction(() => post(`/api/assets/${assetId}/mask/reset`), { success: "Cutting out again automatically…", invalidate: inv });

  // ---- studio state
  const [settings, setSettings] = useState<Record<string, any>>({});
  useEffect(() => {
    if (!a) return;
    const r = a.studio_resolved;
    setSettings({
      background: a.studio_settings.background ?? "auto", white_balance_strength: r.white_balance_strength ?? 0.6,
      auto_exposure: r.auto_exposure ?? true, exposure_ev: r.exposure_ev ?? 0, contrast: r.contrast ?? 0, warmth: r.warmth ?? 0,
      shadow: r.shadow ?? true, fill_ratio: r.fill_ratio ?? 0.8, rotation_deg: r.rotation_resolved ?? 0,
    });
  }, [a?.id, a?.render?.id]); // eslint-disable-line
  const render = useAction((hero?: boolean) => post(`/api/assets/${assetId}/render`, { ...settings, ...(hero ? { hero: true } : {}) }), {
    success: "Rendering the studio image…", invalidate: inv,
  });
  const ai = useQuery({ queryKey: keys.ai, queryFn: () => get<any>("/api/settings/ai"), staleTime: 60000 });

  // ---- result state
  const [variant, setVariant] = useState("store_2x3");
  const review = useAction((decision: string) => post(`/api/assets/${assetId}/review`, { decision }), {
    success: (r: any) => (r.review_status === "approved" ? "Image approved" : r.review_status === "rejected" ? "Image rejected" : "Rendering again…"),
    invalidate: inv,
  });
  const restore = useAction((rid: string) => post(`/api/assets/${assetId}/renders/${rid}/restore`), { success: "Earlier render restored", invalidate: inv });
  const setType = useAction((t: string) => api_patch(assetId, { photo_type: t }), { success: "Photo type updated", invalidate: inv });
  const setKeep = useAction((v: boolean | null) => api_patch(assetId, v === null ? { clear_selection_override: true } : { selection_override: v }), { invalidate: inv });

  const w = watch.data?.watch;
  const metrics = a?.inspection?.metrics ?? {};
  const fid = a?.render?.fidelity?.[variant];
  const variantUrl = a?.render?.variants?.[variant]?.url;
  const beforeUrl = a?.render ? `/api/assets/${assetId}/image/aligned:${variant}?v=${a.render.id}` : "";

  const viewer = useMemo(() => {
    if (!a) return null;
    if (stage === "inspect") return <ZoomView src={a.urls.working} alt="Working copy" />;
    if (stage === "privacy") {
      if (!a.urls.redacted) return <Placeholder text="The privacy check has not run yet." />;
      return showRedacted ? <ZoomView src={`${a.urls.redacted}`} alt="Redacted photo" />
        : <RedactionEditor src={a.urls.working} regions={regions} onChange={setRegions} selected={selected} onSelect={setSelected} zoom={zoom} />;
    }
    if (stage === "cutout") {
      if (!a.urls.mask) return <Placeholder text="No cutout yet." />;
      return previewCut ? <ZoomView src={a.urls.cutout!} alt="Cutout" checker />
        : <MaskEditor imageSrc={a.urls.redacted ?? a.urls.working} maskSrc={a.urls.mask} mode={brushMode} brush={brush} showOverlay={overlay} zoom={zoom} editorRef={maskRef} />;
    }
    if (stage === "studio") return a.render && variantUrl ? <ZoomView src={variantUrl} alt="Studio image" /> : <Placeholder text="No studio image yet — choose settings and render." />;
    return a.render && variantUrl ? <CompareView before={beforeUrl} after={variantUrl} beforeLabel="Original (redacted)" afterLabel="Studio image" /> : <Placeholder text="No studio image yet." />;
  }, [a, stage, showRedacted, regions, selected, zoom, previewCut, brushMode, brush, overlay, variantUrl, beforeUrl]);

  if (assetQ.isError) return <div className="min-h-screen bg-stage text-white grid place-items-center">This photo could not be loaded. <Link className="underline ml-1" to={`/watches/${id}/photos`}>Back</Link></div>;

  return (
    <div className="h-screen flex flex-col bg-stage text-white overflow-hidden">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2 min-h-14 border-b border-stage-line shrink-0">
        <Link to={`/watches/${id}/photos`} className="inline-flex items-center gap-1.5 text-[13px] text-white/70 hover:text-white"><ArrowLeft className="size-4" />Photos</Link>
        <div className="h-5 w-px bg-stage-line" />
        <div className="min-w-0 hidden sm:block">
          <div className="font-display text-[19px] leading-none truncate">{w ? `${w.brand} ${w.model}` : "…"}</div>
          <div className="text-[11.5px] text-white/50 mt-0.5 truncate">{w?.sku} · {a?.filename} · {idx + 1} of {assets.length}</div>
        </div>
        <div className="flex items-center gap-0.5 ml-2">
          <button className="size-8 grid place-items-center rounded hover:bg-white/10 disabled:opacity-30 cursor-pointer" disabled={idx <= 0} onClick={() => go(-1)} aria-label="Previous photo" title="Previous (Alt+←)"><ChevronLeft className="size-4" /></button>
          <button className="size-8 grid place-items-center rounded hover:bg-white/10 disabled:opacity-30 cursor-pointer" disabled={idx >= assets.length - 1} onClick={() => go(1)} aria-label="Next photo" title="Next (Alt+→)"><ChevronRight className="size-4" /></button>
        </div>
        <nav className="ml-auto flex flex-wrap items-center gap-1" role="tablist" aria-label="Steps">
          {STAGES.map((s, i) => (
            <button key={s.key} role="tab" aria-selected={stage === s.key} onClick={() => setStage(s.key)}
              className={cx("h-8 px-3 rounded-md text-[13px] whitespace-nowrap cursor-pointer transition-colors", stage === s.key ? "bg-white text-ink font-medium" : "text-white/70 hover:bg-white/10")}>
              <span className={cx("mr-1.5 tabular-nums", stage === s.key ? "text-steel" : "text-white/40")}>{i + 1}</span>{s.label}
            </button>
          ))}
        </nav>
      </header>

      {busy && (
        <div className="h-8 shrink-0 bg-[#16241e] border-b border-stage-line flex items-center gap-3 px-4 text-[12.5px] text-white/80">
          <Spinner className="text-white/80" /> {job?.label ?? "Processing"}: {job?.message ?? "queued"}
          <div className="flex-1 max-w-xs h-1 rounded-full bg-white/10 overflow-hidden"><div className="h-full bg-[#3c8a69] transition-all" style={{ width: `${job?.progress ?? 5}%` }} /></div>
        </div>
      )}

      <div className="flex-1 min-h-0 grid grid-rows-[1fr_auto] lg:grid-rows-1 lg:grid-cols-[92px_1fr_356px]">
        <aside className="hidden lg:block border-r border-stage-line overflow-y-auto scroll-thin py-3 space-y-2 px-2.5">
          {assets.map((x) => (
            <Link key={x.id} to={`/watches/${id}/studio/${x.id}`} replace title={x.filename}
              className={cx("block rounded-md overflow-hidden border-2 aspect-[3/4] bg-stage-2", x.id === assetId ? "border-white" : "border-transparent opacity-70 hover:opacity-100")}>
              <img src={x.urls.thumb} alt={x.filename} className="size-full object-cover" loading="lazy" />
            </Link>
          ))}
        </aside>
        <main className="relative min-h-[50vh] bg-[radial-gradient(120%_80%_at_50%_30%,#1d2622_0%,#121614_70%)]">
          {!a ? <Placeholder text="Loading photo…" /> : viewer}
        </main>
        <aside className="border-t lg:border-t-0 lg:border-l border-stage-line bg-stage-2 overflow-y-auto scroll-thin px-5 max-h-[45vh] lg:max-h-none">
          {a && stage === "inspect" && (
            <>
              <Section title="Selection">
                <div className="flex items-center gap-2 mb-2">
                  <Pill tone={a.selected ? "velvetSolid" : "ink"}>{a.selected ? "Kept" : "Left out"}</Pill>
                  {a.selection_override !== null && <span className="text-[12px] text-white/50">set by you</span>}
                </div>
                <ul className="text-[13px] text-white/80 space-y-1 mb-3">{a.selection_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
                <div className="flex gap-2">
                  <DBtn onClick={() => setKeep.mutate(!a.selected)}>{a.selected ? "Leave out" : "Keep"}</DBtn>
                  {a.selection_override !== null && <DBtn onClick={() => setKeep.mutate(null)}>Automatic</DBtn>}
                </div>
              </Section>
              <Section title="Quality">
                <Metric label="Overall score" value={a.quality_score !== null ? Math.round(a.quality_score) : "—"} />
                <Metric label="Sharpness" value={metrics.sharpness ?? "—"} warn={metrics.sharpness < 47} />
                <Metric label="Exposure (watch)" value={metrics.exposure_mean !== undefined ? `${metrics.exposure_mean} L*` : "—"} />
                <Metric label="Blown highlights" value={metrics.clipped !== undefined ? `${(metrics.clipped * 100).toFixed(1)}%` : "—"} warn={metrics.clipped > 0.08} />
                <Metric label="Resolution" value={`${a.width} × ${a.height}`} warn={Math.min(a.width, a.height) < 1200} />
                <Metric label="Watch in frame" value={metrics.subject_fill !== undefined ? `${Math.round(metrics.subject_fill * 100)}%` : "—"} />
                <Metric label="File" value={`${a.format} · ${bytes(a.bytes)}`} />
                {a.warnings.length > 0 && <ul className="mt-2 text-[12.5px] text-[#e7c27d] space-y-1">{a.warnings.map((x, i) => <li key={i}>{x}</li>)}</ul>}
              </Section>
              <Section title="Photo type">
                <select className="w-full h-9 rounded-md bg-stage-3 border border-stage-line px-2 text-[13px]" value={a.photo_type ?? "unclassified"} onChange={(e) => setType.mutate(e.target.value)}>
                  {Object.entries(PHOTO_TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                <p className="text-[12px] text-white/50 mt-1.5">
                  {a.photo_type_source === "user" ? "Set by you." : a.photo_type_source === "ai" ? `Suggested by AI (${Math.round((a.photo_type_confidence ?? 0) * 100)}%).` : "Guessed on this machine; correct it if wrong."}
                  {" "}Casebacks, movements and papers never go to cloud AI.
                </p>
              </Section>
              <Section title="Source">
                <Metric label="Kind" value={a.source_profile === "phone" ? "Phone / WhatsApp" : a.source_profile === "edited" ? "Edited set" : a.source_profile === "raw" ? "Camera original" : "—"} />
                <ul className="text-[12.5px] text-white/60 mt-1 space-y-0.5">{a.source_profile_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
                {Object.keys(a.exif).length > 0 && <div className="mt-2">{Object.entries(a.exif).map(([k, v]) => <Metric key={k} label={k} value={v} />)}</div>}
                <div className="mt-3 flex flex-wrap gap-3 text-[12.5px]">
                  <a className="text-[#8fd0b3] hover:underline inline-flex items-center gap-1" href={`${a.urls.original}?download=1`}><Download className="size-3.5" />Original file</a>
                </div>
                <p className="text-[11.5px] text-white/40 mt-2 break-all">SHA-256 {a.sha256.slice(0, 24)}…</p>
              </Section>
              <Section title="Processing">
                <DBtn icon={<RefreshCw className="size-4" />} loading={busy} onClick={async () => {
                  if (await confirm({ title: "Process this photo again?", body: "Runs the privacy scan, cutout, inspection and studio render again. Manual redactions and a hand-corrected cutout are kept.", confirm: "Process again" })) {
                    post(`/api/assets/${assetId}/process`).then(() => qc.invalidateQueries({ queryKey: keys.watch(id) })).catch((e) => toast("error", errorMessage(e)));
                  }
                }}>Process again</DBtn>
                {a.pipeline_error && <p className="text-[12.5px] text-[#f0a397] mt-2">{a.pipeline_error}</p>}
              </Section>
            </>
          )}

          {a && stage === "privacy" && (
            <>
              <Section title="Serial-number check">
                <div className="flex items-center gap-2 mb-2"><Pill tone={SAFETY_TONE[a.safety_status] ?? "neutral"} dot>{a.safety_label}</Pill></div>
                <p className="text-[13px] text-white/80">{a.safety_recheck?.message ?? "Not checked yet."}</p>
                <p className="text-[12px] text-white/50 mt-2">Local OCR read the photo at four rotations. OCR is not proof: look at the photo yourself before marking it checked.</p>
                {a.safety_reviewed_at && <p className="text-[12px] text-[#8fd0b3] mt-2">Checked by {a.safety_reviewed_by?.replace("user:", "")} {ago(a.safety_reviewed_at)}.</p>}
                <div className="flex flex-wrap gap-2 mt-3">
                  <DBtn primary icon={<ShieldCheck className="size-4" />} disabled={a.safety_status === "failed" || a.safety_status === "reviewed" || regionsDirty} loading={checked.isPending}
                    onClick={() => checked.mutate()}>I have checked this photo</DBtn>
                  <DBtn icon={<ScanText className="size-4" />} loading={rescan.isPending} onClick={() => rescan.mutate()}>Scan again</DBtn>
                </div>
              </Section>
              <Section title={`Redactions (${regions.filter((r) => r.enabled).length})`}>
                <p className="text-[12.5px] text-white/55 mb-3">Drag on the photo to add a block. Click a block to move it or drag its corner to resize. Delete removes it.</p>
                <ul className="space-y-1.5 mb-3">
                  {regions.map((r, i) => (
                    <li key={r.id ?? i} className={cx("flex items-center gap-2 rounded-md px-2 py-1.5 text-[12.5px] cursor-pointer", selected === i ? "bg-stage-3" : "hover:bg-stage-3/60")} onClick={() => setSelected(i)}>
                      <span className={cx("size-2.5 rounded-sm", r.source === "ocr" ? "bg-[#c9a35f]" : "bg-[#5ea886]")} />
                      <span className="flex-1 truncate">{r.source === "ocr" ? regionLabel(r.category) : "Added by you"}</span>
                      <button className="text-white/60 hover:text-white cursor-pointer" aria-label={r.enabled ? "Disable" : "Enable"} onClick={(e) => { e.stopPropagation(); setRegions(regions.map((x, j) => j === i ? { ...x, enabled: !x.enabled } : x)); }}>
                        {r.enabled ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
                      </button>
                      <button className="text-white/60 hover:text-[#f0a397] cursor-pointer" aria-label="Delete" onClick={(e) => { e.stopPropagation(); setRegions(regions.filter((_, j) => j !== i)); setSelected(null); }}><Trash2 className="size-3.5" /></button>
                    </li>
                  ))}
                  {!regions.length && <li className="text-[12.5px] text-white/50">No redactions on this photo.</li>}
                </ul>
                <div className="flex flex-wrap gap-2">
                  <DBtn primary disabled={!regionsDirty} loading={saveRegions.isPending} onClick={() => saveRegions.mutate()}>Save redactions</DBtn>
                  {regionsDirty && <DBtn onClick={() => setRegions(a.regions)}>Discard</DBtn>}
                </div>
              </Section>
              <Section title="View">
                <div className="flex flex-wrap gap-2">
                  <DBtn icon={showRedacted ? <EyeOff className="size-4" /> : <Eye className="size-4" />} onClick={() => setShowRedacted(!showRedacted)}>{showRedacted ? "Edit blocks" : "Show result"}</DBtn>
                  {[1, 2, 3].map((z) => <DBtn key={z} onClick={() => setZoom(z)} primary={zoom === z}>{z}×</DBtn>)}
                </div>
              </Section>
              <Section title="Cloud AI">
                <p className="text-[13px] text-white/80">{a.cloud_ai.eligible ? "May be sent to AI (redacted copy only)." : "Stays on this machine."}</p>
                <p className="text-[12px] text-white/50 mt-1">{a.cloud_ai.reason}</p>
              </Section>
            </>
          )}

          {a && stage === "cutout" && (
            <>
              <Section title="Cutout">
                <Metric label="Made by" value={a.mask_source === "manual" ? "You" : a.mask_source?.startsWith("rembg") ? "Local AI model" : a.mask_source === "source_transparency" ? "PNG transparency" : a.mask_source ?? "—"} />
                <ul className="text-[12.5px] text-white/60 mt-1.5 space-y-1">{(a.segmentation?.notes ?? []).map((n, i) => <li key={i}>{n}</li>)}</ul>
              </Section>
              <Section title="Correct by hand">
                <div className="grid grid-cols-2 gap-2 mb-3">
                  <DBtn primary={brushMode === "keep"} icon={<Brush className="size-4" />} onClick={() => setBrushMode("keep")}>Keep</DBtn>
                  <DBtn primary={brushMode === "remove"} icon={<Eraser className="size-4" />} onClick={() => setBrushMode("remove")}>Remove</DBtn>
                </div>
                <Slider label="Brush size" value={brush} min={2} max={100} step={1} onChange={setBrush} />
                <p className="text-[12px] text-white/50 mb-3">Red shows what is removed. Paint “Keep” over any part of the watch that was cut away (hands, crystal edge, strap).</p>
                <div className="flex flex-wrap gap-2">
                  <DBtn icon={<Undo2 className="size-4" />} onClick={() => maskRef.current?.undo()}>Undo</DBtn>
                  <DBtn icon={overlay ? <EyeOff className="size-4" /> : <Eye className="size-4" />} onClick={() => setOverlay(!overlay)}>{overlay ? "Hide red" : "Show red"}</DBtn>
                  <DBtn onClick={() => setPreviewCut(!previewCut)}>{previewCut ? "Edit" : "Preview"}</DBtn>
                  {[1, 2].map((z) => <DBtn key={z} onClick={() => setZoom(z)} primary={zoom === z}>{z}×</DBtn>)}
                </div>
                <div className="flex flex-wrap gap-2 mt-4">
                  <DBtn primary loading={savingMask} onClick={async () => {
                    const blob = await maskRef.current?.exportPng();
                    if (!blob) return;
                    setSavingMask(true);
                    try {
                      await uploadFiles(`/api/assets/${assetId}/mask`, [new File([blob], "mask.png", { type: "image/png" })], undefined, "file", "PUT");
                      toast("success", "Cutout saved. Render the photo again to use it.");
                      inv.forEach((k) => qc.invalidateQueries({ queryKey: k }));
                    } catch (e) {
                      toast("error", errorMessage(e));
                    } finally {
                      setSavingMask(false);
                    }
                  }}>Save cutout</DBtn>
                  <DBtn icon={<RotateCcw className="size-4" />} loading={resegment.isPending} onClick={() => resegment.mutate()}>Redo automatically</DBtn>
                </div>
              </Section>
            </>
          )}

          {a && stage === "studio" && (
            <>
              <Section title="Background">
                <div className="grid grid-cols-3 gap-2">
                  {Object.entries(BACKGROUNDS).map(([k, label]) => {
                    const isAi = k.startsWith("ai_");
                    const disabled = isAi && !ai.data?.available;
                    return (
                      <button key={k} disabled={disabled} onClick={() => setSettings({ ...settings, background: k })} title={disabled ? "Needs an OpenAI key" : label}
                        className={cx("rounded-md border-2 p-1 text-left cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed", settings.background === k ? "border-white" : "border-transparent hover:border-stage-line")}>
                        <span className="block aspect-square rounded" style={{ background: SWATCH[k] }} />
                        <span className="block text-[11px] leading-tight mt-1 text-white/80">{label}</span>
                      </button>
                    );
                  })}
                </div>
                <p className="text-[12px] text-white/50 mt-2">
                  {String(settings.background).startsWith("ai_")
                    ? "The AI makes an empty backdrop only (no photo is sent). Your watch is placed on it by the studio, pixel for pixel."
                    : `House default resolves to “${BACKGROUNDS[a.studio_resolved.background_resolved] ?? a.studio_resolved.background_resolved}” for this ${a.source_profile === "edited" ? "edited" : "unedited"} photo.`}
                </p>
              </Section>
              <Section title="Colour & exposure">
                <Slider label="White balance" value={settings.white_balance_strength ?? 0.6} min={0} max={1} step={0.05} onChange={(v) => setSettings({ ...settings, white_balance_strength: v })} format={(v) => `${Math.round(v * 100)}%`} />
                <Slider label="Exposure" value={settings.exposure_ev ?? 0} min={-1} max={1} step={0.05} onChange={(v) => setSettings({ ...settings, exposure_ev: v })} format={(v) => `${v > 0 ? "+" : ""}${v.toFixed(2)} EV`} />
                <Slider label="Contrast" value={settings.contrast ?? 0} min={-20} max={20} step={1} onChange={(v) => setSettings({ ...settings, contrast: v })} />
                <Slider label="Warmth" value={settings.warmth ?? 0} min={-15} max={15} step={1} onChange={(v) => setSettings({ ...settings, warmth: v })} />
                <label className="flex items-center gap-2 text-[13px] text-white/80"><input type="checkbox" checked={!!settings.auto_exposure} onChange={(e) => setSettings({ ...settings, auto_exposure: e.target.checked })} /> Automatic brightness</label>
                <p className="text-[12px] text-white/50 mt-2">Corrections apply evenly to the whole watch; nothing is retouched.</p>
              </Section>
              <Section title="Framing">
                <Slider label="Watch size in frame" value={settings.fill_ratio ?? 0.8} min={0.5} max={0.92} step={0.01} onChange={(v) => setSettings({ ...settings, fill_ratio: v })} format={(v) => `${Math.round(v * 100)}%`} />
                <Slider label="Rotation" value={settings.rotation_deg ?? 0} min={-45} max={45} step={1} onChange={(v) => setSettings({ ...settings, rotation_deg: v })} format={(v) => `${v}°`} />
                <label className="flex items-center gap-2 text-[13px] text-white/80"><input type="checkbox" checked={!!settings.shadow} onChange={(e) => setSettings({ ...settings, shadow: e.target.checked })} /> Soft contact shadow</label>
              </Section>
              <Section title="Render">
                <div className="flex flex-wrap gap-2">
                  <DBtn primary loading={render.isPending || busy} disabled={a.safety_status === "failed"} onClick={() => render.mutate(undefined)}>Render studio image</DBtn>
                  <DBtn onClick={() => render.mutate(true)} disabled={busy}>Render as lead image</DBtn>
                </div>
                {a.safety_status === "failed" && <p className="text-[12.5px] text-[#f0a397] mt-2">Fix the redactions first.</p>}
                {a.render_stale && <p className="text-[12.5px] text-[#e7c27d] mt-2">Redactions or cutout changed since the last render.</p>}
              </Section>
            </>
          )}

          {a && stage === "result" && (
            <>
              <Section title="Format">
                <div className="flex flex-wrap gap-2">
                  {Object.entries(a.render?.variants ?? {}).map(([k, v]) => <DBtn key={k} primary={variant === k} onClick={() => setVariant(k)}>{v.label}</DBtn>)}
                </div>
                <p className="text-[12px] text-white/50 mt-2">Drag the line to compare with the original. Scroll to zoom.</p>
              </Section>
              {a.render && (
                <Section title="Fidelity check">
                  <div className="flex items-center gap-2 mb-2">
                    {a.render.fidelity_passed ? <Pill tone="velvetSolid">Passed</Pill> : <Pill tone="danger">Failed</Pill>}
                    <span className="text-[12.5px] text-white/70">{fid?.message}</span>
                  </div>
                  {fid && <>
                    <Metric label="Match inside the watch (PSNR)" value={`${fid.psnr_db} dB`} />
                    <Metric label="Largest difference (99th pct.)" value={fid.p99_abs_error} />
                    <Metric label="Pixels compared" value={fid.pixels_compared?.toLocaleString()} />
                    <Metric label="Redaction blocks intact" value={fid.redactions?.checked ? `${fid.redactions.intact} of ${fid.redactions.checked}` : "None on the watch"} />
                  </>}
                  <p className="text-[12px] text-white/50 mt-2">Computed against your original photo inside the watch outline; only compression differences are allowed.</p>
                  {!!a.render.warnings?.length && <ul className="mt-2 text-[12.5px] text-[#e7c27d] space-y-1">{a.render.warnings.map((x, i) => <li key={i}>{x}</li>)}</ul>}
                </Section>
              )}
              <Section title="Review">
                <div className="flex items-center gap-2 mb-3">
                  <Pill tone={a.review_status === "approved" ? "velvetSolid" : a.review_status === "rejected" ? "danger" : "brass"} dot>
                    {a.review_status === "approved" ? "Approved" : a.review_status === "rejected" ? "Rejected" : a.review_status === "regenerate_requested" ? "New render requested" : "Waiting for review"}
                  </Pill>
                </div>
                <div className="flex flex-wrap gap-2">
                  <DBtn primary icon={<Check className="size-4" />} disabled={!a.render || a.review_status === "approved"} loading={review.isPending} onClick={() => review.mutate("approve")}>Approve</DBtn>
                  <DBtn icon={<RefreshCw className="size-4" />} disabled={!a.render} onClick={() => review.mutate("regenerate")}>Render again</DBtn>
                  <DBtn danger icon={<X className="size-4" />} onClick={() => review.mutate("reject")}>Reject</DBtn>
                </div>
              </Section>
              {a.render && (
                <Section title="Download">
                  <div className="flex flex-col gap-1.5 text-[13px]">
                    {Object.entries(a.render.variants ?? {}).map(([k, v]) => (
                      <a key={k} className="text-[#8fd0b3] hover:underline inline-flex items-center gap-1.5" href={`${v.url}&download=1`}><Download className="size-3.5" />{v.label} · {v.width}×{v.height}</a>
                    ))}
                  </div>
                </Section>
              )}
              {a.renders.length > 1 && (
                <Section title="Earlier renders">
                  <ul className="space-y-1.5">
                    {a.renders.map((r) => (
                      <li key={r.id} className="flex items-center gap-2 text-[12.5px]">
                        <img src={r.url} alt="" className="size-9 rounded object-cover bg-stage" loading="lazy" />
                        <span className="flex-1">v{r.version} · {(r.background_source ?? "").replace("local:", "").replace(/_/g, " ")} · {ago(r.created_at)}</span>
                        {r.id === a.render?.id ? <span className="text-white/50">current</span> : <button className="text-[#8fd0b3] hover:underline cursor-pointer" onClick={() => restore.mutate(r.id)}>Use</button>}
                      </li>
                    ))}
                  </ul>
                </Section>
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  );
}

function Placeholder({ text }: { text: string }) {
  return <div className="absolute inset-0 grid place-items-center text-white/50 text-[14px]">{text}</div>;
}

function api_patch(assetId: string, body: unknown) {
  return patch(`/api/assets/${assetId}`, body);
}
