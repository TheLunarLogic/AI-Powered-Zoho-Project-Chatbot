"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createThread, deleteThread, getThreadMessages, listThreads, sendMessage } from "@/lib/api";
import type { Message, PendingAction, Thread } from "@/lib/types";

function generateSessionId(): string {
  return crypto.randomUUID();
}

export default function ChatPage() {
  const [sessionId] = useState(() => generateSessionId());

  // Sidebar state
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [loadingThreads, setLoadingThreads] = useState(false);

  // Chat state
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Load thread list on mount
  useEffect(() => {
    setLoadingThreads(true);
    listThreads()
      .then(setThreads)
      .catch(() => {/* auth redirect handled inside api.ts */})
      .finally(() => setLoadingThreads(false));
  }, []);

  // Switch to a thread: load its history
  const selectThread = useCallback(async (threadId: string) => {
    setActiveThreadId(threadId);
    setError(null);
    setPendingAction(null);
    try {
      const data = await getThreadMessages(threadId);
      setMessages(
        data.messages.map((m) => ({ role: m.role as "user" | "assistant", content: m.content }))
      );
    } catch {
      setError("Failed to load thread history.");
      setMessages([]);
    }
  }, []);

  // Create a new thread and switch to it (empty, no messages yet)
  async function handleDeleteThread(threadId: string, e: React.MouseEvent) {
    e.stopPropagation(); // don't also select the thread
    if (!window.confirm("Delete this chat? This cannot be undone.")) return;
    try {
      await deleteThread(threadId);
      setThreads((prev) => prev.filter((t) => t.id !== threadId));
      if (activeThreadId === threadId) {
        setActiveThreadId(null);
        setMessages([]);
        setPendingAction(null);
        setError(null);
      }
    } catch {
      setError("Failed to delete chat.");
    }
  }

  async function handleNewThread() {
    try {
      const thread = await createThread("New Chat");
      setThreads((prev) => [thread, ...prev]);
      setActiveThreadId(thread.id);
      setMessages([]);
      setPendingAction(null);
      setError(null);
    } catch {
      setError("Failed to create thread.");
    }
  }

  async function handleSend(messageText?: string) {
    const text = messageText ?? input.trim();
    if (!text || loading) return;

    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setLoading(true);

    try {
      const response = await sendMessage(text, sessionId, activeThreadId ?? undefined);

      // If backend created a new thread (no activeThreadId), persist it in sidebar
      if (response.thread_id && response.thread_id !== activeThreadId) {
        setActiveThreadId(response.thread_id);
        // Refresh thread list so the new thread appears in the sidebar
        listThreads().then(setThreads).catch(() => {});
      }

      setMessages((prev) => [...prev, { role: "assistant", content: response.reply }]);
      setPendingAction(response.pending_action);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm() {
    setLoading(true);
    setError(null);
    try {
      const response = await sendMessage("confirm", sessionId, activeThreadId ?? undefined, "confirm");
      setMessages((prev) => [...prev, { role: "assistant", content: response.reply }]);
      setPendingAction(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function handleCancel() {
    setLoading(true);
    setError(null);
    try {
      const response = await sendMessage("cancel", sessionId, activeThreadId ?? undefined, "cancel");
      setMessages((prev) => [...prev, { role: "assistant", content: response.reply }]);
      setPendingAction(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", height: "100vh", fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>

      {/* ── Sidebar ── */}
      <div style={{
        width: "240px",
        minWidth: "240px",
        background: "#1a1a2e",
        color: "#e0e0e0",
        display: "flex",
        flexDirection: "column",
        borderRight: "1px solid #2a2a4a",
      }}>
        {/* Sidebar header */}
        <div style={{ padding: "16px", borderBottom: "1px solid #2a2a4a" }}>
          <div style={{ fontWeight: 700, fontSize: "15px", color: "#fff", marginBottom: "12px" }}>
            💬 Chats
          </div>
          <button
            onClick={handleNewThread}
            style={{
              width: "100%",
              background: "#0070f3",
              color: "#fff",
              border: "none",
              borderRadius: "6px",
              padding: "8px 12px",
              fontSize: "13px",
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            + New Chat
          </button>
        </div>

        {/* Thread list */}
        <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
          {loadingThreads && (
            <p style={{ padding: "12px 16px", fontSize: "12px", color: "#888" }}>Loading…</p>
          )}
          {!loadingThreads && threads.length === 0 && (
            <p style={{ padding: "12px 16px", fontSize: "12px", color: "#888" }}>
              No chats yet. Click &quot;+ New Chat&quot;.
            </p>
          )}
          {threads.map((t) => (
            <div
              key={t.id}
              style={{
                display: "flex",
                alignItems: "center",
                background: activeThreadId === t.id ? "#2a2a5e" : "transparent",
                borderLeft: activeThreadId === t.id ? "3px solid #0070f3" : "3px solid transparent",
              }}
            >
              <button
                onClick={() => selectThread(t.id)}
                style={{
                  flex: 1,
                  background: "transparent",
                  color: activeThreadId === t.id ? "#fff" : "#ccc",
                  border: "none",
                  textAlign: "left",
                  padding: "10px 12px",
                  fontSize: "13px",
                  cursor: "pointer",
                  overflow: "hidden",
                  whiteSpace: "nowrap",
                  textOverflow: "ellipsis",
                  minWidth: 0,
                }}
                title={t.title}
              >
                {t.title}
              </button>
              <button
                onClick={(e) => handleDeleteThread(t.id, e)}
                title="Delete chat"
                style={{
                  flexShrink: 0,
                  background: "transparent",
                  border: "none",
                  color: "#888",
                  cursor: "pointer",
                  padding: "6px 10px",
                  fontSize: "14px",
                  lineHeight: 1,
                  borderRadius: "4px",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "#ff5555")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "#888")}
              >
                🗑
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* ── Main chat area ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Header */}
        <div style={{ padding: "14px 20px", background: "#fff", borderBottom: "1px solid #e0e0e0" }}>
          <h2 style={{ fontSize: "17px", fontWeight: 600 }}>
            {activeThreadId
              ? (threads.find((t) => t.id === activeThreadId)?.title ?? "Zoho Project Assistant")
              : "Zoho Project Assistant"}
          </h2>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", gap: "12px", background: "#f5f5f5" }}>
          {messages.length === 0 && (
            <p style={{ color: "#888", textAlign: "center", marginTop: "40px", fontSize: "14px" }}>
              {activeThreadId
                ? "No messages in this thread yet."
                : "Select a chat or start a new one. Try: \"What projects do I have?\""}
            </p>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              style={{
                alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                background: msg.role === "user" ? "#0070f3" : "#fff",
                color: msg.role === "user" ? "#fff" : "#1a1a1a",
                padding: "10px 14px",
                borderRadius: "12px",
                maxWidth: "72%",
                whiteSpace: "pre-wrap",
                border: msg.role === "assistant" ? "1px solid #e0e0e0" : "none",
                fontSize: "14px",
                lineHeight: "1.5",
              }}
            >
              {msg.content}
            </div>
          ))}

          {/* HIL Confirmation */}
          {pendingAction && (
            <div style={{
              background: "#fff8e1",
              border: "1px solid #ffc107",
              borderRadius: "10px",
              padding: "16px",
              maxWidth: "72%",
            }}>
              <p style={{ fontWeight: 600, marginBottom: "8px" }}>⚠️ Confirm Action</p>
              <p style={{ fontSize: "14px", marginBottom: "12px" }}>{pendingAction.description}</p>
              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  onClick={handleConfirm}
                  disabled={loading}
                  style={{ background: "#2e7d32", color: "white", padding: "8px 20px", border: "none", borderRadius: "6px", fontSize: "14px" }}
                >
                  Confirm
                </button>
                <button
                  onClick={handleCancel}
                  disabled={loading}
                  style={{ background: "#c62828", color: "white", padding: "8px 20px", border: "none", borderRadius: "6px", fontSize: "14px" }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {loading && (
            <div style={{ alignSelf: "flex-start", color: "#888", fontSize: "13px", padding: "8px 0" }}>
              Thinking…
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Error bar */}
        {error && (
          <div style={{ background: "#ffebee", color: "#c62828", padding: "10px 20px", fontSize: "13px" }}>
            {error}
          </div>
        )}

        {/* Input */}
        <div style={{ padding: "14px 20px", background: "#fff", borderTop: "1px solid #e0e0e0", display: "flex", gap: "10px" }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
            placeholder="Ask about your projects or tasks…"
            disabled={loading || !!pendingAction}
            style={{
              flex: 1,
              padding: "10px 14px",
              border: "1px solid #ccc",
              borderRadius: "8px",
              fontSize: "14px",
              outline: "none",
            }}
          />
          <button
            onClick={() => handleSend()}
            disabled={loading || !input.trim() || !!pendingAction}
            style={{
              background: "#0070f3",
              color: "white",
              padding: "10px 20px",
              border: "none",
              borderRadius: "8px",
              fontSize: "14px",
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
