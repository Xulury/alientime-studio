import { useMemo } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus, Search, Watch } from "lucide-react";
import { get } from "../lib/api";
import { keys } from "../lib/hooks";
import { CUSTODY, ago, money } from "../lib/format";
import type { WatchSummary } from "../lib/types";
import { Button, Empty, Loading, Notice, PageHeader, Panel, Pill, Select, StatusPill, cx } from "../components/ui";

const STATUSES: Array<[string, string]> = [
  ["draft", "Draft"], ["processing", "Processing"], ["awaiting_review", "Awaiting review"], ["approved", "Approved"],
  ["published", "Published"], ["reserved", "Reserved"], ["sold", "Sold"], ["withdrawn", "Withdrawn"],
];

interface ListResp { items: WatchSummary[]; total: number; page: number; page_size: number; brands: string[] }

export default function Inventory() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const params = useMemo(() => ({
    q: sp.get("q") ?? "",
    status: sp.getAll("status"),
    availability: sp.get("availability") ?? "",
    brand: sp.get("brand") ?? "",
    custody: sp.get("custody") ?? "",
    consignment: sp.get("consignment") ?? "",
    archived: sp.get("archived") === "true",
    sort: sp.get("sort") ?? "updated",
    order: sp.get("order") ?? "desc",
    page: Number(sp.get("page") ?? 1),
  }), [sp]);
  const q = useQuery({
    queryKey: keys.watches(params),
    queryFn: () => get<ListResp>("/api/watches", { ...params, page_size: 50 }),
    placeholderData: keepPreviousData,
  });
  const set = (k: string, v: string | string[] | null) => {
    const next = new URLSearchParams(sp);
    next.delete(k);
    if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
    else if (v) next.set(k, v);
    if (k !== "page") next.delete("page");
    setSp(next, { replace: true });
  };
  const toggleStatus = (s: string) => {
    const cur = new Set(params.status);
    cur.has(s) ? cur.delete(s) : cur.add(s);
    set("status", [...cur]);
  };
  const data = q.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <>
      <PageHeader title="Inventory" sub="Every watch in the studio, with its listing status."
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => navigate("/watches/new")}>New watch</Button>} />
      <Panel className="mb-5">
        <div className="grid gap-3 md:grid-cols-[1fr_auto_auto_auto] items-end">
          <label className="relative block">
            <span className="sr-only">Search</span>
            <Search className="size-4 text-steel absolute left-3 top-1/2 -translate-y-1/2" />
            <input className="field pl-9" placeholder="Search SKU, brand, model, reference or consignor"
              defaultValue={params.q} onChange={(e) => set("q", e.target.value)} />
          </label>
          <Select aria-label="Availability" value={params.availability} onChange={(e) => set("availability", e.target.value)}
            options={[{ value: "", label: "Any availability" }, { value: "available", label: "Available" }, { value: "reserved", label: "Reserved" }, { value: "sold", label: "Sold" }, { value: "withdrawn", label: "Withdrawn" }]} />
          <Select aria-label="Brand" value={params.brand} onChange={(e) => set("brand", e.target.value)}
            options={[{ value: "", label: "All brands" }, ...(data?.brands ?? []).map((b) => ({ value: b, label: b }))]} />
          <Select aria-label="Sort" value={`${params.sort}:${params.order}`} onChange={(e) => {
            const [s, o] = e.target.value.split(":");
            const next = new URLSearchParams(sp);
            next.set("sort", s);
            next.set("order", o);
            setSp(next, { replace: true });
          }} options={[
            { value: "updated:desc", label: "Recently updated" }, { value: "created:desc", label: "Newest first" },
            { value: "price:desc", label: "Price, high to low" }, { value: "price:asc", label: "Price, low to high" },
            { value: "brand:asc", label: "Brand A–Z" }, { value: "sku:asc", label: "SKU" }, { value: "status:asc", label: "Status" },
          ]} />
        </div>
        <div className="flex flex-wrap items-center gap-2 mt-3">
          {STATUSES.map(([k, label]) => (
            <button key={k} onClick={() => toggleStatus(k)} aria-pressed={params.status.includes(k)}
              className={cx("h-7 px-2.5 rounded-full text-[12.5px] border transition-colors cursor-pointer",
                params.status.includes(k) ? "bg-ink text-white border-ink" : "bg-surface text-ink-2 border-line hover:border-line-strong")}>
              {label}
            </button>
          ))}
          <span className="mx-1 h-5 w-px bg-line" />
          <select className="h-7 rounded-full border border-line bg-surface px-2 text-[12.5px]" value={params.custody} onChange={(e) => set("custody", e.target.value)} aria-label="Custody">
            <option value="">Any custody</option><option value="in_hand">In hand</option><option value="consigned_offsite">Consigned off-site</option><option value="unknown">Custody not recorded</option>
          </select>
          <select className="h-7 rounded-full border border-line bg-surface px-2 text-[12.5px]" value={params.consignment} onChange={(e) => set("consignment", e.target.value)} aria-label="Consignment">
            <option value="">Owned &amp; consigned</option><option value="true">Consignment only</option><option value="false">Owned stock only</option>
          </select>
          <label className="ml-auto flex items-center gap-2 text-[12.5px] text-steel cursor-pointer">
            <input type="checkbox" checked={params.archived} onChange={(e) => set("archived", e.target.checked ? "true" : null)} /> Show archived
          </label>
        </div>
      </Panel>

      {q.isLoading ? <Loading /> : q.error ? <Notice tone="danger">The inventory could not be loaded.</Notice> : !data?.items.length ? (
        <Panel><Empty icon={<Watch className="size-8" />} title={data?.total === 0 && !sp.toString() ? "No watches yet" : "No watches match"}
          action={<Button variant="primary" onClick={() => navigate("/watches/new")}>Add a watch</Button>}>
          {sp.toString() ? "Try removing a filter." : "Add a watch and upload its photographs to begin."}
        </Empty></Panel>
      ) : (
        <Panel pad={false} className="overflow-hidden">
          <table className="w-full text-[13.5px] hidden md:table">
            <thead>
              <tr className="text-left text-[12.5px] text-steel border-b border-line bg-paper/60">
                <th className="font-medium py-2.5 pl-5 pr-3">Watch</th>
                <th className="font-medium px-3">Status</th>
                <th className="font-medium px-3 text-right">Price</th>
                <th className="font-medium px-3">Custody</th>
                <th className="font-medium px-3 text-right">Photos</th>
                <th className="font-medium px-3 pr-5 text-right">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.items.map((w) => (
                <tr key={w.id} className="hover:bg-paper/60 cursor-pointer" onClick={() => navigate(`/watches/${w.id}`)}>
                  <td className="py-2.5 pl-5 pr-3">
                    <Link to={`/watches/${w.id}`} className="flex items-center gap-3" onClick={(e) => e.stopPropagation()}>
                      <div className="size-12 rounded-md bg-wash border border-line overflow-hidden shrink-0 grid place-items-center">{w.thumb ? <img src={w.thumb} alt="" className="size-full object-cover" loading="lazy" /> : <Watch className="size-5 text-steel/60" aria-hidden />}</div>
                      <div className="min-w-0">
                        <div className="font-display text-[17px] leading-tight truncate">{w.brand} {w.model}</div>
                        <div className="text-[12.5px] text-steel tabular-nums">{w.sku}{w.reference ? ` · Ref. ${w.reference}` : ""}{w.year ? ` · ${w.year}` : ""}</div>
                      </div>
                    </Link>
                  </td>
                  <td className="px-3">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <StatusPill status={w.status} label={w.status_label} />
                      {w.is_consignment && <Pill tone="muted">Consignment</Pill>}
                      {w.open_manual_tasks > 0 && <Pill tone="brass">{w.open_manual_tasks} task{w.open_manual_tasks > 1 ? "s" : ""}</Pill>}
                    </div>
                  </td>
                  <td className="px-3 text-right tabular-nums whitespace-nowrap">{money(w.price_sgd)}</td>
                  <td className="px-3 text-steel">{CUSTODY[w.custody] ?? w.custody}</td>
                  <td className="px-3 text-right tabular-nums">{w.photo_count}</td>
                  <td className="px-3 pr-5 text-right text-steel whitespace-nowrap">{ago(w.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="md:hidden divide-y divide-line">
            {data.items.map((w) => (
              <li key={w.id}>
                <Link to={`/watches/${w.id}`} className="flex gap-3 p-4">
                  <div className="size-16 rounded-md bg-wash border border-line overflow-hidden shrink-0 grid place-items-center">{w.thumb ? <img src={w.thumb} alt="" className="size-full object-cover" loading="lazy" /> : <Watch className="size-5 text-steel/60" aria-hidden />}</div>
                  <div className="min-w-0">
                    <div className="font-display text-[18px] leading-tight">{w.brand} {w.model}</div>
                    <div className="text-[12.5px] text-steel tabular-nums mt-0.5">{w.sku} · {money(w.price_sgd)}</div>
                    <div className="mt-1.5"><StatusPill status={w.status} label={w.status_label} /></div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between px-5 py-3 border-t border-line text-[13px] text-steel">
            <span>{data.total} watch{data.total === 1 ? "" : "es"}</span>
            {pages > 1 && (
              <div className="flex items-center gap-2">
                <Button size="sm" disabled={params.page <= 1} onClick={() => set("page", String(params.page - 1))}>Previous</Button>
                <span className="tabular-nums">Page {params.page} of {pages}</span>
                <Button size="sm" disabled={params.page >= pages} onClick={() => set("page", String(params.page + 1))}>Next</Button>
              </div>
            )}
          </div>
        </Panel>
      )}
    </>
  );
}
