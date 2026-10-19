import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, FileSpreadsheet, PlugZap } from "lucide-react";
import { get, post } from "../lib/api";
import { keys, useAction } from "../lib/hooks";
import { ago, dateTime } from "../lib/format";
import type { IntegrationInfo, Job, ManualTask } from "../lib/types";
import { Button, Empty, JOB_TONE, LISTING_TONE, Loading, Notice, PageHeader, Panel, PanelHeader, Pill, Progress, Tabs, Toggle } from "../components/ui";
import { TaskItem } from "./watch/PublishingTab";

interface Listing {
  id: string; watch_id: string; sku: string; watch: string; channel: string; channel_name: string; status: string; label: string;
  mode: string; external_url: string | null; published_at: string | null; last_error: string | null; updated_at: string;
}
interface Overview {
  platforms: Array<{ key: string; name: string; route: string; enabled: boolean; mode: { mode: string; message: string; state: string }; integration: IntegrationInfo | null }>;
  queue: Job[]; scheduled: Job[]; recent_jobs: Job[];
  failures: Listing[]; published: Listing[]; simulated: Listing[]; listings: Listing[]; manual_tasks: ManualTask[];
}

const STATE_TONE: Record<string, any> = { connected: "velvetSolid", configured: "info", not_configured: "muted", error: "danger", unsupported: "muted" };

