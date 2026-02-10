"use client";

import { cn } from "@/lib/utils";
import type { ChatMessage as ChatMessageType } from "@/lib/api";

function formatMarkdown(text: string): string {
  let html = text
    // Code blocks
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="my-2 rounded-md bg-background/50 p-3 font-mono text-xs overflow-x-auto"><code>$2</code></pre>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code class="rounded bg-background/50 px-1 py-0.5 font-mono text-xs">$1</code>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    // Italic
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    // Line breaks
    .replace(/\n/g, "<br />");
  return html;
}

export function ChatMessageBubble({
  message,
  isStreaming,
}: {
  message: ChatMessageType;
  isStreaming?: boolean;
}) {
  const isUser = message.role === "user";

  return (
    <div
      className={cn(
        "flex w-full animate-slide-up",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed sm:max-w-[75%]",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-secondary text-secondary-foreground"
        )}
      >
        {isUser ? (
          <p>{message.content}</p>
        ) : (
          <div
            className="prose-invert prose-sm [&_pre]:my-2 [&_code]:text-xs"
            dangerouslySetInnerHTML={{
              __html: formatMarkdown(message.content),
            }}
          />
        )}
        {isStreaming && (
          <span className="ml-1 inline-block h-3 w-1.5 animate-pulse-subtle rounded-full bg-current" />
        )}
      </div>
    </div>
  );
}
