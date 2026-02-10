"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ChatMessageBubble } from "@/components/chat-message";
import {
  PersonalityRadar,
  PersonalityBars,
} from "@/components/personality-radar";
import {
  getMini,
  fetchChatStream,
  type Mini,
  type ChatMessage,
} from "@/lib/api";
import { Send, ChevronLeft, Trash2, ArrowLeft } from "lucide-react";

const STARTERS = [
  "What's your strongest engineering opinion?",
  "Tell me about a time you disagreed with a coworker's code",
  "What's your code review philosophy?",
  "What technology are you most passionate about?",
];

export default function MiniProfilePage() {
  const params = useParams();
  const username = params.username as string;

  const [mini, setMini] = useState<Mini | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    getMini(username)
      .then(setMini)
      .catch(() => setError("Could not load this mini."))
      .finally(() => setLoading(false));
  }, [username]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || isStreaming) return;

      const userMsg: ChatMessage = { role: "user", content: text };
      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setIsStreaming(true);

      const history = [...messages, userMsg];

      try {
        const res = await fetchChatStream(username, text, history);
        if (!res.ok) throw new Error("Chat request failed");
        if (!res.body) throw new Error("No response body");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let assistantContent = "";

        // Add empty assistant message
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "" },
        ]);

        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Parse SSE events from buffer
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const data = line.slice(6);
              if (data === "[DONE]") continue;
              try {
                const parsed = JSON.parse(data);
                const token =
                  parsed.token || parsed.content || parsed.delta || "";
                assistantContent += token;
                setMessages((prev) => {
                  const updated = [...prev];
                  updated[updated.length - 1] = {
                    role: "assistant",
                    content: assistantContent,
                  };
                  return updated;
                });
              } catch {
                // If not JSON, treat as raw token
                assistantContent += data;
                setMessages((prev) => {
                  const updated = [...prev];
                  updated[updated.length - 1] = {
                    role: "assistant",
                    content: assistantContent,
                  };
                  return updated;
                });
              }
            }
          }
        }
      } catch {
        setMessages((prev) => [
          ...prev.filter((m) => m.content !== ""),
          {
            role: "assistant",
            content:
              "Sorry, I couldn't respond right now. Please try again.",
          },
        ]);
      } finally {
        setIsStreaming(false);
        textareaRef.current?.focus();
      }
    },
    [username, messages, isStreaming]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const clearConversation = () => {
    setMessages([]);
    setInput("");
    textareaRef.current?.focus();
  };

  if (loading) {
    return (
      <div className="mx-auto flex max-w-6xl flex-col gap-6 p-4 lg:flex-row">
        <div className="w-full space-y-4 lg:w-80">
          <div className="flex items-start gap-4">
            <Skeleton className="h-16 w-16 shrink-0 rounded-full" />
            <div className="space-y-2">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-4 w-20" />
            </div>
          </div>
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-3/4" />
          <Separator />
          <Skeleton className="h-[180px] w-full rounded-lg" />
        </div>
        <div className="flex-1">
          <Skeleton className="h-[60vh] w-full rounded-xl" />
        </div>
      </div>
    );
  }

  if (error || !mini) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <p className="text-muted-foreground">{error || "Mini not found."}</p>
        <Link
          href="/gallery"
          className="text-sm text-chart-1 underline hover:text-chart-1/80"
        >
          Back to gallery
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-3.5rem)] max-w-6xl flex-col lg:flex-row">
      {/* Mobile sidebar toggle */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="flex items-center gap-2 border-b px-4 py-3 text-sm text-muted-foreground lg:hidden"
      >
        <ChevronLeft
          className={`h-4 w-4 transition-transform ${sidebarOpen ? "rotate-90" : "-rotate-90"}`}
        />
        {sidebarOpen ? "Hide profile" : "Show profile"}
      </button>

      {/* Sidebar */}
      <aside
        className={`${
          sidebarOpen ? "block" : "hidden"
        } w-full shrink-0 overflow-y-auto border-b p-6 lg:block lg:w-80 lg:border-b-0 lg:border-r`}
      >
        <div className="space-y-6">
          {/* Back to gallery */}
          <Link
            href="/gallery"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-3 w-3" />
            Back to gallery
          </Link>

          {/* Identity */}
          <div className="flex items-start gap-4">
            <Avatar className="h-16 w-16 shrink-0">
              <AvatarImage src={mini.avatar_url} alt={mini.username} />
              <AvatarFallback className="font-mono text-lg">
                {mini.username.slice(0, 2).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <h1 className="truncate text-lg font-semibold">
                {mini.display_name || mini.username}
              </h1>
              <p className="font-mono text-sm text-muted-foreground">
                @{mini.username}
              </p>
            </div>
          </div>

          {/* Bio */}
          {mini.bio && (
            <p className="text-sm leading-relaxed text-muted-foreground">
              {mini.bio}
            </p>
          )}

          <Separator />

          {/* Personality */}
          {mini.values && mini.values.length > 0 && (
            <>
              <div>
                <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Personality
                </h2>
                {mini.values.length >= 3 ? (
                  <PersonalityRadar values={mini.values} />
                ) : (
                  <PersonalityBars values={mini.values} />
                )}
              </div>

              <div>
                <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Traits
                </h2>
                <div className="flex flex-wrap gap-1.5">
                  {mini.values.map((v) => (
                    <Badge
                      key={v.name}
                      variant="outline"
                      className="text-xs"
                      title={v.description}
                    >
                      {v.name}
                    </Badge>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </aside>

      {/* Chat area */}
      <div className="flex flex-1 flex-col">
        {/* Chat header */}
        {messages.length > 0 && (
          <div className="flex items-center justify-between border-b px-4 py-2">
            <span className="text-xs text-muted-foreground">
              {messages.length} message{messages.length !== 1 && "s"}
            </span>
            <button
              onClick={clearConversation}
              disabled={isStreaming}
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50"
            >
              <Trash2 className="h-3 w-3" />
              Clear
            </button>
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4">
          <div className="mx-auto max-w-2xl space-y-4">
            {messages.length === 0 && (
              <div className="flex min-h-[50vh] flex-col items-center justify-center space-y-6">
                <div className="text-center">
                  <Avatar className="mx-auto mb-3 h-12 w-12">
                    <AvatarImage
                      src={mini.avatar_url}
                      alt={mini.username}
                    />
                    <AvatarFallback className="font-mono text-sm">
                      {mini.username.slice(0, 2).toUpperCase()}
                    </AvatarFallback>
                  </Avatar>
                  <p className="text-sm text-muted-foreground">
                    Start a conversation with{" "}
                    <span className="font-mono font-medium text-foreground">
                      {mini.display_name || mini.username}
                    </span>
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground/60">
                    Ask about their coding philosophy, opinions, and experiences
                  </p>
                </div>
                <div className="grid w-full max-w-sm gap-2">
                  {STARTERS.map((s) => (
                    <button
                      key={s}
                      onClick={() => sendMessage(s)}
                      className="rounded-lg border border-border/50 px-4 py-2.5 text-left text-sm text-muted-foreground transition-colors hover:border-border hover:bg-secondary hover:text-foreground"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <ChatMessageBubble
                key={i}
                message={msg}
                isStreaming={
                  isStreaming &&
                  i === messages.length - 1 &&
                  msg.role === "assistant"
                }
              />
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input */}
        <div className="border-t p-4">
          <div className="mx-auto flex max-w-2xl items-end gap-2">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Message @${mini.username}... (Shift+Enter for newline)`}
              className="min-h-[44px] max-h-32 resize-none font-mono text-sm"
              rows={1}
              disabled={isStreaming}
            />
            <Button
              size="icon"
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || isStreaming}
              className="h-[44px] w-[44px] shrink-0"
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
