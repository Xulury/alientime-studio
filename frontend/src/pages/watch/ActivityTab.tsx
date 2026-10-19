import { useQuery } from "@tanstack/react-query";
import { get } from "../../lib/api";
import { keys } from "../../lib/hooks";
import { actorName, dateTime } from "../../lib/format";
import type { ActivityItem } from "../../lib/types";
import { Loading, Panel, PanelHeader } from "../../components/ui";

export default function ActivityTab({ watchId }: { watchId: string }) {
  const q = useQuery({ queryKey: keys.activity(watchId), queryFn: () => get<{ items: ActivityItem[] }>(`/api/watches/${watchId}/activity`, { limit: 300 }) });
  if (q.isLoading) return <Loading />;
  return (
    <Panel>
      <PanelHeader title="Activity" sub="Every change to this watch: who, what and when." />
      <ol className="divide-y divide-line">
        {q.data?.items.map((a) => (
          <li key={a.id} className="py-2.5 grid sm:grid-cols-[160px_1fr_auto] gap-x-4 gap-y-0.5 text-[13.5px]">
            <span className="text-steel tabular-nums">{dateTime(a.at)}</span>
            <span>{a.summary}</span>
            <span className="text-steel text-[12.5px]">{actorName(a.actor)}</span>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
