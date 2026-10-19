import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { errorMessage, get } from "./api";
import { useToast } from "../components/ui";
import type { Job, WatchDetail } from "./types";

export const keys = {
  dashboard: ["dashboard"] as const,
  watches: (params: object) => ["watches", params] as const,
  watch: (id: string) => ["watch", id] as const,
  asset: (id: string) => ["asset", id] as const,
  facts: (id: string) => ["facts", id] as const,
  copy: (id: string) => ["copy", id] as const,
  review: (id: string) => ["review", id] as const,
  approvals: (id: string) => ["approvals", id] as const,
  activity: (id?: string) => ["activity", id ?? "all"] as const,
  publishing: ["publishing"] as const,
  tasks: (params: object) => ["tasks", params] as const,
  jobs: (params: object) => ["jobs", params] as const,
  settings: ["settings"] as const,
  ai: ["ai"] as const,
  integrations: ["integrations"] as const,
  tokens: ["tokens"] as const,
  specs: (q: string) => ["specs", q] as const,
  reviewQueue: ["review-queue"] as const,
  inbox: ["inbox"] as const,
};

const ACTIVE = (jobs?: Job[]) => !!jobs?.some((j) => j.status === "pending" || j.status === "running");

/** Watch detail; polls while any of its jobs are queued or running. */
export function useWatch(id: string) {
  return useQuery({
    queryKey: keys.watch(id),
    queryFn: () => get<WatchDetail>(`/api/watches/${id}`),
    refetchInterval: (q) => (ACTIVE(q.state.data?.jobs) ? 1500 : false),
  });
}

/** A mutation that shows a toast on success / error and refreshes the given queries. */
export function useAction<TArgs = void, TResult = unknown>(
  fn: (args: TArgs) => Promise<TResult>,
  opts: { success?: string | ((r: TResult) => string | null); invalidate?: QueryKey[]; onSuccess?: (r: TResult) => void; onError?: (e: unknown) => void } = {},
) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      const msg = typeof opts.success === "function" ? opts.success(r) : opts.success;
      if (msg) toast("success", msg);
      (opts.invalidate ?? []).forEach((k) => qc.invalidateQueries({ queryKey: k }));
      qc.invalidateQueries({ queryKey: keys.dashboard });
      opts.onSuccess?.(r);
    },
    onError: (e) => {
      if (opts.onError) opts.onError(e);
      else toast("error", errorMessage(e));
    },
  });
}
