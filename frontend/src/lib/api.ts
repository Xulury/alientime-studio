// Thin client for the studio API. Cookie session + CSRF header for every write.

let csrfToken: string | null = null;

export function setCsrf(token: string | null) {
  csrfToken = token;
}

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
  get blockers(): string[] {
    const b = this.details?.blockers;
    return Array.isArray(b) ? (b as string[]) : [];
  }
}

type Query = Record<string, string | number | boolean | undefined | null | string[]>;

function buildUrl(path: string, query?: Query) {
  const url = new URL(path, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === "") continue;
      if (Array.isArray(v)) v.forEach((x) => url.searchParams.append(k, x));
      else url.searchParams.set(k, String(v));
    }
  }
  return url.pathname + url.search;
}

async function parseError(res: Response, path?: string): Promise<ApiError> {
  let code = "error";
  let message = `Request failed (${res.status}).`;
  let details: Record<string, unknown> = {};
  let rawText = "";
  try {
    rawText = await res.text();
    const body = JSON.parse(rawText);
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details ?? {};
    } else if (body?.detail) {
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      code = "fastapi_detail";
    } else if (body?.message) {
      message = body.message;
      code = body.code ?? "server_message";
    }
    if (body && typeof body === "object") {
      details = { ...details, ...body };
    }
  } catch {
    if (rawText && rawText.trim().length > 0) {
      const clean = rawText.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
      message = clean.slice(0, 300) || `Request failed (${res.status}).`;
      details = { raw: rawText.slice(0, 1000) };
    }
  }
  if (res.status === 401) window.dispatchEvent(new CustomEvent("studio:auth-expired"));
  if (res.status === 0) message = "The studio server did not respond. Check your connection.";

  const pathLabel = path ? ` on ${path}` : "";
  if (path && !message.includes(path)) {
    message = `${message} (${res.status}${pathLabel})`;
  }

  return new ApiError(res.status, code, message, details);
}

export async function api<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Query; signal?: AbortSignal } = {},
): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
      signal: opts.signal,
    });
  } catch {
    throw new ApiError(0, "network", `Cannot reach the studio server${path ? ` [${path}]` : ""}. Check that it is running.`);
  }
  if (!res.ok) throw await parseError(res, path);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const get = <T,>(path: string, query?: Query) => api<T>(path, { query });
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: body ?? {} });
export const put = <T,>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body: body ?? {} });
export const patch = <T,>(path: string, body?: unknown) => api<T>(path, { method: "PATCH", body: body ?? {} });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });

/** Upload files with progress (XMLHttpRequest exposes upload progress; fetch does not). */
export function uploadFiles<T = unknown>(
  path: string,
  files: File[] | Blob[],
  onProgress?: (pct: number) => void,
  field = "files",
  method = "POST",
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, path);
    xhr.withCredentials = true;
    if (csrfToken) xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let body: any = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else {
        if (xhr.status === 401) window.dispatchEvent(new CustomEvent("studio:auth-expired"));
        reject(new ApiError(xhr.status, body?.error?.code ?? "error", body?.error?.message ?? `Upload failed (${xhr.status}).`, body?.error?.details ?? {}));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "Upload failed: the studio server did not respond."));
    const form = new FormData();
    files.forEach((f, i) => form.append(field, f, (f as File).name ?? `file-${i}.png`));
    xhr.send(form);
  });
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong.";
}
