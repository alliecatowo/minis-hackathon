"use client";

import { cn } from "@/lib/utils";
import type { ModelInfo } from "@/lib/api";

const PROVIDERS = [
  { id: "gemini", label: "Gemini" },
  { id: "openai", label: "OpenAI" },
  { id: "anthropic", label: "Anthropic" },
] as const;

interface ModelSelectorProps {
  provider: string;
  model: string | null;
  onProviderChange: (provider: string) => void;
  onModelChange: (model: string) => void;
  models: Record<string, ModelInfo[]>;
}

export function ModelSelector({
  provider,
  model,
  onProviderChange,
  onModelChange,
  models,
}: ModelSelectorProps) {
  const providerModels = models[provider] || [];

  return (
    <div className="space-y-3">
      <div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          Provider
        </label>
        <div className="flex gap-2">
          {PROVIDERS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                onProviderChange(p.id);
                // Auto-select first model for new provider
                const newModels = models[p.id] || [];
                if (newModels.length > 0) {
                  onModelChange(newModels[0].id);
                }
              }}
              className={cn(
                "flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-all",
                provider === p.id
                  ? "border-chart-1/50 bg-chart-1/10 text-foreground"
                  : "border-border/50 text-muted-foreground hover:border-border hover:bg-secondary/50"
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          Model
        </label>
        {providerModels.length > 0 ? (
          <select
            value={model || ""}
            onChange={(e) => onModelChange(e.target.value)}
            className="h-9 w-full appearance-none rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 dark:bg-input/30 dark:border-input"
          >
            {providerModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        ) : (
          <p className="text-xs text-muted-foreground">
            No models available for this provider.
          </p>
        )}
      </div>
    </div>
  );
}
