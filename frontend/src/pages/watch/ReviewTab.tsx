import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, Check, RefreshCw, ShieldCheck, Undo2, X } from "lucide-react";
import { del, get, post } from "../../lib/api";
import { keys, useAction } from "../../lib/hooks";
import { actorName, ago, dateTime } from "../../lib/format";
import type { WatchDetail } from "../../lib/types";
import { ApiError } from "../../lib/api";
import { Blockers, Button, Notice, Panel, PanelHeader, Pill, useConfirm, useToast } from "../../components/ui";

const needsPrivacyCheck = (blockers: string[]) => blockers.some((b) => /redaction|serial|privacy/i.test(b));

export default function ReviewTab({ detail }: { detail: WatchDetail }) {
  const w = detail.watch;
  const r = detail.readiness;
  const confirm = useConfirm();
  const toast = useToast();
  const inv = [keys.watch(w.id), keys.review(w.id), keys.copy(w.id), keys.approvals(w.id)];
  const showBlockers = (e: unknown) => {
    if (e instanceof ApiError && e.blockers.length) toast("error", <><b>{e.message}</b><ul className="list-disc pl-4 mt-1">{e.blockers.slice(0, 6).map((b, i) => <li key={i}>{b}</li>)}</ul></>);
    else toast("error", e instanceof Error ? e.message : "Failed");
  };
  const pkg = useAction(() => post("/api/watches/" + w.id + "/approvals", { scope: "package" }), { success: "Full package approved", invalidate: inv, onError: showBlockers });
  const channel = useAction((ch: string) => post("/api/watches/" + w.id + "/approvals", { scope: "channel", target: ch }), { success: "Channel approved", invalidate: inv, onError: showBlockers });
  const revoke = useAction((ch: string) => del(`/api/watches/${w.id}/approvals/channel/${ch}`), { success: "Approval withdrawn", invalidate: inv });
  const image = useAction((a: { id: string; decision: string }) => post(`/api/assets/${a.id}/review`, { decision: a.decision }), {
    success: (res: any) => (res.review_status === "approved" ? "Image approved" : res.review_status === "rejected" ? "Image rejected" : "New render requested"), invalidate: inv, onError: showBlockers,
  });
  const request = useAction(() => post<any>(`/api/watches/${w.id}/request-approval`), {
    success: (res) => (res.notified ? "Approval request sent to Telegram" : "Approval request recorded (Telegram is not configured)"),
  });
  const history = useQuery({ queryKey: keys.approvals(w.id), queryFn: () => get<{ items: any[] }>(`/api/watches/${w.id}/approvals`) });
  const included = r.channels.filter((c) => c.copy);
  const channelName: Record<string, string> = Object.fromEntries(r.channels.map((c) => [c.key, c.name]));

  return (
    <div className="space-y-6">
      <Panel className={r.package.approved ? "border-velvet-100 bg-velvet-50/40" : ""}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-[70ch]">
            <h2 className="font-display text-[26px] leading-tight">{r.package.approved ? "Package approved" : "Approve the listing package"}</h2>
            <p className="text-[13.5px] text-steel mt-1">
              {r.package.approved && r.package.approval
                ? <>Approved by {actorName(r.package.approval.approved_by)} on {dateTime(r.package.approval.approved_at)}. Any edit to facts, copy or images clears the affected approvals automatically.</>
                : <>Approving the package approves the {r.summary.images_total} final image{r.summary.images_total === 1 ? "" : "s"} and the copy for {included.length} channel{included.length === 1 ? "" : "s"}, exactly as they are now.</>}
            </p>
          </div>
          <div className="flex gap-2">
            {!r.package.approved && <Button variant="ghost" loading={request.isPending} onClick={() => request.mutate()}>Ask for approval</Button>}
            {!r.package.approved && (
              <Button variant="primary" icon={<BadgeCheck className="size-4" />} disabled={r.package.blockers.length > 0} loading={pkg.isPending}
                onClick={async () => {
                  if (await confirm({ title: "Approve everything?", confirm: "Approve package", body: <>
                    You are approving {r.summary.images_total} images and copy for: {included.map((c) => c.name).join(", ")}. The approval is tied to this exact content and is recorded with your name and the time.
                  </> })) pkg.mutate();
                }}>Approve package</Button>
            )}
          </div>
        </div>
        {!r.package.approved && r.package.blockers.length > 0 && <div className="mt-4"><Blockers items={r.package.blockers} /></div>}
      </Panel>

      <Panel>
        <PanelHeader title="Final images" sub="Each image is approved as rendered. Re-rendering or editing redactions clears its approval."
          actions={<Link to={`/watches/${w.id}/photos`} className="text-[13px] text-velvet hover:underline">Manage photos</Link>} />
        {r.images.length === 0 ? <Notice tone="info">No studio images yet. Upload and process photos first.</Notice> : (
          <ul className="grid sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-4">
            {r.images.map((img) => (
              <li key={img.asset_id} className="rounded-lg border border-line overflow-hidden flex flex-col">
                <Link to={`/watches/${w.id}/studio/${img.asset_id}`} className="block aspect-[2/3] bg-stage">
                  <img src={img.thumb} alt={img.filename} className="size-full object-contain" loading="lazy" />
                </Link>
                <div className="p-3 flex-1 flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] font-medium truncate">{img.filename}</span>
                    {img.approved ? <Pill tone="velvet" dot>Approved</Pill> : img.review_status === "rejected" ? <Pill tone="danger">Rejected</Pill> : <Pill tone="brass" dot>To review</Pill>}
                  </div>
                  {img.blockers.length > 0 && <ul className="text-[12.5px] text-brass space-y-0.5">{img.blockers.map((b, i) => <li key={i}>{b}</li>)}</ul>}
                  {img.approval && !img.approved && img.approval.invalidated_reason && <p className="text-[12px] text-steel">Approval cleared: {img.approval.invalidated_reason}</p>}
                  <div className="mt-auto flex flex-wrap gap-1.5">
                    {!img.approved && needsPrivacyCheck(img.blockers) && (
                      <Link to={`/watches/${w.id}/studio/${img.asset_id}?stage=privacy`}
                        className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-velvet text-white text-[13px] font-medium hover:bg-velvet-700">
                        <ShieldCheck className="size-3.5" />Check redactions
                      </Link>
                    )}
                    {!img.approved && !needsPrivacyCheck(img.blockers) && <Button size="sm" variant="primary" icon={<Check className="size-3.5" />}
                      disabled={img.blockers.length > 0} onClick={() => image.mutate({ id: img.asset_id, decision: "approve" })}>Approve</Button>}
                    <Button size="sm" icon={<RefreshCw className="size-3.5" />} onClick={() => image.mutate({ id: img.asset_id, decision: "regenerate" })}>Render again</Button>
                    <Button size="sm" variant="ghost" icon={<X className="size-3.5" />} onClick={() => image.mutate({ id: img.asset_id, decision: "reject" })}>Reject</Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel pad={false}>
        <div className="p-5 pb-0"><PanelHeader title="Channel copy" sub="Approve each channel, or approve the whole package above." /></div>
        <table className="w-full text-[13.5px]">
          <thead><tr className="text-left text-[12.5px] text-steel border-y border-line bg-paper/60">
            <th className="font-medium py-2 pl-5">Channel</th><th className="font-medium px-3">Copy</th><th className="font-medium px-3">Approval</th><th className="py-2 pr-5" />
          </tr></thead>
          <tbody className="divide-y divide-line">
            {r.channels.map((c) => (
              <tr key={c.key} className="align-top">
                <td className="py-3 pl-5"><Link className="font-medium hover:underline" to={`/watches/${w.id}/listing`}>{c.name}</Link><div className="text-[12px] text-steel">{c.route === "manual" ? "Draft pack" : c.route === "feed" ? "Dealer feed" : "API"}</div></td>
                <td className="py-3 px-3">
                  {!c.copy ? <span className="text-steel">Not written</span> : (
                    <>
                      <div className="truncate max-w-[42ch]">{c.copy.title || "—"}</div>
                      <div className="text-[12px] text-steel">v{c.copy.version} · {c.copy.chars} characters
                        {c.copy.errors.length > 0 && <span className="text-danger"> · {c.copy.errors.length} issue(s)</span>}
                        {c.copy.stale.length > 0 && <span className="text-danger"> · out of date</span>}</div>
                    </>
                  )}
                </td>
                <td className="py-3 px-3">
                  {c.approved && c.approval ? <span className="text-[12.5px]"><Pill tone="velvet" dot>Approved</Pill><span className="block text-steel mt-1">{actorName(c.approval.approved_by)} · {ago(c.approval.approved_at)}</span></span>
                    : c.approval?.invalidated_reason ? <span className="text-[12.5px] text-brass">Cleared: {c.approval.invalidated_reason}</span>
                    : <span className="text-[12.5px] text-steel">Not approved</span>}
                </td>
                <td className="py-3 pr-5 text-right whitespace-nowrap">
                  {c.copy && !c.approved && <Button size="sm" variant="primary" disabled={c.approval_blockers.length > 0}
                    title={c.approval_blockers.join("\n")} onClick={() => channel.mutate(c.key)}>Approve</Button>}
                  {c.approved && <Button size="sm" variant="ghost" icon={<Undo2 className="size-3.5" />} onClick={() => revoke.mutate(c.key)}>Withdraw approval</Button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel>
        <PanelHeader title="Approval record" sub="Who approved what, when — and why an approval was cleared." />
        {!history.data?.items.length ? <p className="text-[13px] text-steel">No approvals yet.</p> : (
          <ul className="divide-y divide-line text-[13px]">
            {history.data.items.slice(0, 40).map((a) => (
              <li key={a.id} className="py-2 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                <Pill tone={a.status === "active" ? "velvet" : a.status === "revoked" ? "muted" : "neutral"}>{a.status === "active" ? "Active" : a.status === "revoked" ? "Withdrawn" : "Cleared"}</Pill>
                <span className="font-medium">{a.scope === "package" ? "Full package" : a.scope === "channel" ? (channelName[a.target] ?? a.target) : `Image ${a.snapshot?.filename ?? ""}`}</span>
                <span className="text-steel">{a.content_ref} · {actorName(a.approved_by)} · {dateTime(a.approved_at)} · hash {a.hash}</span>
                {a.invalidated_reason && <span className="text-steel w-full sm:w-auto">— {a.invalidated_reason}</span>}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
