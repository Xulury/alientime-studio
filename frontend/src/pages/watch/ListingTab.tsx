import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, PenLine, RefreshCw, Sparkles, Wand2 } from "lucide-react";
import { get, post, put } from "../../lib/api";
import { keys, useAction } from "../../lib/hooks";
import { ago, actorName } from "../../lib/format";
import type { ChannelCopyView, WatchDetail } from "../../lib/types";
import { Button, Empty, Loading, Modal, Notice, Panel, Pill, Select, TextArea, Toggle, cx } from "../../components/ui";

interface CopyResp {
  channels: ChannelCopyView[];
  watch_channels: string[] | null;
  section_labels: Record<string, string>;
  section_kinds: Record<string, string>;
  styles: string[];
  ai: { available: boolean; provider: string };
}

const ROUTE_LABEL = { api: "Posts by API", feed: "Dealer feed", manual: "Draft pack (you post)" } as const;

function Counter({ n, max, verified }: { n: number; max?: number; verified?: boolean }) {
  if (!max) return <span className="text-[12px] text-steel tabular-nums">{n} characters</span>;
  return (
    <span className={cx("text-[12px] tabular-nums", n > max ? "text-danger font-medium" : n > max * 0.9 ? "text-brass" : "text-steel")}
      title={verified ? "Documented platform limit" : "No published limit; conservative internal limit"}>
      {n} / {max}{verified ? "" : "*"}
    </span>
  );
}

