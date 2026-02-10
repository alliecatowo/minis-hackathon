"use client";

import { useEffect, useState, useRef, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { PipelineProgress } from "@/components/pipeline-progress";
import {
  createMini,
  getMini,
  getSources,
  subscribePipelineStatus,
  type SourceInfo,
} from "@/lib/api";
import { Github, MessageSquare, Check } from "lucide-react";

function SourceToggle({
  source,
  selected,
  onToggle,
  disabled,
}: {
  source: SourceInfo;
  selected: boolean;
  onToggle: () => void;
  disabled: boolean;
}) {
  const icon =
    source.id === "github" ? (
      <Github className="h-4 w-4" />
    ) : (
      <MessageSquare className="h-4 w-4" />
    );

  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled || !source.available}
      className={`flex items-center gap-3 rounded-lg border px-4 py-3 text-left text-sm transition-all ${
        selected
          ? "border-chart-1/50 bg-chart-1/10 text-foreground"
          : source.available
            ? "border-border/50 text-muted-foreground hover:border-border hover:bg-secondary/50"
            : "cursor-not-allowed border-border/30 text-muted-foreground/50 opacity-50"
      }`}
    >
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${
          selected ? "bg-chart-1/20 text-chart-1" : "bg-secondary text-muted-foreground"
        }`}
      >
        {icon}
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
  );
}

function CreatePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const username = searchParams.get("username") || "";

  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [selectedSources, setSelectedSources] = useState<string[]>(["github"]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [started, setStarted] = useState(false);
  const [currentStep, setCurrentStep] = useState("fetching");
  const [message, setMessage] = useState("Initializing...");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const initiated = useRef(false);

  // Fetch available sources
  useEffect(() => {
    getSources()
      .then((s) => {
        setSources(s);
        // Auto-select all available sources
        setSelectedSources(s.filter((src) => src.available).map((src) => src.id));
      })
      .catch(() => {
        setSources([
          { id: "github", name: "GitHub", description: "Commits, PRs, and reviews", available: true },
        ]);
      })
      .finally(() => setSourcesLoading(false));
  }, []);

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

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.step) setCurrentStep(data.step);
          if (data.message) setMessage(data.message);
          if (data.progress != null) setProgress(data.progress);

          if (data.step === "complete" || data.progress >= 100) {
            es.close();
            setTimeout(() => {
              router.replace(`/m/${username}`);
            }, 1000);
          }
        } catch {
          // ignore parse errors
        }
      };

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

  const handleStart = () => {
    if (initiated.current) return;
    initiated.current = true;
    startPipeline();
  };

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
              {[1, 2].map((i) => (
                <div
                  key={i}
                  className="h-[68px] animate-pulse rounded-lg border border-border/30 bg-secondary/30"
                />
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              {sources.map((source) => (
                <SourceToggle
                  key={source.id}
                  source={source}
                  selected={selectedSources.includes(source.id)}
                  onToggle={() => toggleSource(source.id)}
                  disabled={started}
                />
              ))}
            </div>
          )}

          <button
            onClick={handleStart}
            disabled={selectedSources.length === 0}
            className="w-full rounded-lg bg-primary px-4 py-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Start Analysis
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
