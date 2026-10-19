import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowUpRight, BadgeCheck, Camera, ClipboardList, FileText, ImageUp, Plus, ShieldAlert, Sparkles } from "lucide-react";
import { get } from "../lib/api";
import { keys } from "../lib/hooks";
import { actorName, ago, money, plural } from "../lib/format";
import type { ActivityItem, Job, WatchSummary } from "../lib/types";
import { useAuth } from "../lib/auth";
import { Button, Empty, Loading, Notice, PageHeader, Panel, PanelHeader, Progress, StatusPill, cx } from "../components/ui";

interface DashboardData {
  counts: Record<string, number>;
  by_status: Record<string, number>;
  inventory_value_sgd: number;
  attention: WatchSummary[];
  running_jobs: Job[];
  failed_jobs: Job[];
  recent_activity: ActivityItem[];
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function Stage({ label, count, to, emphasis }: { label: string; count: number; to: string; emphasis?: boolean }) {
  return (
    <Link to={to} className="group relative flex-1 min-w-[120px] px-4 py-4 rounded-md hover:bg-wash/70 transition-colors">
      <div className={cx("font-display text-[44px] leading-none tabular-nums", emphasis && count > 0 ? "text-brass" : "text-ink")}>{count}</div>
      <div className="mt-2 text-[13px] text-steel group-hover:text-ink flex items-center gap-1">{label}<ArrowUpRight className="size-3 opacity-0 group-hover:opacity-100" /></div>
    </Link>
  );
}

function Movement({ d }: { d: DashboardData }) {
  const s = d.by_status;
  return (
    <Panel pad={false} className="mb-6 overflow-hidden">
      <div className="flex flex-wrap items-stretch">
        <div className="flex flex-1 flex-wrap items-stretch">
          <Stage label="In preparation" count={(s.draft ?? 0) + (s.processing ?? 0)} to="/inventory?status=draft&status=processing" />
          <Chevron />
          <Stage label="Awaiting your review" count={s.awaiting_review ?? 0} to="/review" emphasis />
          <Chevron />
          <Stage label="Approved" count={s.approved ?? 0} to="/inventory?status=approved" />
          <Chevron />
          <Stage label="Published" count={s.published ?? 0} to="/inventory?status=published" />
        </div>
        <div className="flex items-stretch border-t md:border-t-0 md:border-l border-line bg-paper/50 w-full md:w-auto">
          <Stage label="Reserved" count={d.counts.reserved} to="/inventory?availability=reserved" />
          <Stage label="Sold" count={d.counts.sold} to="/inventory?availability=sold" />
        </div>
      </div>
      <div className="flex flex-wrap gap-x-8 gap-y-1 px-5 py-3 border-t border-line text-[13px] text-steel bg-paper/40">
        <span><b className="text-ink font-semibold tabular-nums">{d.counts.total}</b> watches in inventory</span>
        <span><b className="text-ink font-semibold tabular-nums">{d.counts.available}</b> available</span>
        <span>Available stock value <b className="text-ink font-semibold tabular-nums">{money(d.inventory_value_sgd)}</b></span>
        <span><b className="text-ink font-semibold tabular-nums">{d.counts.published_listings}</b> live listings</span>
        {d.counts.simulated_listings > 0 && <span className="text-info">{plural(d.counts.simulated_listings, "simulated listing")} (not live)</span>}
      </div>
    </Panel>
  );
}

function Chevron() {
  return <div className="hidden sm:flex items-center text-line-strong select-none" aria-hidden>
    <svg width="14" height="40" viewBox="0 0 14 40"><path d="M2 2 L12 20 L2 38" fill="none" stroke="currentColor" strokeWidth="1.2" /></svg>
  </div>;
}

function NeedsYou({ c }: { c: Record<string, number> }) {
  const rows = [
    { n: c.privacy_checks, icon: <ShieldAlert className="size-4 text-brass" />, text: plural(c.privacy_checks, "photo") + " need a privacy check (serials or engraving)", to: "/review", cta: "Check photos" },
    { n: c.images_awaiting_review, icon: <Camera className="size-4 text-brass" />, text: plural(c.images_awaiting_review, "studio image") + " waiting for approval", to: "/review", cta: "Review" },
    { n: c.listings_awaiting_approval, icon: <FileText className="size-4 text-brass" />, text: plural(c.listings_awaiting_approval, "channel listing") + " waiting for approval", to: "/review", cta: "Review" },
    { n: c.open_manual_tasks, icon: <ClipboardList className="size-4 text-brass" />, text: plural(c.open_manual_tasks, "manual posting task") + " (draft packs, sold checklists)", to: "/publishing", cta: "Open tasks" },
    { n: c.failed, icon: <AlertTriangle className="size-4 text-danger" />, text: plural(c.failed, "failed job") + " or publishing error", to: "/publishing", cta: "See what failed" },
    { n: c.awaiting_processing, icon: <Sparkles className="size-4 text-info" />, text: plural(c.awaiting_processing, "watch", "watches") + " with photos still processing", to: "/jobs", cta: "View jobs" },
  ].filter((r) => r.n > 0);
  return (
    <Panel>
      <PanelHeader title="Needs you" sub="Work waiting on a decision or an action." />
      {rows.length === 0 ? (
        <div className="flex items-center gap-3 text-[13.5px] text-steel py-3"><BadgeCheck className="size-5 text-velvet" /> Nothing is waiting on you.</div>
      ) : (
        <ul className="divide-y divide-line -mx-5">
          {rows.map((r, i) => (
            <li key={i} className="flex items-center gap-3 px-5 py-3">
              {r.icon}
              <span className="flex-1 text-[13.5px]">{r.text}</span>
              <Link to={r.to} className="text-[13px] font-medium text-velvet hover:underline underline-offset-4">{r.cta}</Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export default function Dashboard() {
  const { state } = useAuth();
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: keys.dashboard,
    queryFn: () => get<DashboardData>("/api/dashboard"),
    refetchInterval: (qq) => (qq.state.data?.running_jobs.length ? 3000 : 20000),
  });
  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) return <Notice tone="danger">The dashboard could not be loaded.</Notice>;
  const d = q.data;
  const waiting = (d.counts.images_awaiting_review ?? 0) + (d.counts.listings_awaiting_approval ?? 0) + (d.counts.privacy_checks ?? 0);
  return (
    <>
      <PageHeader
        title={`${greeting()}, ${state?.user?.display_name ?? ""}`}
        sub={d.counts.total === 0 ? "Add your first watch to start." : waiting ? `${plural(waiting, "item")} waiting for your review.` : "Everything in the studio is up to date."}
        actions={<>
          <Button icon={<ImageUp className="size-4" />} onClick={() => navigate("/watches/new")}>Upload photos</Button>
          <Button icon={<FileText className="size-4" />} onClick={() => navigate("/review")}>Generate listings</Button>
          <Button icon={<BadgeCheck className="size-4" />} onClick={() => navigate("/review")}>Review pending</Button>
          <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => navigate("/watches/new")}>New watch</Button>
        </>}
      />
      {d.counts.total === 0 ? (
        <Panel><Empty title="No watches yet" action={<Button variant="primary" onClick={() => navigate("/watches/new")}>Add a watch</Button>}>
          Create a watch record and drop in its photographs. The studio checks them for serial numbers, cuts out the watch and prepares studio images.
        </Empty></Panel>
      ) : (
        <>
          <Movement d={d} />
          <div className="grid xl:grid-cols-[1.35fr_1fr] gap-6">
            <div className="space-y-6 min-w-0">
              <NeedsYou c={d.counts} />
              <Panel>
                <PanelHeader title="In progress" sub="Watches being processed or waiting for review." actions={<Link className="text-[13px] text-velvet hover:underline" to="/inventory">All inventory</Link>} />
                {d.attention.length === 0 ? <p className="text-steel text-[13.5px]">No watches in progress.</p> : (
                  <ul className="grid sm:grid-cols-2 gap-3">
                    {d.attention.map((w) => (
                      <li key={w.id}>
                        <Link to={`/watches/${w.id}`} className="flex gap-3 items-center rounded-lg border border-line p-2.5 hover:border-line-strong hover:bg-paper/50 transition-colors">
                          <div className="size-14 shrink-0 rounded-md bg-stage overflow-hidden">
                            {w.thumb && <img src={w.thumb} alt="" className="size-full object-cover" loading="lazy" />}
                          </div>
                          <div className="min-w-0">
                            <div className="font-display text-[17px] leading-tight truncate">{w.brand} {w.model}</div>
                            <div className="text-[12.5px] text-steel mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1"><span className="tabular-nums whitespace-nowrap">{w.sku}</span><StatusPill status={w.status} label={w.status_label} /></div>
                          </div>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </div>
            <div className="space-y-6 min-w-0">
              {(d.running_jobs.length > 0 || d.failed_jobs.length > 0) && (
                <Panel>
                  <PanelHeader title="Background work" actions={<Link to="/jobs" className="text-[13px] text-velvet hover:underline">All jobs</Link>} />
                  <ul className="space-y-3">
                    {d.running_jobs.map((j) => (
                      <li key={j.id}>
                        <div className="flex justify-between text-[13px] mb-1"><span>{j.label}{j.sku ? ` · ${j.sku}` : ""}</span><span className="text-steel">{j.message}</span></div>
                        <Progress value={j.progress} indeterminate={j.status === "pending"} tone="info" />
                      </li>
                    ))}
                    {d.failed_jobs.slice(0, 4).map((j) => (
                      <li key={j.id} className="text-[13px] flex gap-2"><AlertTriangle className="size-4 text-danger shrink-0" /><span><b className="font-medium">{j.label}{j.sku ? ` · ${j.sku}` : ""}</b> failed: <span className="text-steel">{j.error}</span></span></li>
                    ))}
                  </ul>
                </Panel>
              )}
              <Panel>
                <PanelHeader title="Recent activity" actions={<Link to="/activity" className="text-[13px] text-velvet hover:underline">Full log</Link>} />
                <ol className="relative border-l border-line ml-1.5 space-y-4">
                  {d.recent_activity.map((a) => (
                    <li key={a.id} className="pl-4 relative">
                      <span className="absolute -left-[4.5px] top-1.5 size-2 rounded-full bg-line-strong" />
                      <div className="text-[13.5px] leading-snug">{a.summary}</div>
                      <div className="text-[12px] text-steel mt-0.5">
                        {actorName(a.actor)} · {ago(a.at)}{a.sku && a.watch_id ? <> · <Link to={`/watches/${a.watch_id}`} className="hover:underline">{a.sku}</Link></> : null}
                      </div>
                    </li>
                  ))}
                </ol>
              </Panel>
            </div>
          </div>
        </>
      )}
    </>
  );
}
