import type { ChatResponse, Thread, ThreadMessagesResponse } from "./types";

const API = "";  // Next.js rewrites handle routing

// ── Chat ─────────────────────────────────────────────────────────────────────

export async function sendMessage(
  message: string,
  sessionId: string,
  threadId?: string,
  hilResponse?: "confirm" | "cancel"
): Promise<ChatResponse> {
  const body: Record<string, unknown> = { message, session_id: sessionId };
  if (threadId) body.thread_id = threadId;
  if (hilResponse) body.hil_response = hilResponse;

  const res = await fetch(`${API}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });

  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("Not authenticated");
  }
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

// ── Threads ───────────────────────────────────────────────────────────────────

export async function createThread(title?: string): Promise<Thread> {
  const res = await fetch(`${API}/api/threads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ title: title ?? "New Chat" }),
  });
  if (res.status === 401) { window.location.href = "/login"; throw new Error("Not authenticated"); }
  if (!res.ok) throw new Error(`Create thread failed: ${res.status}`);
  return res.json();
}

export async function listThreads(): Promise<Thread[]> {
  const res = await fetch(`${API}/api/threads`, {
    credentials: "include",
  });
  if (res.status === 401) { window.location.href = "/login"; throw new Error("Not authenticated"); }
  if (!res.ok) throw new Error(`List threads failed: ${res.status}`);
  return res.json();
}

export async function getThreadMessages(threadId: string): Promise<ThreadMessagesResponse> {
  const res = await fetch(`${API}/api/threads/${threadId}/messages`, {
    credentials: "include",
  });
  if (res.status === 401) { window.location.href = "/login"; throw new Error("Not authenticated"); }
  if (!res.ok) throw new Error(`Get messages failed: ${res.status}`);
  return res.json();
}

export async function deleteThread(threadId: string): Promise<void> {
  const res = await fetch(`${API}/api/threads/${threadId}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (res.status === 401) { window.location.href = "/login"; throw new Error("Not authenticated"); }
  if (!res.ok) throw new Error(`Delete thread failed: ${res.status}`);
}

export function getLoginUrl(): string {
  return "/auth/login";
}
