"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
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
import { PersonalityRadar } from "@/components/personality-radar";
import {
  getMiniByUsername,
  deleteMini,
  fetchChatStream,
  type Mini,
  type ChatMessage,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Send, ChevronLeft, ChevronRight, Trash2, ArrowLeft, Github, MessageSquare, Sparkles, AlertCircle, Lock, LogIn } from "lucide-react";

const STARTERS = [
  "What's your strongest engineering opinion?",
  "Tell me about a time you disagreed with a coworker's code",
  "What's your code review philosophy?",
  "What technology are you most passionate about?",
];

function parseSourcesUsed(sourcesUsed?: string | string[]): string[] {
  if (!sourcesUsed) return [];
  if (Array.isArray(sourcesUsed)) return sourcesUsed;
  try {
    const parsed = JSON.parse(sourcesUsed);
    if (Array.isArray(parsed)) return parsed;
  } catch {
    return sourcesUsed.split(",").map((s) => s.trim()).filter(Boolean);
  }
  return [];
}

/** Reusable collapsible sidebar section with chevron trigger */
function SidebarSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 py-1 text-xs font-medium uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground">
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 ${open ? "rotate-90" : ""}`}
        />
        {title}
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden data-[state=open]:animate-collapsible-down data-[state=closed]:animate-collapsible-up">
        <div className="pt-3">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export default function MiniProfilePage() {
  const params = useParams();
  const router = useRouter();
  const username = params.username as string;
  const { user, login } = useAuth();

  const [mini, setMini] = useState<Mini | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [pendingToolCalls, setPendingToolCalls] = useState<Array<{ tool: string; args: Record<string, string>; result?: string }>>([]);
  const pendingToolCallsRef = useRef<Array<{ tool: string; args: Record<string, string>; result?: string }>>([]);
  const [toolActivity, setToolActivity] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isOwner = user?.id != null && user.id === mini?.owner_id;

  useEffect(() => {
    getMiniByUsername(username)
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

      const history = [...messages];

      try {
        const res = await fetchChatStream(
          mini!.id,
          text,
          history,
        );
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

          // Normalize \r\n to \n (sse_starlette uses \r\n line endings)
          buffer = buffer.replace(/\r\n/g, "\n");

          // SSE spec: events are separated by \n\n (blank line)
          const events = buffer.split("\n\n");
          buffer = events.pop() || ""; // Last element may be incomplete

          for (const eventStr of events) {
            if (!eventStr.trim()) continue;

            let eventType = "";
            const dataLines: string[] = [];

            for (const rawLine of eventStr.split("\n")) {
              const line = rawLine.replace(/\r$/, "");
              if (line.startsWith("event:")) {
                eventType = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                const val = line.slice(5);
                dataLines.push(val.startsWith(" ") ? val.slice(1) : val);
              }
            }

            const data = dataLines.join("\n");

            if (eventType === "done" || data === "[DONE]") {
              break;
            }

            if (eventType === "tool_call") {
              try {
                const toolData = JSON.parse(data);
                const tc = { tool: toolData.tool, args: toolData.args || {} };
                pendingToolCallsRef.current = [...pendingToolCallsRef.current, tc];
                setPendingToolCalls([...pendingToolCallsRef.current]);

                // Set tool activity label directly
                const labels: Record<string, string> = {
                  search_memories: "Searching memories...",
                  search_evidence: "Searching evidence...",
                  think: "Thinking...",
                };
                setToolActivity(labels[tc.tool] || `Using ${tc.tool}...`);
              } catch { /* ignore parse errors */ }
              continue;
            }

            if (eventType === "tool_result") {
              try {
                const resultData = JSON.parse(data);
                const updated = [...pendingToolCallsRef.current];
                const last = updated.findLast(tc => tc.tool === resultData.tool && !tc.result);
                if (last) last.result = resultData.summary || resultData.result;
                pendingToolCallsRef.current = updated;
                setPendingToolCalls(updated);
              } catch { /* ignore parse errors */ }
              continue;
            }

            if (eventType === "error") {
              throw new Error(data || "Chat failed");
            }

            if (eventType === "chunk" || eventType === "") {
              // Clear tool activity when first chunk arrives
              setToolActivity(null);

              // On first chunk, attach accumulated tool calls to the message
              if (assistantContent === "" && pendingToolCallsRef.current.length > 0) {
                const captured = [...pendingToolCallsRef.current];
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === "assistant") {
                    updated[updated.length - 1] = { ...last, toolCalls: captured };
                  }
                  return updated;
                });
                pendingToolCallsRef.current = [];
                setPendingToolCalls([]);
              }

              assistantContent += data;
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                updated[updated.length - 1] = {
                  ...last,
                  role: "assistant",
                  content: assistantContent,
                };
                return updated;
              });
            }
          }
        }

        // If we have pending tool calls but no content, attach them to the message
        if (pendingToolCallsRef.current.length > 0) {
          const captured = [...pendingToolCallsRef.current];
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = { ...last, toolCalls: captured };
            }
            return updated;
          });
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
        setToolActivity(null);
        pendingToolCallsRef.current = [];
        setPendingToolCalls([]);
        textareaRef.current?.focus();
      }
    },
    [mini, messages, isStreaming]
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
      await deleteMini(mini!.id);
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
    const isFailed = mini?.status === "failed";
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center p-4">
        <div className="w-full max-w-md rounded-xl border border-border/50 bg-card p-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-secondary">
            {isFailed ? (
              <AlertCircle className="h-6 w-6 text-destructive" />
            ) : (
              <Lock className="h-6 w-6 text-muted-foreground" />
            )}
          </div>
          <h2 className="mb-2 text-lg font-semibold">
            {isFailed ? "Mini Creation Failed" : "Mini Not Available"}
          </h2>
          <p className="mb-6 text-sm text-muted-foreground">
            {isFailed
              ? `Something went wrong while creating @${username}'s mini. You can try creating it again.`
              : `This mini doesn't exist or is private. @${username} may not have been cloned yet, or the owner has restricted access.`}
          </p>
          <div className="flex flex-col items-center gap-3">
            {isFailed ? (
              <Link href={`/create?username=${username}`}>
                <Button variant="default" className="gap-2">
                  <Sparkles className="h-4 w-4" />
                  Retry Creation
                </Button>
              </Link>
            ) : (
              <Link href={`/create?username=${username}`}>
                <Button variant="default" className="gap-2">
                  <Sparkles className="h-4 w-4" />
                  Create This Mini
                </Button>
              </Link>
            )}
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

  const sources = parseSourcesUsed(mini.sources_used);
  const hasSkillsOrTraits =
    (mini.skills && mini.skills.length > 0) ||
    (mini.traits && mini.traits.length > 0);
  const hasRadar = mini.values && mini.values.length >= 3;

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
        <div className="space-y-5">
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

          {/* ---- Section 1: Identity (always visible, NOT collapsible) ---- */}
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
              {mini.roles?.primary ? (
                <p className="text-sm text-muted-foreground">
                  {mini.roles.primary}
                </p>
              ) : (
                <p className="font-mono text-sm text-muted-foreground">
                  @{mini.username}
                </p>
              )}
            </div>
          </div>

          {/* Secondary roles */}
          {mini.roles?.secondary && mini.roles.secondary.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {mini.roles.secondary.map((role) => (
                <Badge key={role} variant="secondary" className="text-[11px]">
                  {role}
                </Badge>
              ))}
            </div>
          )}

          {/* Bio */}
          {mini.bio && (
            <p className="text-sm leading-relaxed text-muted-foreground">
              {mini.bio}
            </p>
          )}

          <Separator />

          {/* ---- Section 2: Skills & Traits (collapsible, collapsed by default) ---- */}
          {hasSkillsOrTraits && (
            <>
              <SidebarSection title="Skills & Traits">
                <div className="space-y-3">
                  {mini.skills && mini.skills.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {mini.skills.map((skill) => (
                        <Badge key={skill} variant="default" className="text-[11px]">
                          {skill}
                        </Badge>
                      ))}
                    </div>
                  )}
                  {mini.traits && mini.traits.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {mini.traits.map((trait) => (
                        <Badge key={trait} variant="outline" className="text-[11px]">
                          {trait}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              </SidebarSection>
              <Separator />
            </>
          )}

          {/* ---- Section 4: Personality Radar (collapsible, collapsed by default) ---- */}
          {hasRadar && (
            <>
              <SidebarSection title="Personality Radar">
                <PersonalityRadar values={mini.values} />
              </SidebarSection>
              <Separator />
            </>
          )}

          {/* ---- Section 5: Sources (collapsible, collapsed by default) ---- */}
          {sources.length > 0 && (
            <>
              <SidebarSection title="Sources">
                <div className="flex flex-wrap gap-1.5">
                  {sources.map((source) => (
                    <Badge key={source} variant="outline" className="gap-1 text-xs">
                      {source === "github" ? (
                        <Github className="h-3 w-3" />
                      ) : source === "claude_code" ? (
                        <MessageSquare className="h-3 w-3" />
                      ) : null}
                      {source === "github"
                        ? "GitHub"
                        : source === "claude_code"
                          ? "Claude Code"
                          : source}
                    </Badge>
                  ))}
                </div>
              </SidebarSection>
              <Separator />
            </>
          )}

          {/* ---- Section 6: Spirit Doc (collapsible, collapsed by default) ---- */}
          {mini.spirit_content && (
            <SidebarSection title="Spirit Doc">
              <div className="rounded-lg bg-secondary/30 p-4 text-sm text-muted-foreground whitespace-pre-wrap max-h-96 overflow-y-auto">
                {mini.spirit_content}
              </div>
            </SidebarSection>
          )}

          {/* Enhance with Claude Code CTA */}
          {isOwner && !sources.includes("claude_code") && (
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
          <div className="mx-auto max-w-3xl space-y-6">
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
                {user ? (
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
                ) : (
                  <div className="flex flex-col items-center gap-3 rounded-xl border border-border/50 bg-secondary/30 px-8 py-6">
                    <LogIn className="h-5 w-5 text-muted-foreground" />
                    <p className="text-sm text-muted-foreground">
                      Sign in to chat with <span className="font-mono font-medium text-foreground">@{username}</span>
                    </p>
                    <Button onClick={login} size="sm">
                      Sign In with GitHub
                    </Button>
                  </div>
                )}
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
                toolActivity={
                  isStreaming &&
                  i === messages.length - 1 &&
                  msg.role === "assistant"
                    ? toolActivity
                    : undefined
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

        {/* Input area with context picker */}
        <div className="border-t">
          {user ? (
            <>
              <div className="p-4">
                <div className="mx-auto flex max-w-3xl items-end gap-2">
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
            </>
          ) : (
            <div className="flex items-center justify-center gap-3 p-4">
              <p className="text-sm text-muted-foreground">
                Sign in to chat with @{mini.username}
              </p>
              <Button onClick={login} size="sm" variant="outline" className="gap-1.5">
                <LogIn className="h-3.5 w-3.5" />
                Sign In
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
