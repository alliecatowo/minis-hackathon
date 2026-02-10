"use client";

import { useEffect, useState, useRef, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { PipelineProgress } from "@/components/pipeline-progress";
import { createMini, getMini, subscribePipelineStatus } from "@/lib/api";

function CreatePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const username = searchParams.get("username") || "";

  const [currentStep, setCurrentStep] = useState("fetching");
  const [message, setMessage] = useState("Initializing...");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const initiated = useRef(false);

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
        await createMini(username);
      }

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
        getMini(username).then((mini) => {
          if (mini.status === "ready") {
            router.replace(`/m/${username}`);
          } else if (mini.status === "failed") {
            setError("Pipeline failed. Please try again.");
          }
        }).catch(() => {
          setError("Lost connection to server.");
        });
      };
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start pipeline.");
    }
  }, [username, router]);

  useEffect(() => {
    if (initiated.current) return;
    initiated.current = true;
    startPipeline();
  }, [startPipeline]);

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
          Creating mini for{" "}
          <span className="font-mono text-chart-1">@{username}</span>
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Analyzing their GitHub footprint...
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
      ) : (
        <PipelineProgress
          currentStep={currentStep}
          message={message}
          progress={progress}
        />
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
