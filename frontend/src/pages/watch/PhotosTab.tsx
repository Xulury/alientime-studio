import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Camera, Play, ShieldCheck, Sparkles, Star, Trash2 } from "lucide-react";
import { del, get, patch, post, put } from "../../lib/api";
import { keys, useAction } from "../../lib/hooks";
import type { Asset, WatchDetail } from "../../lib/types";
import { Dropzone, PendingList, useUploader } from "../../components/Dropzone";
import { Button, Empty, Notice, Panel, PanelHeader, Pill, Progress, SAFETY_TONE, cx, useConfirm } from "../../components/ui";

function AssetCard({ a, watchId, job }: { a: Asset; watchId: string; job?: { progress: number; message: string | null; status: string } }) {
  const confirm = useConfirm();
  const inv = [keys.watch(watchId), keys.review(watchId)];
  const toggle = useAction((v: boolean | null) => patch(`/api/assets/${a.id}`, v === null ? { clear_selection_override: true } : { selection_override: v }), { invalidate: inv });
  const remove = useAction(() => del(`/api/assets/${a.id}`), { success: "Photo removed from the listing. The original file is kept.", invalidate: inv });
  const busy = a.pipeline_status === "queued" || a.pipeline_status === "processing" || !!job;
  return (
    <li className="panel overflow-hidden flex flex-col">
      <Link to={`/watches/${watchId}/studio/${a.id}`} className="relative block aspect-[4/5] bg-stage group">
        <img src={a.urls.thumb} alt={a.filename} className={cx("size-full object-contain transition-opacity", busy && "opacity-60")} loading="lazy" />
        <div className="absolute inset-x-0 top-0 p-2 flex justify-between gap-2">
          {busy ? <Pill tone="ink" className="shadow-sm">Processing</Pill> : <Pill tone={a.selected ? "velvetSolid" : "ink"} className="shadow-sm">{a.selected ? "Kept" : "Left out"}</Pill>}
          {a.has_render && (a.fidelity_passed ? <Pill tone="velvet" className="shadow-sm">Studio image</Pill> : <Pill tone="danger">Fidelity failed</Pill>)}
        </div>
        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-stage/40 text-white text-[13px] font-medium">
          Open in studio
        </div>
        {busy && <div className="absolute inset-x-3 bottom-3"><Progress value={job?.progress ?? 0} indeterminate={!job || job.status === "pending"} tone="info" /><div className="text-[11.5px] text-white/80 mt-1 truncate">{job?.message ?? "Queued"}</div></div>}
      </Link>
      <div className="p-3 flex-1 flex flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-[13px] font-medium truncate" title={a.filename}>{a.filename}</div>
            <div className="text-[12px] text-steel">{a.photo_type_label}{a.source_profile ? ` · ${a.source_profile === "phone" ? "phone / WhatsApp" : a.source_profile}` : ""}{a.quality_score !== null ? ` · score ${Math.round(a.quality_score)}` : ""}</div>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Pill tone={SAFETY_TONE[a.safety_status] ?? "neutral"} dot>{a.safety_label}</Pill>
          {a.review_status === "approved" && <Pill tone="velvet">Approved</Pill>}
          {a.review_status === "rejected" && <Pill tone="danger">Rejected</Pill>}
          {a.render_stale && <Pill tone="brass">Render again</Pill>}
        </div>
        {a.selection_reasons[0] && <p className={cx("text-[12.5px]", a.selected ? "text-steel" : "text-brass")}>{a.selection_reasons[0]}</p>}
        {a.warnings.slice(0, 2).map((w, i) => <p key={i} className="text-[12px] text-steel">{w}</p>)}
        {a.pipeline_error && <p className="text-[12px] text-danger">{a.pipeline_error}</p>}
        {["needs_review", "ocr_unavailable", "failed"].includes(a.safety_status) && (
          <Link to={`/watches/${watchId}/studio/${a.id}?stage=privacy`}
            className="inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-md bg-velvet text-white text-[13px] font-medium hover:bg-velvet-700">
            <ShieldCheck className="size-3.5" />Check redactions
          </Link>
        )}
        <div className="mt-auto flex gap-1.5 pt-1">
          <Button size="sm" variant="ghost" onClick={() => toggle.mutate(a.selected ? false : true)}>{a.selected ? "Leave out" : "Keep"}</Button>
          {a.selection_override !== null && <Button size="sm" variant="ghost" onClick={() => toggle.mutate(null)}>Automatic</Button>}
          <Button size="sm" variant="ghost" className="ml-auto" aria-label="Remove photo" onClick={async () => {
            if (await confirm({ title: "Remove this photo?", body: "It is removed from the listing. The original file stays in private storage.", confirm: "Remove", danger: true })) remove.mutate();
          }}><Trash2 className="size-4" /></Button>
        </div>
      </div>
    </li>
  );
}

