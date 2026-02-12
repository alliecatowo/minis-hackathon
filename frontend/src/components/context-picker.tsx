"use client";

import { cn } from "@/lib/utils";
import type { MiniContext } from "@/lib/api";

interface ContextPickerProps {
  contexts: MiniContext[];
  activeContext: string | null;
  onContextChange: (contextKey: string | null) => void;
}

export function ContextPicker({
  contexts,
  activeContext,
  onContextChange,
}: ContextPickerProps) {
  if (contexts.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 overflow-x-auto px-1 py-1.5">
      <span className="shrink-0 text-[10px] uppercase tracking-wider text-muted-foreground/50">
        Context
      </span>
      <button
        onClick={() => onContextChange(null)}
        className={cn(
          "shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-all",
          activeContext === null
            ? "border-chart-1/50 bg-chart-1/15 text-chart-1"
            : "border-border/50 text-muted-foreground hover:border-border hover:text-foreground"
        )}
      >
        Default
      </button>
      {contexts.map((ctx) => (
        <button
          key={ctx.context_key}
          onClick={() => onContextChange(ctx.context_key)}
          title={ctx.description}
          className={cn(
            "shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-all",
            activeContext === ctx.context_key
              ? "border-chart-1/50 bg-chart-1/15 text-chart-1"
              : "border-border/50 text-muted-foreground hover:border-border hover:text-foreground",
          )}
          style={{
            opacity: activeContext === ctx.context_key ? 1 : Math.max(0.5, ctx.confidence),
          }}
        >
          {ctx.display_name}
        </button>
      ))}
    </div>
  );
}
