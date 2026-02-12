"use client";

import { useEffect, useState, useRef, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { PipelineProgress } from "@/components/pipeline-progress";
import { FileUpload } from "@/components/file-upload";
import {
  createMini,
  createMiniWithExclusions,
  deleteMini,
  getMiniByUsername,
  getSources,
  subscribePipelineStatus,
  type SourceInfo,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AuthGate } from "@/components/auth-gate";
import {
  Github,
  MessageSquare,
  Check,
  Rss,
  Globe,
  Code,
  Star,
  ChevronDown,
  ChevronRight,
  Settings2,
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
  website: {
    label: "Website URL",
    placeholder: "e.g. https://allisons.dev",
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
    case "website":
      return <Globe className={className} />;
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

/** Shape of a GitHub repo from the public API. */
interface GitHubRepo {
  name: string;
  full_name: string;
  language: string | null;
  stargazers_count: number;
  description: string | null;
  fork: boolean;
}

/** Language → color mapping for badges. */
const LANG_COLORS: Record<string, string> = {
  TypeScript: "bg-blue-500/20 text-blue-400",
  JavaScript: "bg-yellow-500/20 text-yellow-400",
  Python: "bg-green-500/20 text-green-400",
  Rust: "bg-orange-500/20 text-orange-400",
  Go: "bg-cyan-500/20 text-cyan-400",
  Java: "bg-red-500/20 text-red-400",
  C: "bg-gray-500/20 text-gray-400",
  "C++": "bg-pink-500/20 text-pink-400",
  "C#": "bg-purple-500/20 text-purple-400",
  Ruby: "bg-red-500/20 text-red-300",
  Shell: "bg-emerald-500/20 text-emerald-400",
  HTML: "bg-orange-500/20 text-orange-300",
  CSS: "bg-violet-500/20 text-violet-400",
  Swift: "bg-orange-500/20 text-orange-400",
  Kotlin: "bg-purple-500/20 text-purple-300",
};

function RepoSelector({
  username,
  excludedRepos,
  onExcludedChange,
  disabled,
}: {
  username: string;
  excludedRepos: Set<string>;
  onExcludedChange: (excluded: Set<string>) => void;
  disabled: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const fetched = useRef(false);

  const fetchRepos = useCallback(async () => {
    if (fetched.current) return;
    fetched.current = true;
    setLoading(true);
    setFetchError(null);
    try {
      const res = await fetch(
        `https://api.github.com/users/${username}/repos?sort=updated&per_page=30`
      );
      if (!res.ok) throw new Error("Failed to fetch repos");
      const data: GitHubRepo[] = await res.json();
      setRepos(data);
    } catch {
      setFetchError("Could not load repositories.");
    } finally {
      setLoading(false);
    }
  }, [username]);

  const handleExpand = () => {
    if (!expanded) {
      fetchRepos();
    }
    setExpanded(!expanded);
  };

  const toggleRepo = (fullName: string) => {
    const next = new Set(excludedRepos);
    if (next.has(fullName)) {
      next.delete(fullName);
    } else {
      next.add(fullName);
    }
    onExcludedChange(next);
  };

  const allSelected = repos.length > 0 && excludedRepos.size === 0;

  const toggleAll = () => {
    if (allSelected) {
      // Deselect all
      onExcludedChange(new Set(repos.map((r) => r.full_name)));
    } else {
      // Select all
      onExcludedChange(new Set());
    }
  };

  const includedCount = repos.length - excludedRepos.size;

  return (
    <div className="rounded-lg border border-border/50 bg-secondary/20">
      <button
        type="button"
        onClick={handleExpand}
        disabled={disabled}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm transition-colors hover:bg-secondary/40 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Settings2 className="h-4 w-4 text-muted-foreground" />
        <span className="flex-1 text-muted-foreground">
          {expanded
            ? "Customize repositories"
            : excludedRepos.size > 0
              ? `${includedCount} of ${repos.length} repos included`
              : "All repos will be included"}
        </span>
        {excludedRepos.size > 0 && !expanded && (
          <Badge
            variant="secondary"
            className="text-[10px] bg-chart-1/10 text-chart-1 border-chart-1/20"
          >
            customized
          </Badge>
        )}
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-border/50">
          {loading ? (
            <div className="space-y-2 p-4">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="flex items-center gap-3">
                  <Skeleton className="h-4 w-4 rounded" />
                  <Skeleton className="h-4 flex-1" />
                  <Skeleton className="h-4 w-12" />
                </div>
              ))}
            </div>
          ) : fetchError ? (
            <div className="p-4">
              <p className="text-xs text-muted-foreground">{fetchError}</p>
            </div>
          ) : repos.length === 0 ? (
            <div className="p-4">
              <p className="text-xs text-muted-foreground">
                No public repositories found.
              </p>
            </div>
          ) : (
            <>
              {/* Select All / Deselect All toggle */}
              <div className="flex items-center justify-between border-b border-border/30 px-4 py-2">
                <span className="text-xs text-muted-foreground">
                  {includedCount} of {repos.length} repos selected
                </span>
                <button
                  type="button"
                  onClick={toggleAll}
                  disabled={disabled}
                  className="text-xs text-chart-1 hover:text-chart-1/80 transition-colors disabled:opacity-50"
                >
                  {allSelected ? "Deselect All" : "Select All"}
                </button>
              </div>

              <ScrollArea className="max-h-64">
                <div className="divide-y divide-border/20">
                  {repos.map((repo) => {
                    const included = !excludedRepos.has(repo.full_name);
                    const langClass =
                      repo.language && LANG_COLORS[repo.language]
                        ? LANG_COLORS[repo.language]
                        : "bg-secondary text-muted-foreground";

                    return (
                      <label
                        key={repo.full_name}
                        className={`flex cursor-pointer items-start gap-3 px-4 py-2.5 transition-colors hover:bg-secondary/40 ${
                          disabled ? "cursor-not-allowed opacity-50" : ""
                        }`}
                      >
                        <div className="flex h-5 w-5 shrink-0 items-center justify-center pt-0.5">
                          <div
                            className={`flex h-4 w-4 items-center justify-center rounded border transition-colors ${
                              included
                                ? "border-chart-1 bg-chart-1 text-background"
                                : "border-border"
                            }`}
                          >
                            {included && <Check className="h-2.5 w-2.5" />}
                          </div>
                        </div>
                        <input
                          type="checkbox"
                          checked={included}
                          onChange={() => toggleRepo(repo.full_name)}
                          disabled={disabled}
                          className="sr-only"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-sm font-medium text-foreground">
                              {repo.name}
                            </span>
                            {repo.language && (
                              <Badge
                                variant="secondary"
                                className={`text-[10px] px-1.5 py-0 border-transparent ${langClass}`}
                              >
                                {repo.language}
                              </Badge>
                            )}
                            {repo.stargazers_count > 0 && (
                              <span className="flex items-center gap-0.5 text-[10px] text-muted-foreground">
                                <Star className="h-2.5 w-2.5" />
                                {repo.stargazers_count}
                              </span>
                            )}
                            {repo.fork && (
                              <Badge
                                variant="secondary"
                                className="text-[10px] px-1.5 py-0 border-transparent bg-secondary text-muted-foreground"
                              >
                                fork
                              </Badge>
                            )}
                          </div>
                          {repo.description && (
                            <p className="mt-0.5 truncate text-xs text-muted-foreground/70">
                              {repo.description}
                            </p>
                          )}
                        </div>
                      </label>
                    );
                  })}
                </div>
              </ScrollArea>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function CreatePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const username = searchParams.get("username") || "";
  const regenerate = searchParams.get("regenerate") === "true";
  const { user } = useAuth();

  const isOwnMini = user?.github_username === username;

  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [selectedSources, setSelectedSources] = useState<string[]>(
    regenerate ? ["github", "claude_code"] : ["github"]
  );
  const [sourceIdentifiers, setSourceIdentifiers] = useState<
    Record<string, string>
  >({});
  const [excludedRepos, setExcludedRepos] = useState<Set<string>>(new Set());
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
      const existing = await getMiniByUsername(username).catch(() => null);
      if (existing?.status === "ready" && !regenerate) {
        router.replace(`/m/${username}`);
        return;
      }

      // If regenerating, delete the existing mini first
      if (existing && regenerate) {
        await deleteMini(existing.id).catch(() => {});
      }

      // Filter out empty source identifiers
      const filteredIdentifiers = Object.fromEntries(
        Object.entries(sourceIdentifiers).filter(([, v]) => v.trim() !== "")
      );
      const hasIdentifiers = Object.keys(filteredIdentifiers).length > 0;

      let mini = regenerate ? null : existing;
      if (!mini || mini.status === "failed") {
        if (excludedRepos.size > 0) {
          mini = await createMiniWithExclusions(
            username,
            selectedSources,
            Array.from(excludedRepos),
            hasIdentifiers ? filteredIdentifiers : undefined,
          );
        } else {
          mini = await createMini(
            username,
            selectedSources,
            hasIdentifiers ? filteredIdentifiers : undefined,
          );
        }
      }

      if (!mini) return;

      setStarted(true);

      // Subscribe to SSE for pipeline updates using the mini's integer id
      const es = subscribePipelineStatus(mini.id);

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
        getMiniByUsername(username)
          .then((m) => {
            if (m.status === "ready") {
              router.replace(`/m/${username}`);
            } else if (m.status === "failed") {
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
  }, [username, router, selectedSources, excludedRepos, sourceIdentifiers]);

  // Auto-start if mini is already processing
  useEffect(() => {
    if (!username) return;
    if (regenerate) return; // Don't auto-redirect when regenerating
    getMiniByUsername(username)
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
  }, [username, router, startPipeline, regenerate]);

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

          {/* Repo selection for GitHub source */}
          {selectedSources.includes("github") && username && (
            <RepoSelector
              username={username}
              excludedRepos={excludedRepos}
              onExcludedChange={setExcludedRepos}
              disabled={started}
            />
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
    <AuthGate icon={Github} message="Sign in with GitHub to create a mini.">
      <Suspense
        fallback={
          <div className="flex min-h-[80vh] items-center justify-center">
            <p className="text-muted-foreground">Loading...</p>
          </div>
        }
      >
        <CreatePageInner />
      </Suspense>
    </AuthGate>
  );
}
