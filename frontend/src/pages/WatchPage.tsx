import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Archive, ChevronLeft, RotateCcw } from "lucide-react";
import { del, post } from "../lib/api";
import { keys, useAction, useWatch } from "../lib/hooks";
import { money, CUSTODY } from "../lib/format";
import { Button, Loading, Notice, Pill, Progress, StatusPill, Tabs, useConfirm } from "../components/ui";
import OverviewTab from "./watch/OverviewTab";
import PhotosTab from "./watch/PhotosTab";
import ListingTab from "./watch/ListingTab";
import ReviewTab from "./watch/ReviewTab";
import PublishingTab from "./watch/PublishingTab";
import ActivityTab from "./watch/ActivityTab";

type Tab = "overview" | "photos" | "listing" | "review" | "publishing" | "activity";
const TABS: Tab[] = ["overview", "photos", "listing", "review", "publishing", "activity"];

const ACTION_LABELS: Record<string, { label: string; confirm: string; body: string; danger?: boolean }> = {
  reserved: { label: "Mark reserved", confirm: "Mark reserved", body: "The inventory changes now. Connected channels are updated in the background and manual channels get a checklist." },
  sold: { label: "Mark sold", confirm: "Mark sold", body: "The inventory changes now. Live listings are taken down where the platform allows; the rest appear on your checklist.", danger: true },
  withdrawn: { label: "Withdraw", confirm: "Withdraw", body: "The watch is taken off sale. Live listings are removed where possible; the rest appear on your checklist.", danger: true },
  available: { label: "Make available again", confirm: "Make available", body: "The watch returns to sale. Channels that were marked reserved are updated." },
  reopen: { label: "Reopen", confirm: "Reopen", body: "Use only if the sale fell through. The watch returns to its listing workflow." },
};

export default function WatchPage() {
  const { id = "", tab = "overview" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const confirm = useConfirm();
  const q = useWatch(id);
  const invalidate = [keys.watch(id), keys.review(id), keys.copy(id), keys.publishing];
  const statusAction = useAction((action: string) => post<any>(`/api/watches/${id}/status`, { action }), {
    success: (r) => r.sync?.message ?? "Status updated", invalidate,
  });
  const archive = useAction(() => del(`/api/watches/${id}`), {
    success: "Watch archived. Photos and records are kept.", invalidate: [["watches"]], onSuccess: () => navigate("/inventory"),
  });
  const restore = useAction(() => post(`/api/watches/${id}/restore`), { success: "Watch restored", invalidate });

  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) return <Notice tone="danger" title="This watch could not be loaded">It may have been removed. <Link className="underline" to="/inventory">Back to inventory</Link></Notice>;
  const { watch: w, summary, assets, jobs, readiness } = q.data;
  const active = jobs.filter((j) => j.status === "pending" || j.status === "running");
  const current = (TABS.includes(tab as Tab) ? tab : "overview") as Tab;
  const blockers = readiness.issues.filter((i) => i.severity === "blocker").length;
  const pendingReview = readiness.summary.images_total - readiness.summary.images_approved + readiness.summary.channels_with_copy - readiness.summary.channels_approved;

  return (
    <>
      <div className="mb-5">
        <Link to="/inventory" className="inline-flex items-center gap-1 text-[13px] text-steel hover:text-ink"><ChevronLeft className="size-4" /> Inventory</Link>
      </div>
      <header className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div className="min-w-0">
          <h1 className="font-display text-[38px] leading-[1.05]">{w.brand} {w.model}</h1>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 mt-2 text-[13.5px] text-steel">
            <span className="tabular-nums text-ink-2 font-medium">{w.sku}</span>
            {w.reference && <span>Ref. {w.reference}</span>}
            {w.year && <span>{w.year}</span>}
            <span className="tabular-nums">{money(w.price_sgd)}</span>
            <span>{CUSTODY[w.custody] ?? w.custody}</span>
            <StatusPill status={w.status} label={w.status_label} />
            {w.is_consignment && <Pill tone="muted">Consignment</Pill>}
            {w.archived && <Pill tone="danger">Archived</Pill>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {w.archived ? (
            <Button icon={<RotateCcw className="size-4" />} onClick={() => restore.mutate()}>Restore</Button>
          ) : (
            <>
              {w.allowed_actions.map((a) => ACTION_LABELS[a] && (
                <Button key={a} variant={a === "sold" ? "primary" : "secondary"} loading={statusAction.isPending && statusAction.variables === a}
                  onClick={async () => {
                    const meta = ACTION_LABELS[a];
                    if (await confirm({ title: `${meta.label}?`, body: meta.body, confirm: meta.confirm, danger: meta.danger })) statusAction.mutate(a);
                  }}>
                  {ACTION_LABELS[a].label}
                </Button>
              ))}
              <Button variant="ghost" icon={<Archive className="size-4" />} onClick={async () => {
                if (await confirm({ title: "Archive this watch?", body: "It disappears from the inventory list. Photos, copy and history are kept and it can be restored. Watches still listed on a channel cannot be archived.", confirm: "Archive", danger: true })) archive.mutate();
              }}>Archive</Button>
            </>
          )}
        </div>
      </header>

      {active.length > 0 && (
        <div className="panel px-4 py-3 mb-5 flex flex-wrap items-center gap-4">
          <div className="text-[13px] font-medium">Working on {active.length} task{active.length > 1 ? "s" : ""}</div>
          <div className="flex-1 min-w-[200px] grid gap-1.5">
            {active.slice(0, 3).map((j) => (
              <div key={j.id} className="flex items-center gap-3 text-[12.5px]">
                <span className="w-44 truncate text-steel">{j.label}: {j.message}</span>
                <Progress value={j.progress} indeterminate={j.status === "pending"} tone="info" className="flex-1" />
              </div>
            ))}
          </div>
        </div>
      )}

      <Tabs<Tab>
        className="mb-6"
        value={current}
        onChange={(t) => navigate(`/watches/${id}/${t}`, { replace: true })}
        tabs={[
          { key: "overview", label: "Overview", badge: blockers ? <Pill tone="brass">{blockers}</Pill> : undefined },
          { key: "photos", label: "Photos", badge: <span className="text-steel text-[12px] tabular-nums">{assets.length}</span> },
          { key: "listing", label: "Listing copy" },
          { key: "review", label: "Review & approval", badge: pendingReview > 0 ? <Pill tone="brass">{pendingReview}</Pill> : readiness.package.approved ? <Pill tone="velvet">Approved</Pill> : undefined },
          { key: "publishing", label: "Publishing", badge: summary.open_manual_tasks ? <Pill tone="brass">{summary.open_manual_tasks}</Pill> : undefined },
          { key: "activity", label: "Activity" },
        ]}
      />
      {current === "overview" && <OverviewTab detail={q.data} onSaved={() => qc.invalidateQueries({ queryKey: keys.watch(id) })} />}
      {current === "photos" && <PhotosTab detail={q.data} />}
      {current === "listing" && <ListingTab detail={q.data} />}
      {current === "review" && <ReviewTab detail={q.data} />}
      {current === "publishing" && <PublishingTab detail={q.data} />}
      {current === "activity" && <ActivityTab watchId={id} />}
    </>
  );
}
