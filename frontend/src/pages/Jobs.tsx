import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw, X } from "lucide-react";
import { get, post } from "../lib/api";
import { keys, useAction } from "../lib/hooks";
import { actorName, ago } from "../lib/format";
import type { Job } from "../lib/types";
import { Button, Empty, JOB_TONE, Loading, PageHeader, Panel, Pill, Progress, Tabs } from "../components/ui";

export default function Jobs() {
  const [status, setStatus] = useState<string>("active");
  const filter = status === "active" ? "pending,running" : status === "all" ? undefined : status;
  const q = useQuery({
    queryKey: keys.jobs({ status }), queryFn: () => get<{ items: Job[] }>("/api/jobs", { status: filter, limit: 200 }),
    refetchInterval: (qq) => (qq.state.data?.items.some((j) => j.status === "running" || j.status === "pending") ? 2000 : 10000),
  });
  const inv = [["jobs"]];
  const retry = useAction((id: string) => post(`/api/jobs/${id}/retry`), { success: "Queued again", invalidate: inv });
  const cancel = useAction((id: string) => post(`/api/jobs/${id}/cancel`), { success: "Cancelling", invalidate: inv });
  return (
    <>
      <PageHeader title="Background jobs" sub="Photo processing, AI work and publishing run here so the studio stays responsive. Jobs survive a restart and retry automatically." />
      <Tabs value={status} onChange={setStatus} className="mb-5" tabs={[
        { key: "active", label: "Running & queued" }, { key: "failed", label: "Failed" }, { key: "completed", label: "Completed" }, { key: "all", label: "All" },
      ]} />
      {q.isLoading ? <Loading /> : !q.data?.items.length ? <Panel><Empty title="No jobs here">{status === "active" ? "Nothing is running right now." : "Nothing to show."}</Empty></Panel> : (
        <Panel pad={false}>
          <ul className="divide-y divide-line">
            {q.data.items.map((j) => (
              <li key={j.id} className="px-5 py-3.5 grid md:grid-cols-[1fr_220px_auto] gap-3 items-center">
                <div className="min-w-0">
                  <div className="text-[13.5px] font-medium">{j.label}{j.channel ? ` · ${j.channel}` : ""}
                    {j.sku && j.watch_id && <Link to={`/watches/${j.watch_id}`} className="ml-2 text-steel font-normal hover:underline tabular-nums">{j.sku}</Link>}</div>
                  <div className="text-[12.5px] text-steel">
                    {j.message} · attempt {j.attempts} of {j.max_attempts} · {actorName(j.created_by ?? "system")} · {ago(j.created_at)}
                  </div>
                  {j.error && <div className="text-[12.5px] text-danger mt-1 break-words">{j.error}</div>}
                </div>
                {j.status === "running" || j.status === "pending" ? <Progress value={j.progress} indeterminate={j.status === "pending"} tone="info" /> : <span className="hidden md:block" />}
                <div className="flex items-center gap-2 justify-end">
                  <Pill tone={JOB_TONE[j.status]}>{j.status}</Pill>
                  {(j.status === "failed" || j.status === "cancelled") && <Button size="sm" icon={<RotateCcw className="size-3.5" />} onClick={() => retry.mutate(j.id)}>Retry</Button>}
                  {(j.status === "pending" || j.status === "running") && <Button size="sm" variant="ghost" icon={<X className="size-3.5" />} onClick={() => cancel.mutate(j.id)}>Cancel</Button>}
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </>
  );
}
