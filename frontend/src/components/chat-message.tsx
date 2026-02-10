"use client";

import { cn } from "@/lib/utils";
import type { ChatMessage as ChatMessageType } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose-invert prose-sm max-w-none [&_pre]:my-2 [&_pre]:rounded-md [&_pre]:bg-background/50 [&_pre]:p-3 [&_pre]:text-xs [&_pre]:overflow-x-auto [&_code]:rounded [&_code]:bg-background/50 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_code]:font-mono [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:my-0.5 [&_p]:my-1 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_a]:text-chart-1 [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:border-muted-foreground/30 [&_blockquote]:pl-3 [&_blockquote]:italic [&_blockquote]:text-muted-foreground [&_table]:w-full [&_th]:border [&_th]:border-border/50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_td]:border [&_td]:border-border/50 [&_td]:px-2 [&_td]:py-1 [&_hr]:my-2 [&_hr]:border-border/50">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}
        {isStreaming && (
          <span className="ml-1 inline-block h-4 w-1.5 animate-pulse rounded-full bg-chart-1" />
        )}
      </div>
    </div>
  );
}
