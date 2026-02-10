"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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
  deleteMini,
  fetchChatStream,
  type Mini,
  type ChatMessage,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Send, ChevronLeft, ChevronRight, Trash2, ArrowLeft, Github, MessageSquare, Sparkles, AlertCircle } from "lucide-react";

const STARTERS = [
  "What's your strongest engineering opinion?",
  "Tell me about a time you disagreed with a coworker's code",
  "What's your code review philosophy?",
  "What technology are you most passionate about?",
];

function parseSourcesUsed(sourcesUsed?: string): string[] {
  if (!sourcesUsed) return [];
  try {
    const parsed = JSON.parse(sourcesUsed);
    if (Array.isArray(parsed)) return parsed;
  } catch {
    return sourcesUsed.split(",").map((s) => s.trim()).filter(Boolean);
  }
  return [];
}

export default function MiniProfilePage() {
  const params = useParams();
  const router = useRouter();
  const username = params.username as string;
  const { user } = useAuth();

  const isOwner = user?.github_username === username;

  const [mini, setMini] = useState<Mini | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [spiritOpen, setSpiritOpen] = useState(false);
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

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteMini(username);
      router.push("/gallery");
    } catch {
      setDeleting(false);
      setDeleteOpen(false);
    }
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

  if (error || !mini || mini.status === "failed") {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center p-4">
        <div className="w-full max-w-md rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
            <AlertCircle className="h-6 w-6 text-destructive" />
          </div>
          <h2 className="mb-2 text-lg font-semibold">
            {mini?.status === "failed" ? "Mini Creation Failed" : "Mini Not Found"}
          </h2>
          <p className="mb-6 text-sm text-muted-foreground">
            {error || (mini?.status === "failed"
              ? `Something went wrong while creating @${username}'s mini. You can try creating it again.`
              : `We couldn't find a mini for @${username}.`)}
          </p>
          <div className="flex flex-col items-center gap-3">
            <Link href={`/create?username=${username}`}>
              <Button variant="default" className="gap-2">
                <Sparkles className="h-4 w-4" />
                Retry Creation
              </Button>
            </Link>
            <Link
              href="/gallery"
              className="text-sm text-muted-foreground underline transition-colors hover:text-foreground"
            >
              Back to Gallery
            </Link>
          </div>
        </div>
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

          {/* Owner badge */}
          {isOwner && (
            <div className="flex items-center justify-between rounded-lg border border-chart-1/30 bg-chart-1/5 px-3 py-2">
              <div className="flex items-center gap-2">
                <Sparkles className="h-3.5 w-3.5 text-chart-1" />
                <span className="text-xs font-medium text-chart-1">This is your mini</span>
              </div>
              <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
                <DialogTrigger asChild>
                  <button
                    className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    title="Delete mini"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Delete @{username}?</DialogTitle>
                    <DialogDescription>
                      This will permanently delete this mini and all associated data.
                      This action cannot be undone.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter>
                    <Button
                      variant="outline"
                      onClick={() => setDeleteOpen(false)}
                      disabled={deleting}
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="destructive"
                      onClick={handleDelete}
                      disabled={deleting}
                    >
                      {deleting ? "Deleting..." : "Delete"}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          )}

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

          {/* Source badges */}
          {parseSourcesUsed(mini.sources_used).length > 0 && (
            <div className="space-y-2">
              <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Sources
              </h2>
              <div className="flex flex-wrap gap-1.5">
                {parseSourcesUsed(mini.sources_used).map((source) => (
                  <Badge key={source} variant="outline" className="gap-1 text-xs">
                    {source === "github" ? (
                      <Github className="h-3 w-3" />
                    ) : source === "claude_code" ? (
                      <MessageSquare className="h-3 w-3" />
                    ) : null}
                    {source === "github" ? "GitHub" : source === "claude_code" ? "Claude Code" : source}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Enhance with Claude Code CTA */}
          {isOwner && !parseSourcesUsed(mini.sources_used).includes("claude_code") && (
            <Link
              href={`/create?username=${username}`}
              className="flex items-center gap-3 rounded-lg border border-dashed border-border/50 px-4 py-3 text-sm transition-colors hover:border-border hover:bg-secondary/30"
            >
              <MessageSquare className="h-4 w-4 text-muted-foreground" />
              <div>
                <p className="font-medium">Enhance with Claude Code</p>
                <p className="text-xs text-muted-foreground">
                  Add conversation data for richer personality
                </p>
              </div>
            </Link>
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

          {mini.spirit_content && (
            <div className="mt-4">
              <button
                type="button"
                onClick={() => setSpiritOpen(!spiritOpen)}
                className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <ChevronRight className={`h-4 w-4 transition-transform ${spiritOpen ? "rotate-90" : ""}`} />
                About this Mini
              </button>
              {spiritOpen && (
                <div className="mt-3 rounded-lg bg-secondary/30 p-4 text-sm text-muted-foreground whitespace-pre-wrap max-h-96 overflow-y-auto">
                  {mini.spirit_content}
                </div>
              )}
            </div>
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
            {isStreaming && messages.length > 0 && messages[messages.length - 1].role === "user" && (
              <div className="flex gap-3 px-4 py-3">
                <Avatar className="h-8 w-8 shrink-0">
                  <AvatarImage src={mini?.avatar_url} />
                  <AvatarFallback className="text-xs">{username.slice(0, 2).toUpperCase()}</AvatarFallback>
                </Avatar>
                <div className="flex items-center gap-1 text-sm text-muted-foreground">
                  <span className="animate-pulse">Thinking</span>
                  <span className="animate-bounce" style={{ animationDelay: "0ms" }}>.</span>
                  <span className="animate-bounce" style={{ animationDelay: "150ms" }}>.</span>
                  <span className="animate-bounce" style={{ animationDelay: "300ms" }}>.</span>
                </div>
              </div>
            )}
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
