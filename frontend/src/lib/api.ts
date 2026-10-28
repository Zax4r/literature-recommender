import type { ChatMessage } from "./types";

const API = "/api/v1";

let token: string | null = localStorage.getItem("token");
let onUnauthorized: () => void = () => {};

export const hasToken = () => token !== null;
export function setToken(value: string | null) {
  token = value;
  if (value) localStorage.setItem("token", value);
  else localStorage.removeItem("token");
}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

interface Options {
  method?: string;
  json?: unknown;
  form?: Record<string, string>;
  body?: FormData;
}

function headers(extra: Record<string, string> = {}) {
  return token ? { Authorization: `Bearer ${token}`, ...extra } : extra;
}

async function fail(res: Response): Promise<never> {
  if (res.status === 401 && token) {
    setToken(null);
    onUnauthorized();
  }
  const err = await res.json().catch(() => ({}));
  const detail = Array.isArray(err.detail)
    ? err.detail.map((d: { msg: string }) => d.msg).join("; ")
    : err.detail;
  throw new Error(detail || res.statusText);
}

export async function api<T = unknown>(path: string, o: Options = {}): Promise<T> {
  let body: BodyInit | undefined = o.body;
  const extra: Record<string, string> = {};
  if (o.form) body = new URLSearchParams(o.form);
  else if (o.json !== undefined) {
    extra["Content-Type"] = "application/json";
    body = JSON.stringify(o.json);
  }
  const res = await fetch(API + path, { method: o.method ?? "GET", headers: headers(extra), body });
  if (!res.ok) return fail(res);
  return (res.status === 204 ? null : await res.json()) as T;
}

export interface ChatHandlers {
  onUser(m: ChatMessage): void;
  onMessage(m: ChatMessage): void;
}

/** POSTs a chat message and dispatches the server-sent events as they arrive. */
export async function sendChatMessage(
  sessionId: number,
  text: string,
  file: File | null,
  h: ChatHandlers,
) {
  const body = new FormData();
  if (text) body.append("message", text);
  if (file) body.append("file", file);
  const res = await fetch(`${API}/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: headers(),
    body,
  });
  if (!res.ok) return fail(res);

  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? "null");
      if (event === "user") h.onUser(data);
      else if (event === "message") h.onMessage(data);
      else if (event === "error") throw new Error(data);
    }
  }
}
