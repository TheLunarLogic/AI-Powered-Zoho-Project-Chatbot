import { getLoginUrl } from "@/lib/api";

export default function LoginPage() {
  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      minHeight: "100vh",
      gap: "24px",
    }}>
      <h1 style={{ fontSize: "28px", fontWeight: 600 }}>Zoho Project Chatbot</h1>
      <p style={{ color: "#666", fontSize: "16px" }}>
        Sign in with your Zoho account to get started.
      </p>
      <a
        href={getLoginUrl()}
        style={{
          background: "#e84c3d",
          color: "white",
          padding: "12px 28px",
          borderRadius: "6px",
          textDecoration: "none",
          fontSize: "15px",
          fontWeight: 500,
        }}
      >
        Sign in with Zoho
      </a>
    </div>
  );
}