function ListingTable({ rows, empty }: { rows: Listing[]; empty: string }) {
  if (!rows.length) return <p className="text-[13px] text-steel">{empty}</p>;
  return (
    <div className="overflow-x-auto -mx-5">
      <table className="w-full text-[13.5px] min-w-[640px]">
        <thead><tr className="text-left text-[12.5px] text-steel border-y border-line bg-paper/60">
          <th className="font-medium py-2 pl-5">Watch</th><th className="font-medium px-3">Channel</th><th className="font-medium px-3">Status</th><th className="font-medium px-3 pr-5">When</th>
        </tr></thead>
        <tbody className="divide-y divide-line">
          {rows.map((l) => (
            <tr key={l.id} className="align-top">
              <td className="py-2.5 pl-5"><Link className="hover:underline" to={`/watches/${l.watch_id}/publishing`}><span className="tabular-nums text-steel">{l.sku}</span> {l.watch}</Link></td>
              <td className="py-2.5 px-3">{l.channel_name}</td>
              <td className="py-2.5 px-3">
                <Pill tone={LISTING_TONE[l.status] ?? "neutral"} dot>{l.label}</Pill>
                {l.external_url && !l.external_url.includes("simulation.invalid") && <a className="ml-2 text-velvet text-[12.5px] hover:underline inline-flex items-center gap-1" href={l.external_url} target="_blank" rel="noreferrer noopener">Open<ExternalLink className="size-3" /></a>}
                {l.last_error && <div className="text-[12.5px] text-danger mt-1 max-w-[52ch]">{l.last_error}</div>}
              </td>
              <td className="py-2.5 px-3 pr-5 text-steel whitespace-nowrap">{ago(l.published_at ?? l.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Platform({ p }: { p: Overview["platforms"][number] }) {
  const inv = [keys.publishing, keys.integrations];
  const test = useAction(() => post<IntegrationInfo>(`/api/integrations/${p.key}/test`), { success: (r) => `${p.name}: ${r.state_label}`, invalidate: inv });
  const live = useAction((v: boolean) => post(`/api/integrations/${p.key}/live`, { enabled: v }), { success: "Saved", invalidate: inv });
  const i = p.integration;
  return (
    <li className="rounded-lg border border-line p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold text-[14px]">{p.name}</div>
          <div className="text-[12px] text-steel">{p.route === "manual" ? "No posting API — draft pack" : p.route === "feed" ? "Product feed" : "Official API"}</div>
        </div>
        {i ? <Pill tone={STATE_TONE[i.state]}>{i.state_label}</Pill> : <Pill tone="brass">You post it</Pill>}
      </div>
      <p className="text-[12.5px] text-ink-2">{p.mode.message}</p>
      {i && i.missing_env.length > 0 && <p className="text-[12px] text-steel">Needs: <span className="text-ink-2">{i.missing_env.join(", ")}</span></p>}
      {i && (
        <div className="mt-auto flex flex-wrap items-center gap-3 pt-1">
          <Button size="sm" icon={<PlugZap className="size-3.5" />} disabled={i.state === "not_configured"} loading={test.isPending} onClick={() => test.mutate()}>Test connection</Button>
          <Toggle checked={i.live_enabled} disabled={i.state !== "connected"} onChange={(v) => live.mutate(v)} label="Live publishing" />
        </div>
      )}
      {!p.enabled && <p className="text-[12px] text-brass">Switched off in Settings → Channels.</p>}
    </li>
  );
}

export default function Publishing() {
  const q = useQuery({ queryKey: keys.publishing, queryFn: () => get<Overview>("/api/publishing/overview"), refetchInterval: (qq) => (qq.state.data?.queue.length ? 3000 : 15000) });
  const [tab, setTab] = useState<"tasks" | "queue" | "published" | "failures" | "platforms">("tasks");
  const feed = useAction(() => post<any>("/api/publishing/chrono24/feed"), { success: (r) => `Chrono24 feed rebuilt: ${r.rows} watch(es)`, invalidate: [keys.publishing] });
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Notice tone="danger">The publishing centre could not be loaded.</Notice>;
  const d = q.data;
  const liveCount = d.platforms.filter((p) => p.mode.mode === "live").length;
  return (
    <>
      <PageHeader title="Publishing" sub="Where every listing stands, what is queued, what failed, and what you need to post yourself."
        actions={<>
          <Button icon={<FileSpreadsheet className="size-4" />} loading={feed.isPending} onClick={() => feed.mutate()}>Rebuild Chrono24 feed</Button>
          <a href="/api/publishing/chrono24/feed.csv" className="inline-flex items-center h-9 px-3 rounded-md border border-line-strong text-[13.5px] hover:bg-wash">Download feed</a>
        </>} />
      {liveCount === 0 && <Notice tone="info" className="mb-5" title="No platform is connected for live publishing yet">
        API channels run in simulation: the full flow is exercised, but nothing is posted and simulated listings are never counted as live. Add credentials in .env, test the connection below, then switch live publishing on.
      </Notice>}
      <Tabs value={tab} onChange={setTab} className="mb-5" tabs={[
        { key: "tasks", label: "Your tasks", badge: d.manual_tasks.length ? <Pill tone="brass">{d.manual_tasks.length}</Pill> : undefined },
        { key: "queue", label: "Queue", badge: d.queue.length ? <Pill tone="info">{d.queue.length}</Pill> : undefined },
        { key: "published", label: "Published" },
        { key: "failures", label: "Failures", badge: d.failures.length ? <Pill tone="danger">{d.failures.length}</Pill> : undefined },
        { key: "platforms", label: "Platforms" },
      ]} />
      {tab === "tasks" && (
        <Panel>
          <PanelHeader title="Manual tasks" sub="Draft packs to post on channels without an API, and updates after a watch is reserved or sold." />
          {!d.manual_tasks.length ? <Empty title="No tasks">Nothing needs posting or updating by hand.</Empty> : (
            <ul className="space-y-3">{d.manual_tasks.map((t) => (
              <div key={t.id}>
                <Link to={`/watches/${t.watch_id}/publishing`} className="text-[12.5px] text-steel hover:underline">{t.sku} · {t.watch}</Link>
                <TaskItem t={t} inv={[keys.publishing, ["tasks"]]} />
              </div>
            ))}</ul>
          )}
        </Panel>
      )}
      {tab === "queue" && (
        <Panel>
          <PanelHeader title="Publishing queue" sub="Publish and channel-update jobs. Scheduled jobs run at their time." />
          {!d.recent_jobs.length ? <p className="text-[13px] text-steel">No publishing jobs yet.</p> : (
            <ul className="divide-y divide-line">
              {d.recent_jobs.map((j) => (
                <li key={j.id} className="py-3 grid sm:grid-cols-[1fr_200px_auto] gap-3 items-center text-[13.5px]">
                  <div>
                    <div className="font-medium">{j.label} · {j.channel} {j.sku && <span className="text-steel font-normal">· {j.sku}</span>}</div>
                    <div className="text-[12.5px] text-steel">{j.status === "pending" && j.run_after && new Date(j.run_after + "") > new Date() ? `Scheduled for ${dateTime(j.run_after)}` : j.message}{j.error ? ` — ${j.error}` : ""}</div>
                  </div>
                  {j.status === "running" || j.status === "pending" ? <Progress value={j.progress} indeterminate={j.status === "pending"} tone="info" /> : <span />}
                  <Pill tone={JOB_TONE[j.status]}>{j.status}</Pill>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}
      {tab === "published" && (
        <div className="space-y-5">
          <Panel><PanelHeader title="Live listings" sub="Posted through an API, or posted by you with the link recorded." /><ListingTable rows={d.published} empty="No live listings yet." /></Panel>
          <Panel><PanelHeader title="Simulated listings" sub="Exercised in simulation; nothing was posted. Not counted as live." /><ListingTable rows={d.simulated} empty="None." /></Panel>
        </div>
      )}
      {tab === "failures" && (
        <Panel><PanelHeader title="Failures" sub="Publishing or channel updates that did not succeed. Open the watch to retry." /><ListingTable rows={d.failures} empty="Nothing has failed." /></Panel>
      )}
      {tab === "platforms" && (
        <Panel>
          <PanelHeader title="Platforms" sub="Live publishing can only be switched on after a successful connection test." />
          <ul className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">{d.platforms.map((p) => <Platform key={p.key} p={p} />)}</ul>
        </Panel>
      )}
    </>
  );
}