function GalleryOrder({ detail }: { detail: WatchDetail }) {
  const w = detail.watch;
  const imgs = detail.readiness.images;
  const [order, setOrder] = useState(imgs.map((i) => i.asset_id));
  const [hero, setHero] = useState<string | null>(w.hero_asset_id ?? imgs[0]?.asset_id ?? null);
  useEffect(() => { setOrder(imgs.map((i) => i.asset_id)); setHero(w.hero_asset_id ?? imgs[0]?.asset_id ?? null); }, [detail]); // eslint-disable-line
  const save = useAction(() => put(`/api/watches/${w.id}/gallery`, { asset_ids: order, hero_asset_id: hero }), {
    success: "Image order saved. Approvals that depended on the old order were cleared.", invalidate: [keys.watch(w.id), keys.review(w.id)],
  });
  const changed = JSON.stringify(order) !== JSON.stringify(imgs.map((i) => i.asset_id)) || hero !== (w.hero_asset_id ?? imgs[0]?.asset_id ?? null);
  const move = (i: number, d: number) => {
    const next = [...order];
    const [x] = next.splice(i, 1);
    next.splice(i + d, 0, x);
    setOrder(next);
  };
  if (!imgs.length) return null;
  const byId = Object.fromEntries(imgs.map((i) => [i.asset_id, i]));
  return (
    <Panel className="mb-6">
      <PanelHeader title="Final selection" sub="The images used in listings, in posting order. The first is the cover image."
        actions={changed && <Button variant="primary" size="sm" loading={save.isPending} onClick={() => save.mutate()}>Save order</Button>} />
      <ol className="flex gap-3 overflow-x-auto scroll-thin pb-2">
        {order.map((id, i) => byId[id] && (
          <li key={id} className="shrink-0 w-32">
            <div className="relative aspect-[2/3] rounded-md overflow-hidden bg-stage">
              <img src={byId[id].thumb} alt="" className="size-full object-cover" />
              <span className="absolute left-1.5 top-1.5 size-6 rounded-full bg-ink/80 text-white text-[12px] grid place-items-center tabular-nums">{i + 1}</span>
              {hero === id && <span className="absolute right-1.5 top-1.5"><Pill tone="brassSolid">Lead</Pill></span>}
            </div>
            <div className="flex items-center justify-between mt-1.5">
              <button className="p-1 rounded hover:bg-wash disabled:opacity-30 cursor-pointer" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move earlier"><ArrowLeft className="size-3.5" /></button>
              <button className={cx("p-1 rounded hover:bg-wash cursor-pointer", hero === id ? "text-brass" : "text-steel")} onClick={() => setHero(id)} aria-label="Make lead image"><Star className="size-3.5" fill={hero === id ? "currentColor" : "none"} /></button>
              <button className="p-1 rounded hover:bg-wash disabled:opacity-30 cursor-pointer" disabled={i === order.length - 1} onClick={() => move(i, 1)} aria-label="Move later"><ArrowRight className="size-3.5" /></button>
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

export default function PhotosTab({ detail }: { detail: WatchDetail }) {
  const w = detail.watch;
  const qc = useQueryClient();
  const confirm = useConfirm();
  const up = useUploader();
  const [uploading, setUploading] = useState(false);
  const inv = [keys.watch(w.id), keys.review(w.id), keys.facts(w.id)];
  const ai = useQuery({ queryKey: keys.ai, queryFn: () => get<any>("/api/settings/ai"), staleTime: 60000 });
  const processAll = useAction(() => post<any>(`/api/watches/${w.id}/process`), {
    success: (r) => (r.queued ? `Processing ${r.queued} photo(s)` : "Every photo is already processed."), invalidate: inv,
  });
  const checkAll = useAction(() => post<any>(`/api/watches/${w.id}/privacy-review`, { confirm: true }), {
    success: (r) => `${r.checked} photo(s) marked as checked` + (r.skipped?.length ? `; ${r.skipped.length} need fixing first` : ""), invalidate: inv,
  });
  const tag = useAction(() => post(`/api/watches/${w.id}/ai/tag`), { success: "Tagging checked photos…", invalidate: inv });
  const jobsByAsset = Object.fromEntries(detail.jobs.filter((j) => (j.status === "pending" || j.status === "running") && j.asset_id).map((j) => [j.asset_id!, j]));
  const needsCheck = detail.assets.filter((a) => ["needs_review", "ocr_unavailable", "clear"].includes(a.safety_status)).length;
  const unprocessed = detail.assets.filter((a) => a.pipeline_status === "uploaded" || a.pipeline_status === "failed").length;

  const doUpload = async () => {
    setUploading(true);
    const r = await up.uploadAll(w.id);
    setUploading(false);
    qc.invalidateQueries({ queryKey: keys.watch(w.id) });
    if (r.added) setTimeout(() => up.clear(), 1500);
  };

  return (
    <div>
      <Panel className="mb-6">
        <div className="grid lg:grid-cols-[1fr_auto] gap-4 items-start">
          <div>
            <Dropzone onFiles={up.add} compact />
            <PendingList files={up.files} onRemove={up.remove} />
            {up.readyCount > 0 && <Button variant="primary" className="mt-3" loading={uploading} onClick={doUpload}>Upload {up.readyCount} photo{up.readyCount > 1 ? "s" : ""}</Button>}
          </div>
          <div className="flex lg:flex-col gap-2 flex-wrap lg:w-56">
            <Button icon={<Play className="size-4" />} disabled={!unprocessed} loading={processAll.isPending} onClick={() => processAll.mutate()}>Process new photos</Button>
            <Button icon={<ShieldCheck className="size-4" />} disabled={!needsCheck} onClick={async () => {
              if (await confirm({
                title: "Mark every photo as checked?",
                body: <>Confirm you have looked at each photo (or its redactions) and no serial number, warranty card number or other private detail is readable. Checked photos may be sent to AI, except casebacks and papers, which never leave this machine.</>,
                confirm: "I have checked them",
              })) checkAll.mutate();
            }}>Mark all as checked</Button>
            <Button icon={<Sparkles className="size-4" />} disabled={!ai.data?.available || !detail.assets.length} loading={tag.isPending}
              title={ai.data?.available ? "" : "AI is not configured"} onClick={() => tag.mutate()}>Tag photos with AI</Button>
          </div>
        </div>
      </Panel>

      <GalleryOrder detail={detail} />

      {detail.assets.length === 0 ? (
        <Panel><Empty icon={<Camera className="size-8" />} title="No photos yet">Drop the watch's photographs above. Edited, raw camera and WhatsApp photos are all fine.</Empty></Panel>
      ) : (
        <>
          {needsCheck > 0 && <Notice tone="warning" className="mb-4" title={`${needsCheck} photo${needsCheck > 1 ? "s" : ""} not yet checked for serials`}>
            Open each photo to review the redaction blocks, or use “Mark all as checked” once you have looked. OCR alone does not prove every identifier is hidden.
          </Notice>}
          <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-4">
            {detail.assets.map((a) => <AssetCard key={a.id} a={a} watchId={w.id} job={jobsByAsset[a.id]} />)}
          </ul>
        </>
      )}
    </div>
  );
}
