"use client";

import { useEffect, useState, useRef, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { PipelineProgress } from "@/components/pipeline-progress";
import { FileUpload } from "@/components/file-upload";
import {
  createMini,
  getMini,
  getSources,
  subscribePipelineStatus,
  type SourceInfo,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  Github,
  MessageSquare,
  Check,
  Rss,
  Globe,
  Code,
} from "lucide-react";

/** Metadata for sources that need a separate identifier (not the main GitHub username). */
const SOURCE_IDENTIFIER_META: Record<
  string,
  { label: string; placeholder: string }
> = {
  hackernews: {
    label: "Hacker News username",
    placeholder: "e.g. pg",
  },
  stackoverflow: {
    label: "Stack Overflow user ID",
    placeholder: "e.g. 22656",
  },
  blog: {
    label: "Blog or RSS feed URL",
    placeholder: "e.g. https://example.com/feed.xml",
  },
  devblog: {
    label: "Dev.to username",
    placeholder: "e.g. bendhalpern",
  },
};

/** Pick a lucide icon based on source id. */
function SourceIcon({ id, className }: { id: string; className?: string }) {
  switch (id) {
    case "github":
      return <Github className={className} />;
    case "claude_code":
      return <MessageSquare className={className} />;
    case "blog":
      return <Rss className={className} />;
    case "hackernews":
      return <Globe className={className} />;
    case "stackoverflow":
      return <Code className={className} />;
    case "devblog":
      return <Code className={className} />;
    default:
      return <MessageSquare className={className} />;
  }
}

function SourceToggle({
  source,
  selected,
  onToggle,
  disabled,
  identifier,
  onIdentifierChange,
}: {
  source: SourceInfo;
  selected: boolean;
  onToggle: () => void;
  disabled: boolean;
  identifier?: string;
  onIdentifierChange?: (value: string) => void;
}) {
  const meta = SOURCE_IDENTIFIER_META[source.id];

  return (
    <div className="space-y-1.5">
      <button
        type="button"
        onClick={onToggle}
        disabled={disabled || !source.available}
        className={`flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left text-sm transition-all ${
          selected
            ? "border-chart-1/50 bg-chart-1/10 text-foreground"
            : source.available
              ? "border-border/50 text-muted-foreground hover:border-border hover:bg-secondary/50"
              : "cursor-not-allowed border-border/30 text-muted-foreground/50 opacity-50"
        }`}
      >
        <div
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${
            selected
              ? "bg-chart-1/20 text-chart-1"
              : "bg-secondary text-muted-foreground"
          }`}
        >
          <SourceIcon id={source.id} className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium">{source.name}</span>
            {!source.available && (
              <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                Coming soon
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">{source.description}</p>
        </div>
        <div
          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors ${
            selected
              ? "border-chart-1 bg-chart-1 text-background"
              : "border-border"
          }`}
        >
          {selected && <Check className="h-3 w-3" />}
        </div>
      </button>

      {/* Identifier input for sources that need one */}
      {selected && meta && onIdentifierChange && (
        <input
          type="text"
          value={identifier ?? ""}
          onChange={(e) => onIdentifierChange(e.target.value)}
          placeholder={meta.placeholder}
          disabled={disabled}
          className="ml-11 w-[calc(100%-2.75rem)] rounded-md border border-border/50 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:border-chart-1/50 focus:outline-none focus:ring-1 focus:ring-chart-1/30"
        />
      )}
    </div>
  );
}

function CreatePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const username = searchParams.get("username") || "";
  const { user } = useAuth();

  const isOwnMini = user?.github_username === username;

  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [selectedSources, setSelectedSources] = useState<string[]>(["github"]);
  const [sourceIdentifiers, setSourceIdentifiers] = useState<
    Record<string, string>
  >({});
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [started, setStarted] = useState(false);
  const [currentStep, setCurrentStep] = useState("fetching");
  const [message, setMessage] = useState("Initializing...");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [uploadComplete, setUploadComplete] = useState(false);
  const initiated = useRef(false);

  // Fetch available sources
  useEffect(() => {
    getSources()
      .then((s) => {
        setSources(s);
        // Auto-select github only; let user opt-in to other sources
        const defaultSources = s
          .filter((src) => src.available && src.id === "github")
          .map((src) => src.id);
        setSelectedSources(defaultSources);
      })
      .catch(() => {
        setSources([
          {
            id: "github",
            name: "GitHub",
            description: "Commits, PRs, and reviews",
            available: true,
          },
        ]);
      })
      .finally(() => setSourcesLoading(false));
  }, [isOwnMini]);

  const startPipeline = useCallback(async () => {
    if (!username) return;

    try {
      // Check if mini already exists and is ready
      const existing = await getMini(username).catch(() => null);
      if (existing?.status === "ready") {
        router.replace(`/m/${username}`);
        return;
      }

      // If not already processing, kick off creation
      if (!existing || existing.status === "failed") {
        await createMini(username, selectedSources);
      }

      setStarted(true);

      // Subscribe to SSE for pipeline updates
      const es = subscribePipelineStatus(username);

      es.addEventListener("progress", (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data);
          if (data.stage) setCurrentStep(data.stage);
          if (data.message) setMessage(data.message);
          if (data.progress != null) setProgress(data.progress * 100);
        } catch {
          // ignore parse errors
        }
      });

      es.addEventListener("done", () => {
        es.close();
        setTimeout(() => {
          router.replace(`/m/${username}`);
        }, 1000);
      });

      es.onerror = () => {
        es.close();
        // Check if mini completed while we were disconnected
        getMini(username)
          .then((mini) => {
            if (mini.status === "ready") {
              router.replace(`/m/${username}`);
            } else if (mini.status === "failed") {
              setError("Pipeline failed. Please try again.");
            }
          })
          .catch(() => {
            setError("Lost connection to server.");
          });
      };
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to start pipeline."
      );
    }
  }, [username, router, selectedSources]);

  // Auto-start if mini is already processing
  useEffect(() => {
    if (!username) return;
    getMini(username)
      .then((existing) => {
        if (existing?.status === "processing") {
          setStarted(true);
          if (!initiated.current) {
            initiated.current = true;
            startPipeline();
          }
        } else if (existing?.status === "ready") {
          router.replace(`/m/${username}`);
        }
      })
      .catch(() => {
        // Mini doesn't exist yet, that's fine
      });
  }, [username, router, startPipeline]);

  const toggleSource = (id: string) => {
    setSelectedSources((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  };

  const updateIdentifier = (sourceId: string, value: string) => {
    setSourceIdentifiers((prev) => ({ ...prev, [sourceId]: value }));
  };

  const handleStart = () => {
    if (initiated.current) return;
    initiated.current = true;
    startPipeline();
  };

  // Need upload for claude_code if selected and not yet uploaded
  const needsUpload =
    isOwnMini &&
    selectedSources.includes("claude_code") &&
    !uploadComplete;

  if (!username) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-muted-foreground">No username provided.</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-[80vh] flex-col items-center justify-center px-4">
      <div className="mb-8 text-center">
        <Avatar className="mx-auto mb-4 h-16 w-16">
          <AvatarImage
            src={`https://github.com/${username}.png`}
            alt={username}
          />
          <AvatarFallback className="font-mono text-lg">
            {username.slice(0, 2).toUpperCase()}
          </AvatarFallback>
        </Avatar>
        <h1 className="text-xl font-semibold">
          {started ? "Creating" : "Create"} mini for{" "}
          <span className="font-mono text-chart-1">@{username}</span>
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {started
            ? "Analyzing their footprint..."
            : "Choose data sources to analyze"}
        </p>
      </div>

      {error ? (
        <div className="max-w-md text-center">
          <p className="text-sm text-destructive">{error}</p>
          <button
            onClick={() => {
              setError(null);
              setProgress(0);
              setCurrentStep("fetching");
              setMessage("Retrying...");
              initiated.current = false;
              startPipeline();
            }}
            className="mt-4 text-sm text-muted-foreground underline hover:text-foreground"
          >
            Try again
          </button>
        </div>
      ) : started ? (
        <PipelineProgress
          currentStep={currentStep}
          message={message}
          progress={progress}
        />
      ) : (
        <div className="w-full max-w-md space-y-4">
          {/* Source selection */}
          {sourcesLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-[68px] animate-pulse rounded-lg border border-border/30 bg-secondary/30"
                />
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              {sources
                .filter((source) => isOwnMini || source.id !== "claude_code")
                .map((source) => (
                  <SourceToggle
                    key={source.id}
                    source={source}
                    selected={selectedSources.includes(source.id)}
                    onToggle={() => toggleSource(source.id)}
                    disabled={started}
                    identifier={sourceIdentifiers[source.id]}
                    onIdentifierChange={(val) =>
                      updateIdentifier(source.id, val)
                    }
                  />
                ))}
            </div>
          )}

          {/* File upload for Claude Code (own mini only) */}
          {isOwnMini && selectedSources.includes("claude_code") && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">
                Upload Claude Code conversation files
              </p>
              <FileUpload
                onUploadComplete={() => setUploadComplete(true)}
              />
            </div>
          )}

          <button
            onClick={handleStart}
            disabled={selectedSources.length === 0 || needsUpload}
            className="w-full rounded-lg bg-primary px-4 py-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {needsUpload ? "Upload files first" : "Start Analysis"}
          </button>
        </div>
      )}
    </div>
  );
}

export default function CreatePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[80vh] items-center justify-center">
          <p className="text-muted-foreground">Loading...</p>
        </div>
      }
    >
      <CreatePageInner />
    </Suspense>
  );
}
