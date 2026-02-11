"use client";

import { useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import type { ChatMessage as ChatMessageType } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Check, Copy, ChevronRight, Search, Brain, BookOpen } from "lucide-react";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className="absolute right-2 top-2 rounded-md border border-border/50 bg-background/80 p-1.5 text-muted-foreground opacity-0 backdrop-blur-sm transition-all hover:bg-background hover:text-foreground group-hover:opacity-100"
      title={copied ? "Copied!" : "Copy code"}
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-green-400" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

const TOOL_ICONS: Record<string, React.ReactNode> = {
  search_memories: <Search className="h-3 w-3" />,
  search_evidence: <BookOpen className="h-3 w-3" />,
  think: <Brain className="h-3 w-3" />,
};

const TOOL_LABELS: Record<string, string> = {
  search_memories: "Searched memories",
  search_evidence: "Searched evidence",
  think: "Reasoned",
};

function ThinkingSection({
  toolCalls,
}: {
  toolCalls: Array<{ tool: string; args: Record<string, string>; result?: string }>;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-2 border-t border-border/30 pt-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-[11px] text-muted-foreground/70 hover:text-muted-foreground transition-colors"
      >
        <ChevronRight
          className={cn("h-3 w-3 transition-transform", open && "rotate-90")}
        />
        <Brain className="h-3 w-3" />
        <span>
          {toolCalls.length} tool call{toolCalls.length !== 1 ? "s" : ""}
        </span>
      </button>
      {open && (
        <div className="mt-1.5 space-y-1">
          {toolCalls.map((tc, i) => (
            <div
              key={i}
              className="flex items-start gap-1.5 text-[11px] text-muted-foreground/60"
            >
              <span className="mt-0.5">
                {TOOL_ICONS[tc.tool] || <Brain className="h-3 w-3" />}
              </span>
              <div>
                <span className="font-medium">
                  {TOOL_LABELS[tc.tool] || tc.tool}
                </span>
                {tc.tool !== "think" && tc.args?.query && (
                  <span className="ml-1 text-muted-foreground/40">
                    &quot;{tc.args.query}&quot;
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ChatMessageBubble({
  message,
  isStreaming,
  toolActivity,
}: {
  message: ChatMessageType;
  isStreaming?: boolean;
  toolActivity?: string | null;
}) {
  const isUser = message.role === "user";

  return (
    <div
      className={cn(
        "flex w-full animate-slide-up",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div className="flex max-w-[85%] flex-col sm:max-w-[75%]">
        <div
          className={cn(
            "rounded-2xl px-4 py-2.5 leading-relaxed",
            isUser
              ? "bg-primary text-primary-foreground text-sm"
              : "bg-secondary text-secondary-foreground text-base"
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <>
              {/* Tool activity indicator during streaming */}
              {toolActivity && !message.content && (
                <div className="flex items-center gap-2 py-1 text-sm text-muted-foreground">
                  <div className="flex gap-0.5">
                    <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40" style={{ animationDelay: "0ms" }} />
                    <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40" style={{ animationDelay: "150ms" }} />
                    <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground/40" style={{ animationDelay: "300ms" }} />
                  </div>
                  <span>{toolActivity}</span>
                </div>
              )}
              {message.content ? (
                <div className="prose prose-invert max-w-none [&_p]:my-1.5 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:my-0.5 [&_a]:text-chart-1 [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:border-muted-foreground/30 [&_blockquote]:pl-3 [&_blockquote]:italic [&_blockquote]:text-muted-foreground [&_table]:w-full [&_th]:border [&_th]:border-border/50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_td]:border [&_td]:border-border/50 [&_td]:px-2 [&_td]:py-1 [&_hr]:my-2 [&_hr]:border-border/50">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      code({ className, children, ...props }) {
                        const match = /language-(\w+)/.exec(className || "");
                        const codeString = String(children).replace(/\n$/, "");

                        if (match) {
                          return (
                            <div className="group relative my-3 first:mt-0 last:mb-0">
                              <div className="flex items-center justify-between rounded-t-md border-b border-border/30 bg-[#1e1e1e] px-3 py-1.5">
                                <span className="text-[11px] font-mono text-muted-foreground/70 uppercase tracking-wider">
                                  {match[1]}
                                </span>
                              </div>
                              <CopyButton text={codeString} />
                              <SyntaxHighlighter
                                style={oneDark}
                                language={match[1]}
                                PreTag="div"
                                customStyle={{
                                  margin: 0,
                                  borderTopLeftRadius: 0,
                                  borderTopRightRadius: 0,
                                  borderBottomLeftRadius: "0.375rem",
                                  borderBottomRightRadius: "0.375rem",
                                  fontSize: "0.8125rem",
                                  lineHeight: "1.5",
                                }}
                              >
                                {codeString}
                              </SyntaxHighlighter>
                            </div>
                          );
                        }

                        return (
                          <code
                            className="rounded bg-background/50 px-1.5 py-0.5 text-[0.8125rem] font-mono"
                            {...props}
                          >
                            {children}
                          </code>
                        );
                      },
                      pre({ children }) {
                        return <>{children}</>;
                      },
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                </div>
              ) : !toolActivity && !isStreaming ? null : null}
              {/* Completed tool calls — collapsible */}
              {!isStreaming &&
                message.toolCalls &&
                message.toolCalls.length > 0 && (
                  <ThinkingSection toolCalls={message.toolCalls} />
                )}
            </>
          )}
          {isStreaming && (
            <span className="ml-1 inline-block h-4 w-1.5 animate-pulse rounded-full bg-chart-1" />
          )}
        </div>
      </div>
    </div>
  );
}
