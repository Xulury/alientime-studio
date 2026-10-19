import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { post, errorMessage } from "../lib/api";
import type { WatchRecord } from "../lib/types";
import { Dropzone, PendingList, useUploader } from "../components/Dropzone";
import { toBody, toForm, WatchForm } from "../components/WatchForm";
import { Button, Notice, PageHeader, Panel, PanelHeader } from "../components/ui";

export default function NewWatch() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [form, setForm] = useState(toForm());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const up = useUploader();

  const submit = async () => {
    setError(null);
    if (!form.brand.trim() || !form.model.trim()) return setError("Brand and model are required.");
    setBusy(true);
    try {
      const w = await post<WatchRecord>("/api/watches", toBody(form));
      if (up.readyCount) await up.uploadAll(w.id);
      qc.invalidateQueries({ queryKey: ["watches"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      navigate(`/watches/${w.id}/photos`);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader eyebrow="Inventory" title="New watch" sub="Enter what you know now; anything missing can be added later. Photos start processing as soon as they are uploaded." />
      <div className="grid xl:grid-cols-[1fr_420px] gap-6 items-start">
        <Panel className="order-2 xl:order-1">
          <WatchForm value={form} onChange={setForm} mode="create" />
        </Panel>
        <div className="order-1 xl:order-2 space-y-4 xl:sticky xl:top-8">
          <Panel>
            <PanelHeader title="Photographs" sub="Originals are kept untouched and private." />
            <Dropzone onFiles={up.add} compact />
            <PendingList files={up.files} onRemove={up.remove} />
          </Panel>
          {error && <Notice tone="danger">{error}</Notice>}
          <div className="flex gap-2">
            <Button variant="primary" size="lg" className="flex-1" loading={busy} onClick={submit}>
              {up.readyCount ? `Create watch and upload ${up.readyCount} photo${up.readyCount > 1 ? "s" : ""}` : "Create watch"}
            </Button>
            <Button size="lg" onClick={() => navigate(-1)} disabled={busy}>Cancel</Button>
          </div>
        </div>
      </div>
    </>
  );
}
