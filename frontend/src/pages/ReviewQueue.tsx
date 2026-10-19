import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, Wand2 } from "lucide-react";
import { get, post } from "../lib/api";
import { keys, useAction } from "../lib/hooks";
import { ago, money } from "../lib/format";
import type { WatchSummary } from "../lib/types";
import { Button, Empty, Loading, PageHeader, Panel, Pill, StatusPill } from "../components/ui";

interface QueueItem extends WatchSummary {
  pending_images: number;
  pending_channels: number;
  fact_blockers: number;
  package_approved: boolean;
  open_suggestions: number;
}

function Row({ w }: { w: QueueItem }) {
  const write = useAction(() => post(`/api/watches/${w.id}/copy/generate`, { mode: "template" }), {
    success: "Copy written for every channel", invalidate: [keys.reviewQueue, keys.copy(w.id), keys.watch(w.id)],
  });
  const noCopy = w.pending_channels === 0 && !w.package_approved;
  return (
    <li className="panel p-4 flex flex-wrap gap-4 items-center">
      <Link to={`/watches/${w.id}/review`} className="size-20 rounded-md bg-stage overflow-hidden shrink-0">
        {w.thumb && <img src={w.thumb} alt="" className="size-full object-cover" loading="lazy" />}
      </Link>
      <div className="flex-1 min-w-[220px]">
        <Link to={`/watches/${w.id}/review`} className="font-display text-[21px] leading-tight hover:underline">{w.brand} {w.model}</Link>
        <div className="text-[12.5px] text-steel mt-0.5 flex flex-wrap items-center gap-2"><span className="tabular-nums">{w.sku}</span><span>{money(w.price_sgd)}</span><StatusPill status={w.status} label={w.status_label} /><span>updated {ago(w.updated_at)}</span></div>
        <div className="flex flex-wrap gap-1.5 mt-2">
          {w.pending_images > 0 && <Pill tone="brass">{w.pending_images} image{w.pending_images > 1 ? "s" : ""} to approve</Pill>}
          {w.pending_channels > 0 && <Pill tone="brass">{w.pending_channels} channel{w.pending_channels > 1 ? "s" : ""} to approve</Pill>}
          {w.fact_blockers > 0 && <Pill tone="danger">{w.fact_blockers} missing fact{w.fact_blockers > 1 ? "s" : ""}</Pill>}
          {w.open_suggestions > 0 && <Pill tone="info">{w.open_suggestions} suggestion{w.open_suggestions > 1 ? "s" : ""}</Pill>}
          {noCopy && <Pill tone="muted">No listing copy yet</Pill>}
        </div>
      </div>
      <div className="flex gap-2">
        {noCopy && <Button icon={<Wand2 className="size-4" />} loading={write.isPending} onClick={() => write.mutate()}>Write copy</Button>}
        <Link to={`/watches/${w.id}/review`}><Button variant="primary" icon={<BadgeCheck className="size-4" />}>Review</Button></Link>
      </div>
    </li>
  );
}

export default function ReviewQueue() {
  const q = useQuery({ queryKey: keys.reviewQueue, queryFn: () => get<{ items: QueueItem[] }>("/api/review/queue"), refetchInterval: 15000 });
  return (
    <>
      <PageHeader title="Review" sub="Watches with photos, facts or listing copy waiting for your decision. Approvals are tied to the exact content you see." />
      {q.isLoading ? <Loading /> : !q.data?.items.length ? (
        <Panel><Empty icon={<BadgeCheck className="size-8" />} title="Nothing to review">Every watch in progress is approved, or still being prepared.</Empty></Panel>
      ) : (
        <ul className="space-y-3">{q.data.items.map((w) => <Row key={w.id} w={w} />)}</ul>
      )}
    </>
  );
}
