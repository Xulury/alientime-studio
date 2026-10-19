import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, ExternalLink, Send } from "lucide-react";
import { get, post } from "../../lib/api";
import { keys, useAction } from "../../lib/hooks";
import type { ManualTask, WatchDetail } from "../../lib/types";
import { ago } from "../../lib/format";
import { Button, LISTING_TONE, Notice, Panel, PanelHeader, Pill, Toggle, cx, useConfirm } from "../../components/ui";

const MODE: Record<string, { label: string; tone: "velvetSolid" | "info" | "brass" | "danger" }> = {
  live: { label: "Live API", tone: "velvetSolid" },
  simulation: { label: "Simulation", tone: "info" },
  manual: { label: "You post it", tone: "brass" },
  unavailable: { label: "Not connected", tone: "danger" },
};

export function TaskItem({ t, inv }: { t: ManualTask; inv: any[] }) {
  const [url, setUrl] = useState("");
  const done = useAction(() => post(`/api/manual-tasks/${t.id}/complete`, { url: url || null }), { success: "Marked done", invalidate: inv });
  const dismiss = useAction(() => post(`/api/manual-tasks/${t.id}/dismiss`), { success: "Task dismissed", invalidate: inv });
  const needsUrl = t.kind === "post";
  return (
    <li className="rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[14px] font-semibold">{t.title}</div>
          <div className="text-[12px] text-steel">{t.channel_name} · created {ago(t.created_at)}</div>
        </div>
        {t.kind === "post" && <a className="inline-flex items-center gap-1.5 text-[13px] text-velvet hover:underline" href={`/api/watches/${t.watch_id}/draft-pack?channels=${t.channel}`}><Download className="size-4" />Draft pack</a>}
      </div>
      <pre className="whitespace-pre-wrap font-sans text-[13px] text-ink-2 mt-2.5 leading-relaxed">{t.instructions}</pre>
      <div className="flex flex-wrap gap-2 mt-3 items-center">
        {needsUrl && <input className="field max-w-md" placeholder="Paste the live link (https://…)" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="Live link" />}
        <Button variant="primary" size="sm" disabled={needsUrl && !/^https?:\/\//.test(url)} loading={done.isPending} onClick={() => done.mutate()}>
          {needsUrl ? "Mark as posted" : "Mark done"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => dismiss.mutate()}>Dismiss</Button>
      </div>
    </li>
  );
}

export default function PublishingTab({ detail }: { detail: WatchDetail }) {
  const w = detail.watch;
  const r = detail.readiness;
  const confirm = useConfirm();
  const [chosen, setChosen] = useState<string[]>([]);
  const [schedule, setSchedule] = useState("");
  const [simulate, setSimulate] = useState(false);
  const inv = [keys.watch(w.id), keys.publishing, keys.review(w.id), ["tasks"]];
  const tasks = useQuery({ queryKey: keys.tasks({ watch: w.id }), queryFn: () => get<{ items: ManualTask[] }>("/api/manual-tasks", { watch_id: w.id }) });
  const publish = useAction(() => post<any>(`/api/watches/${w.id}/publish`, {
    channels: chosen, simulate, schedule_at: schedule ? new Date(schedule).toISOString() : null,
  }), {
    success: (res) => res.results.map((x: any) => `${x.channel}: ${x.message}`).join(" · "), invalidate: inv, onSuccess: () => setChosen([]),
  });
  const withdraw = useAction((ch: string) => post<any>(`/api/watches/${w.id}/channels/${ch}/withdraw`), { success: (res) => res.message, invalidate: inv });
  const ready = r.channels.filter((c) => c.publish_ready);
  const anyLive = r.channels.some((c) => c.mode.mode === "live");
  const onHold = ["reserved", "sold", "withdrawn"].includes(w.status);
  const openTasks = (tasks.data?.items ?? []).filter((t) => t.status === "open");

  return (
    <div className="space-y-6">
      {onHold && (
        <Notice tone={w.status === "reserved" ? "warning" : "info"} title={`This watch is ${w.status}`}>
          {openTasks.length || r.channels.some((c) => c.listing && ["live", "simulated", "manual_posted", "sync_failed"].includes(c.listing.status))
            ? "It is not yet updated on every channel. Finish the checklist below; failed updates are shown in red."
            : "Every channel it was listed on has been updated."}
        </Notice>
      )}
      <Panel pad={false}>
        <div className="p-5 pb-3">
          <PanelHeader className="mb-0" title="Channels" sub="Nothing is published unless its copy and images are approved exactly as they are now."
            actions={<a href={`/api/watches/${w.id}/draft-pack`} className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md border border-line-strong text-[13.5px] hover:bg-wash"><Download className="size-4" />All draft packs</a>} />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13.5px] min-w-[760px]">
            <thead><tr className="text-left text-[12.5px] text-steel border-y border-line bg-paper/60">
              <th className="py-2 pl-5 pr-3 w-12" /><th className="font-medium py-2">Channel</th><th className="font-medium px-3">Route</th><th className="font-medium px-3">Listing</th><th className="font-medium px-3">Ready?</th><th className="pr-5" />
            </tr></thead>
            <tbody className="divide-y divide-line">
              {r.channels.map((c) => {
                const m = MODE[c.mode.mode];
                const listed = c.listing && ["live", "simulated", "manual_posted", "reserved", "sync_failed"].includes(c.listing.status);
                return (
                  <tr key={c.key} className="align-top">
                    <td className="py-3 pl-5 pr-3">
                      <input type="checkbox" aria-label={`Select ${c.name}`} disabled={!c.publish_ready} checked={chosen.includes(c.key)}
                        onChange={(e) => setChosen(e.target.checked ? [...chosen, c.key] : chosen.filter((x) => x !== c.key))} />
                    </td>
                    <td className="py-3 font-medium">{c.name}</td>
                    <td className="py-3 px-3"><Pill tone={m.tone} title={c.mode.message}>{m.label}</Pill><div className="text-[12px] text-steel mt-1 max-w-[32ch]">{c.mode.message}</div></td>
                    <td className="py-3 px-3">
                      {c.listing ? (
                        <>
                          <Pill tone={LISTING_TONE[c.listing.status] ?? "neutral"} dot>{c.listing.label}</Pill>
                          {c.listing.external_url && (
                            c.listing.external_url.includes("simulation.invalid")
                              ? <div className="text-[12px] text-info mt-1">Simulated — nothing was posted</div>
                              : <a href={c.listing.external_url} target="_blank" rel="noreferrer noopener" className="flex items-center gap-1 text-[12px] text-velvet hover:underline mt-1">Open listing <ExternalLink className="size-3" /></a>
                          )}
                          {c.listing.last_error && <div className="text-[12px] text-danger mt-1 max-w-[36ch]">{c.listing.last_error}</div>}
                          {c.listing.published_at && <div className="text-[12px] text-steel mt-0.5">{ago(c.listing.published_at)}</div>}
                        </>
                      ) : <span className="text-steel text-[12.5px]">Not published</span>}
                    </td>
                    <td className="py-3 px-3 text-[12.5px]">
                      {c.publish_ready ? <span className="text-velvet font-medium">Ready</span> : <ul className="text-steel space-y-0.5 max-w-[34ch]">{c.publish_blockers.slice(0, 3).map((b, i) => <li key={i}>{b}</li>)}</ul>}
                    </td>
                    <td className="py-3 pr-5 text-right whitespace-nowrap">
                      <a href={`/api/watches/${w.id}/draft-pack?channels=${c.key}`} className="text-[12.5px] text-velvet hover:underline mr-3">Draft pack</a>
                      {listed && <Button size="sm" variant="ghost" onClick={async () => {
                        if (await confirm({ title: `Remove from ${c.name}?`, body: "Connected channels are updated automatically; for the others you get a checklist item.", confirm: "Remove", danger: true })) withdraw.mutate(c.key);
                      }}>Remove</Button>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-4 px-5 py-4 border-t border-line bg-paper/50 rounded-b-[11px]">
          <div className="text-[13px] text-steel flex-1 min-w-[220px]">{chosen.length ? `${chosen.length} channel(s) selected` : ready.length ? `${ready.length} channel(s) ready — select the ones to publish.` : "No channel is ready yet. Approve the copy and images first."}</div>
          <label className="text-[13px] flex items-center gap-2">Schedule
            <input type="datetime-local" className="field h-9 w-auto" value={schedule} onChange={(e) => setSchedule(e.target.value)} />
          </label>
          {anyLive && <Toggle checked={simulate} onChange={setSimulate} label="Simulate only" />}
          <Button variant="primary" icon={<Send className="size-4" />} disabled={!chosen.length || onHold} loading={publish.isPending} onClick={async () => {
            const live = r.channels.filter((c) => chosen.includes(c.key) && c.mode.mode === "live" && !simulate);
            if (live.length && !(await confirm({ title: "Publish live?", confirm: "Publish", body: `This posts to ${live.map((c) => c.name).join(", ")} for real.` }))) return;
            publish.mutate();
          }}>{schedule ? "Schedule" : "Publish"}</Button>
        </div>
      </Panel>

      <Panel>
        <PanelHeader title="Your checklist" sub="Channels without a posting API, and updates the platforms cannot make themselves." />
        {tasks.isLoading ? null : openTasks.length === 0 ? <p className="text-[13px] text-steel">Nothing to do by hand for this watch.</p> : (
          <ul className="space-y-3">{openTasks.map((t) => <TaskItem key={t.id} t={t} inv={inv} />)}</ul>
        )}
        {(tasks.data?.items ?? []).some((t) => t.status !== "open") && (
          <details className="mt-4 text-[13px]">
            <summary className="cursor-pointer text-steel">Completed tasks</summary>
            <ul className="mt-2 space-y-1">
              {(tasks.data?.items ?? []).filter((t) => t.status !== "open").map((t) => (
                <li key={t.id} className={cx("flex gap-2", t.status === "dismissed" && "text-steel line-through")}>
                  <span>{t.title}</span>{t.live_url && <a href={t.live_url} className="text-velvet hover:underline" target="_blank" rel="noreferrer noopener">link</a>}<span className="text-steel">{ago(t.completed_at)}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </Panel>
    </div>
  );
}
