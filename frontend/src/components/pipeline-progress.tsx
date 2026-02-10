"use client";

import { cn } from "@/lib/utils";
import { Check, Loader2, Circle } from "lucide-react";

const PIPELINE_STEPS = [
  { key: "fetching", label: "Fetching GitHub data" },
  { key: "analyzing", label: "Analyzing evidence" },
  { key: "extracting", label: "Extracting values" },
  { key: "synthesizing", label: "Synthesizing spirit" },
  { key: "complete", label: "Complete" },
];

type StepStatus = "pending" | "active" | "complete";

function getStepStatuses(currentStep: string, progress: number): StepStatus[] {
  if (progress >= 100) {
    return PIPELINE_STEPS.map(() => "complete");
  }

  const currentIndex = PIPELINE_STEPS.findIndex((s) => s.key === currentStep);
  return PIPELINE_STEPS.map((_, i) => {
    if (i < currentIndex) return "complete";
    if (i === currentIndex) return "active";
    return "pending";
  });
}

export function PipelineProgress({
  currentStep,
  message,
  progress,
}: {
  currentStep: string;
  message: string;
  progress: number;
}) {
  const statuses = getStepStatuses(currentStep, progress);

  return (
    <div className="w-full max-w-md space-y-6">
      {/* Progress bar */}
      <div className="space-y-2">
        <div className="h-1 w-full overflow-hidden rounded-full bg-secondary">
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{ width: `${Math.min(progress, 100)}%` }}
          />
        </div>
        <p className="font-mono text-xs text-muted-foreground">
          {message || "Starting..."}
        </p>
      </div>

      {/* Steps */}
      <div className="space-y-3">
        {PIPELINE_STEPS.map((step, i) => {
          const status = statuses[i];
          return (
            <div
              key={step.key}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 transition-all",
                status === "active" && "bg-secondary",
                status === "complete" && "opacity-70"
              )}
            >
              <div className="flex h-5 w-5 shrink-0 items-center justify-center">
                {status === "complete" ? (
                  <Check className="h-4 w-4 text-emerald-400" />
                ) : status === "active" ? (
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                ) : (
                  <Circle className="h-3 w-3 text-muted-foreground/50" />
                )}
              </div>
              <span
                className={cn(
                  "text-sm",
                  status === "active" && "font-medium text-foreground",
                  status === "pending" && "text-muted-foreground/50",
                  status === "complete" && "text-muted-foreground"
                )}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
