export interface Message {
  role: "user" | "assistant";
  content: string;
}

export interface PendingAction {
  operation: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface ChatResponse {
  reply: string;
  session_id: string;
  thread_id: string;
  pending_action: PendingAction | null;
  error: string | null;
}

export interface Thread {
  id: string;
  title: string;
  created_at: string;
}

export interface ThreadMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ThreadMessagesResponse {
  thread_id: string;
  messages: ThreadMessage[];
}