function ChannelEditor({ ch, data, watchId, onJob }: { ch: ChannelCopyView; data: CopyResp; watchId: string; onJob: () => void }) {
  const qc = useQueryClient();
  const copy = ch.copy;
  const [title, setTitle] = useState(copy?.sections.title ?? "");
  const [body, setBody] = useState(copy?.sections.body ?? "");
  const [tags, setTags] = useState((copy?.sections.hashtags ?? []).join(" "));
  const [showRevs, setShowRevs] = useState(false);
  useEffect(() => {
    setTitle(copy?.sections.title ?? "");
    setBody(copy?.sections.body ?? "");
    setTags((copy?.sections.hashtags ?? []).join(" "));
  }, [copy?.version, ch.key]); // eslint-disable-line
  const inv = [keys.copy(watchId), keys.review(watchId), keys.watch(watchId)];
  const dirty = !!copy && (title !== (copy.sections.title ?? "") || body !== (copy.sections.body ?? "") || tags !== (copy.sections.hashtags ?? []).join(" "));
  const save = useAction(() => {
    const b: Record<string, unknown> = {};
    if (title !== (copy?.sections.title ?? "")) b.title = title;
    if (body !== (copy?.sections.body ?? "")) b.body = body;
    if (tags !== (copy?.sections.hashtags ?? []).join(" ")) b.hashtags = tags;
    return put(`/api/watches/${watchId}/copy/${ch.key}`, b);
  }, { success: "Copy saved. Its approval was cleared.", invalidate: inv });
  const regen = useAction((a: { section?: string; mode: "template" | "ai" }) =>
    post<any>(`/api/watches/${watchId}/copy/generate`, { channels: [ch.key], mode: a.mode, section: a.section }), {
    success: (r) => (r.job ? "Writing with AI…" : "Copy updated"), invalidate: inv, onSuccess: (r) => r.job && onJob(),
  });
  const include = useAction((v: boolean) => {
    const all = data.channels.map((c) => c.key);
    const current = data.watch_channels ?? all;
    const next = v ? Array.from(new Set([...current, ch.key])) : current.filter((c) => c !== ch.key);
    return put(`/api/watches/${watchId}/channels`, { channels: next.length === all.length ? null : next });
  }, { invalidate: inv });
  const revs = useQuery({ queryKey: ["revisions", watchId, ch.key], queryFn: () => get<{ items: any[] }>(`/api/watches/${watchId}/copy/${ch.key}/revisions`), enabled: showRevs });
  const restore = useAction((rid: string) => post(`/api/watches/${watchId}/copy/${ch.key}/revisions/${rid}/restore`), {
    success: "Earlier version restored", invalidate: inv, onSuccess: () => { setShowRevs(false); qc.invalidateQueries({ queryKey: ["revisions", watchId, ch.key] }); },
  });
  const limits = ch.limits;
  const v = copy?.validation;
  const textLen = copy?.text.length ?? 0;
  const roSections = ch.sections.filter((s) => !["title", "body", "hashtags"].includes(s));

  return (
    <Panel className="min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="font-display text-[26px] leading-tight">{ch.name}</h2>
          <div className="text-[13px] text-steel mt-0.5">{ch.audience}</div>
          <div className="flex flex-wrap gap-1.5 mt-2">
            <Pill tone="muted">{ROUTE_LABEL[ch.route]}</Pill>
            <Pill tone="muted">Up to {ch.max_images} images</Pill>
            {ch.approved ? <Pill tone="velvet" dot>Approved</Pill> : copy ? <Pill tone="brass" dot>Not approved</Pill> : null}
          </div>
        </div>
        <Toggle checked={ch.included} onChange={(x) => include.mutate(x)} label="List on this channel" hint="For this watch only" />
      </div>

      {!ch.included ? (
        <Notice tone="info">This channel is switched off for this watch. Switch it on to write and approve copy for it.</Notice>
      ) : !copy ? (
        <Empty title="No copy yet" action={<div className="flex gap-2 justify-center">
          <Button icon={<Wand2 className="size-4" />} loading={regen.isPending} onClick={() => regen.mutate({ mode: "template" })}>Write from template</Button>
          {data.ai.available && <Button variant="primary" icon={<Sparkles className="size-4" />} loading={regen.isPending} onClick={() => regen.mutate({ mode: "ai" })}>Write with AI</Button>}
        </div>}>Copy is written only from the confirmed facts of this watch.</Empty>
      ) : (
        <div className="space-y-5">
          {(v!.errors.length > 0 || copy.stale.length > 0) && (
            <Notice tone="danger" title="Fix before approving" action={copy.stale.length ? <Button size="sm" icon={<RefreshCw className="size-3.5" />} onClick={() => regen.mutate({ mode: "template" })}>Refresh</Button> : undefined}>
              <ul className="list-disc pl-4 space-y-0.5">
                {copy.stale.map((s, i) => <li key={`s${i}`}>{s}</li>)}
                {v!.errors.map((e, i) => <li key={i}><b className="font-medium">{data.section_labels[e.section] ?? e.section}:</b> {e.message}</li>)}
              </ul>
            </Notice>
          )}
          {v!.warnings.length > 0 && (
            <Notice tone="warning">
              <ul className="list-disc pl-4 space-y-0.5">{v!.warnings.map((e, i) => <li key={i}><b className="font-medium">{data.section_labels[e.section] ?? e.section}:</b> {e.message}</li>)}</ul>
            </Notice>
          )}

          {ch.has_title && (
            <div>
              <div className="flex items-end justify-between mb-1.5">
                <label className="field-label mb-0" htmlFor={`t-${ch.key}`}>Title <span className="text-steel font-normal">· {copy.sources.title === "user" ? "edited by you" : copy.sources.title}</span></label>
                <Counter n={title.length} max={limits.title?.max_chars} verified={limits.title?.verified} />
              </div>
              <input id={`t-${ch.key}`} className="field" value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
          )}
          <div>
            <div className="flex items-end justify-between mb-1.5">
              <label className="field-label mb-0" htmlFor={`b-${ch.key}`}>Description <span className="text-steel font-normal">· {copy.sources.body === "user" ? "edited by you" : copy.sources.body}</span></label>
            </div>
            <TextArea id={`b-${ch.key}`} rows={5} value={body} onChange={(e) => setBody(e.target.value)} />
          </div>
          {ch.hashtags_max > 0 && (
            <div>
              <div className="flex items-end justify-between mb-1.5">
                <label className="field-label mb-0" htmlFor={`h-${ch.key}`}>Hashtags</label>
                <Counter n={tags.split(/\s+/).filter(Boolean).length} max={ch.hashtags_max} verified />
              </div>
              <input id={`h-${ch.key}`} className="field" value={tags} onChange={(e) => setTags(e.target.value)} />
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()} icon={<PenLine className="size-4" />}>Save edits</Button>
            <Select aria-label="Regenerate" value="" className="w-auto" onChange={(e) => {
              const [mode, section] = e.target.value.split(":");
              if (mode) regen.mutate({ mode: mode as "template" | "ai", section: section || undefined });
            }} options={[
              { value: "", label: "Rewrite…" },
              { value: "template:", label: "Everything, from template" },
              ...(data.ai.available ? [{ value: "ai:", label: "Everything, with AI" }, { value: "ai:title", label: "Title only, with AI" }, { value: "ai:body", label: "Description only, with AI" }] : []),
              { value: "template:title", label: "Title only, from template" },
              ...(ch.hashtags_max ? [{ value: "template:hashtags", label: "Hashtags, house defaults" }] : []),
            ]} />
            <Button variant="ghost" icon={<History className="size-4" />} onClick={() => setShowRevs(true)}>Versions</Button>
            <span className="ml-auto self-center text-[12px] text-steel">v{copy.version} · {copy.generator.startsWith("ai") ? "AI" : copy.generator} · {ago(copy.updated_at)}</span>
          </div>

          <div className="grid md:grid-cols-2 gap-3">
            {roSections.map((s) => copy.sections[s] ? (
              <div key={s} className="rounded-lg border border-line bg-paper/50 p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[12.5px] font-semibold">{data.section_labels[s] ?? s}</span>
                  {data.section_kinds[s] === "fixed"
                    ? <Link to="/settings/terms" className="text-[12px] text-velvet hover:underline">Edit in Settings</Link>
                    : <Link to={`/watches/${watchId}/overview`} className="text-[12px] text-velvet hover:underline">Edit facts</Link>}
                </div>
                <div className="text-[13px] text-ink-2 whitespace-pre-wrap">{String(copy.sections[s])}</div>
              </div>
            ) : null)}
          </div>

          <div>
            <div className="flex items-end justify-between mb-1.5">
              <span className="field-label mb-0">Exactly what will be posted</span>
              <Counter n={textLen} max={limits.text?.max_chars} verified={limits.text?.verified} />
            </div>
            <pre className="rounded-lg bg-stage text-white/90 p-4 text-[13px] leading-relaxed whitespace-pre-wrap font-sans max-h-[420px] overflow-y-auto scroll-thin">{copy.text}</pre>
            {Object.values(limits).some((l) => !l.verified) && <p className="text-[12px] text-steel mt-1.5">* {ch.name} publishes no limit for this; the studio uses a conservative internal limit.</p>}
          </div>
        </div>
      )}

      <Modal open={showRevs} onClose={() => setShowRevs(false)} title={`${ch.name} — versions`} wide>
        {revs.isLoading ? <Loading /> : (
          <ul className="space-y-3">
            {revs.data?.items.map((r, i) => (
              <li key={r.id} className="rounded-lg border border-line p-3">
                <div className="flex items-center justify-between gap-3 mb-1.5">
                  <div className="text-[13px]"><b className="font-medium">v{r.version}</b> · {r.reason} · {actorName(r.created_by ?? "")} · {ago(r.created_at)}</div>
                  {i > 0 && <Button size="sm" loading={restore.isPending} onClick={() => restore.mutate(r.id)}>Restore</Button>}
                </div>
                <pre className="text-[12.5px] text-ink-2 whitespace-pre-wrap font-sans max-h-36 overflow-y-auto scroll-thin">{r.text}</pre>
              </li>
            ))}
          </ul>
        )}
      </Modal>
    </Panel>
  );
}

export default function ListingTab({ detail }: { detail: WatchDetail }) {
  const w = detail.watch;
  const qc = useQueryClient();
  const q = useQuery({ queryKey: keys.copy(w.id), queryFn: () => get<CopyResp>(`/api/watches/${w.id}/copy`) });
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<"template" | "ai">("template");
  const copyJobActive = detail.jobs.some((j) => j.type === "generate_copy" && (j.status === "pending" || j.status === "running"));
  const wasActive = useRef(copyJobActive);
  useEffect(() => {
    if (wasActive.current && !copyJobActive) qc.invalidateQueries({ queryKey: keys.copy(w.id) });
    wasActive.current = copyJobActive;
  }, [copyJobActive, qc, w.id]);
  const genAll = useAction(() => post<any>(`/api/watches/${w.id}/copy/generate`, { mode }), {
    success: (r) => (r.job ? "Writing copy with AI for every channel…" : "Copy written for every channel"),
    invalidate: [keys.copy(w.id), keys.watch(w.id), keys.review(w.id)],
  });
  const channels = q.data?.channels ?? [];
  const current = useMemo(() => channels.find((c) => c.key === selected) ?? channels.find((c) => c.included) ?? channels[0], [channels, selected]);
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Notice tone="danger">Listing copy could not be loaded.</Notice>;
  const blockers = detail.readiness.issues.filter((i) => i.severity === "blocker");

  return (
    <div>
      <Panel className="mb-6">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[240px]">
            <div className="text-[14px] font-semibold">Write copy for every channel</div>
            <div className="text-[13px] text-steel">Built only from confirmed facts. House terms are inserted word for word. Each result is checked against platform limits and claim rules.</div>
          </div>
          <Select aria-label="Writer" value={mode} onChange={(e) => setMode(e.target.value as "template" | "ai")} className="w-auto"
            options={[{ value: "template", label: "House templates (offline)" }, ...(q.data.ai.available ? [{ value: "ai", label: `AI writer (${q.data.ai.provider === "mock" ? "test mode" : "OpenAI"})` }] : [])]} />
          <Button variant="primary" icon={mode === "ai" ? <Sparkles className="size-4" /> : <Wand2 className="size-4" />} loading={genAll.isPending || copyJobActive} onClick={() => genAll.mutate()}>
            {copyJobActive ? "Writing…" : "Write all"}
          </Button>
        </div>
        {blockers.length > 0 && <Notice tone="warning" className="mt-4" title="Some facts are still missing">
          {blockers.map((b) => b.message).join(" ")} Copy can be written now, but it cannot be approved until these are filled in on the Overview tab.
        </Notice>}
      </Panel>
      <div className="grid lg:grid-cols-[260px_1fr] gap-6 items-start">
        <nav className="panel p-2 lg:sticky lg:top-8" aria-label="Channels">
          {channels.map((c) => {
            const errs = c.copy?.validation.errors.length ?? 0;
            return (
              <button key={c.key} onClick={() => setSelected(c.key)}
                className={cx("w-full text-left rounded-md px-3 py-2 flex items-center gap-2 cursor-pointer transition-colors",
                  current?.key === c.key ? "bg-velvet-50" : "hover:bg-wash", !c.included && "opacity-50")}>
                <span className="flex-1 min-w-0">
                  <span className={cx("block text-[13.5px] truncate", current?.key === c.key ? "font-semibold text-velvet" : "font-medium")}>{c.name}</span>
                  <span className="block text-[12px] text-steel">{!c.included ? "Not used for this watch" : !c.copy ? "No copy yet" : errs ? `${errs} issue${errs > 1 ? "s" : ""}` : c.approved ? "Approved" : "Ready for review"}</span>
                </span>
                <span className={cx("size-2 rounded-full shrink-0", !c.included || !c.copy ? "bg-line-strong" : errs || c.copy.stale.length ? "bg-danger" : c.approved ? "bg-velvet" : "bg-brass")} />
              </button>
            );
          })}
        </nav>
        {current && <ChannelEditor key={current.key} ch={current} data={q.data} watchId={w.id} onJob={() => qc.invalidateQueries({ queryKey: keys.watch(w.id) })} />}
      </div>
    </div>
  );
}
