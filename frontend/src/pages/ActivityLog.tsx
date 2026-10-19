import { useState } from "react";
import { Link } from "react-router-dom";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { get } from "../lib/api";
import { actorName, dateTime } from "../lib/format";
import type { ActivityItem } from "../lib/types";
import { Button, Empty, Loading, PageHeader, Panel } from "../components/ui";

export default function ActivityLog() {
  const [q, setQ] = useState("");
  const list = useInfiniteQuery({
    queryKey: ["activity-log", q],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => get<{ items: ActivityItem[] }>("/api/activity", { q, before_id: pageParam || undefined, limit: 100 }),
    getNextPageParam: (last) => (last.items.length === 100 ? last.items[last.items.length - 1].id : undefined),
  });
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <>
      <PageHeader title="Activity log" sub="Every approval, publish, price change, status change and setting change — who, what and when." />
      <Panel className="mb-5">
        <label className="relative block max-w-md">
          <Search className="size-4 text-steel absolute left-3 top-1/2 -translate-y-1/2" />
          <input className="field pl-9" placeholder="Search the log" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
      </Panel>
      {list.isLoading ? <Loading /> : !items.length ? <Panel><Empty title="Nothing recorded yet" /></Panel> : (
        <Panel pad={false}>
          <ol className="divide-y divide-line">
            {items.map((a) => (
              <li key={a.id} className="px-5 py-2.5 grid md:grid-cols-[150px_110px_1fr_auto] gap-x-4 gap-y-0.5 text-[13.5px]">
                <span className="text-steel tabular-nums">{dateTime(a.at)}</span>
                <span className="tabular-nums">{a.sku && a.watch_id ? <Link className="hover:underline" to={`/watches/${a.watch_id}`}>{a.sku}</Link> : <span className="text-steel-2">—</span>}</span>
                <span>{a.summary}</span>
                <span className="text-steel text-[12.5px]">{actorName(a.actor)}</span>
              </li>
            ))}
          </ol>
          {list.hasNextPage && <div className="p-4 text-center"><Button loading={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>Load older entries</Button></div>}
        </Panel>
      )}
    </>
  );
}
