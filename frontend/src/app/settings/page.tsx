"use client";

import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ModelSelector } from "@/components/model-selector";
import { useAuth } from "@/lib/auth";
import {
  getSettings,
  updateSettings,
  getUsage,
  getAdminCostControls,
  getAvailableModels,
  getTierModels,
  testApiKey,
  type UserSettings,
  type UsageInfo,
  type AdminCostControls,
  type ModelInfo,
  type TierModelsResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { AuthGate } from "@/components/auth-gate";
import {
  Key,
  BarChart3,
  User,
  Eye,
  EyeOff,
  Check,
  Loader2,
  LogOut,
  Shield,
  FlaskConical,
  Cpu,
} from "lucide-react";

type Tab = "api-keys" | "models" | "usage" | "account";

const TABS: { id: Tab; label: string; icon: typeof Key }[] = [
  { id: "api-keys", label: "API Keys", icon: Key },
  { id: "models", label: "Model Tiers", icon: Cpu },
  { id: "usage", label: "Usage", icon: BarChart3 },
  { id: "account", label: "Account", icon: User },
];

const TIER_LABELS: Record<string, string> = {
  fast: "Fast",
  standard: "Standard",
  thinking: "Thinking",
};

const TIER_DESCRIPTIONS: Record<string, string> = {
  fast: "Compaction, summaries, classifications",
  standard: "Explorer agents, chat, tool-calling",
  thinking: "Complex synthesis, soul documents",
};

function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const isHigh = pct >= 80;

  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
      <div
        className={cn(
          "h-full rounded-full transition-all duration-500",
          isHigh ? "bg-destructive" : "bg-chart-1"
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function ApiKeysTab() {
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [models, setModels] = useState<Record<string, ModelInfo[]>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [provider, setProvider] = useState("gemini");
  const [model, setModel] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);

  // Test key state
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ valid: boolean; message: string } | null>(null);

  useEffect(() => {
    Promise.all([getSettings(), getAvailableModels()])
      .then(([s, m]) => {
        setSettings(s);
        setModels(m);
        setProvider(s.llm_provider || "gemini");
        setModel(s.preferred_model || null);
      })
      .catch(() => {
        setError("Failed to load settings");
        toast.error("Failed to load settings");
      })
      .finally(() => setLoading(false));
  }, []);

  // Clear test result when key changes
  useEffect(() => {
    setTestResult(null);
  }, [apiKey, provider]);

  const handleTestKey = useCallback(async () => {
    if (!apiKey.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testApiKey(provider, apiKey);
      setTestResult(result);
      if (result.valid) {
        toast.success("API key is valid");
      } else {
        toast.error(result.message || "Invalid API key");
      }
    } catch {
      setTestResult({ valid: false, message: "Could not reach verification service." });
      toast.error("Could not reach verification service");
    } finally {
      setTesting(false);
    }
  }, [provider, apiKey]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const data: Record<string, string> = {
        llm_provider: provider,
      };
      if (model) data.preferred_model = model;
      if (apiKey) data.llm_api_key = apiKey;

      const updated = await updateSettings(data);
      setSettings(updated);
      setApiKey("");
      setTestResult(null);
      setSaved(true);
      toast.success("Settings saved");
      setTimeout(() => setSaved(false), 2000);
    } catch {
      setError("Failed to save settings");
      toast.error("Failed to save settings");
    } finally {
      setSaving(false);
    }
  }, [provider, model, apiKey]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-24" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Current status */}
      <div className="flex items-center gap-2">
        <div
          className={cn(
            "h-2 w-2 rounded-full",
            settings?.has_api_key ? "bg-emerald-500" : "bg-muted-foreground/40"
          )}
        />
        <span className="text-xs text-muted-foreground">
          {settings?.has_api_key
            ? "API key configured"
            : "Using shared API key (rate limited)"}
        </span>
      </div>

      {/* Provider + model selector */}
      <ModelSelector
        provider={provider}
        model={model}
        onProviderChange={setProvider}
        onModelChange={setModel}
        models={models}
      />

      {/* API key input */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          API Key
        </label>
        <div className="relative">
          <Input
            type={showKey ? "text" : "password"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={
              settings?.has_api_key
                ? "Enter new key to replace existing"
                : "Paste your API key"
            }
            className="pr-10 font-mono text-sm"
          />
          <button
            type="button"
            onClick={() => setShowKey(!showKey)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            {showKey ? (
              <EyeOff className="h-3.5 w-3.5" />
            ) : (
              <Eye className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
        <p className="mt-1 text-[11px] text-muted-foreground">
          Your key is encrypted and only used for your requests.
        </p>

        {/* Test key button + feedback */}
        <div className="mt-2 flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleTestKey}
            disabled={!apiKey.trim() || testing}
            className="gap-1.5 text-xs"
          >
            {testing ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <FlaskConical className="h-3 w-3" />
            )}
            Test Key
          </Button>
          {testResult && (
            <span
              className={cn(
                "flex items-center gap-1 text-xs",
                testResult.valid ? "text-emerald-500" : "text-destructive"
              )}
            >
              {testResult.valid ? (
                <Check className="h-3 w-3" />
              ) : null}
              {testResult.message}
            </span>
          )}
        </div>
      </div>

      {/* Save button */}
      <div className="flex items-center gap-3">
        <Button
          onClick={handleSave}
          disabled={saving}
          size="sm"
          className="gap-1.5"
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : saved ? (
            <Check className="h-3.5 w-3.5" />
          ) : null}
          {saved ? "Saved" : "Save Changes"}
        </Button>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
    </div>
  );
}

function ModelTiersTab() {
  const [tierData, setTierData] = useState<TierModelsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // tier → selected model id
  const [preferences, setPreferences] = useState<Record<string, string>>({});
  const [provider, setProvider] = useState("gemini");

  useEffect(() => {
    Promise.all([getSettings(), getTierModels()])
      .then(([s, td]) => {
        setTierData(td);
        const prov = s.llm_provider || "gemini";
        setProvider(prov);
        // Seed from saved preferences or system defaults
        const saved = s.model_preferences ?? {};
        const defaults = td.defaults[prov] ?? {};
        const merged: Record<string, string> = {};
        for (const tier of td.tiers) {
          merged[tier] = saved[tier] ?? defaults[tier] ?? "";
        }
        setPreferences(merged);
      })
      .catch(() => {
        setError("Failed to load model preferences");
        toast.error("Failed to load model preferences");
      })
      .finally(() => setLoading(false));
  }, []);

  // When provider changes, re-seed from defaults if no saved pref
  const handleProviderChange = useCallback(
    (newProvider: string) => {
      setProvider(newProvider);
      if (!tierData) return;
      const defaults = tierData.defaults[newProvider] ?? {};
      setPreferences((prev) => {
        const next = { ...prev };
        for (const tier of tierData.tiers) {
          if (!next[tier]) {
            next[tier] = defaults[tier] ?? "";
          }
        }
        return next;
      });
    },
    [tierData]
  );

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await updateSettings({
        llm_provider: provider,
        model_preferences: preferences,
      });
      setSaved(true);
      toast.success("Settings saved");
      setTimeout(() => setSaved(false), 2000);
    } catch {
      setError("Failed to save model preferences");
      toast.error("Failed to save model preferences");
    } finally {
      setSaving(false);
    }
  }, [provider, preferences]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (!tierData) {
    return <p className="text-sm text-destructive">{error ?? "Failed to load."}</p>;
  }

  const PROVIDERS = ["gemini", "openai", "anthropic"] as const;

  return (
    <div className="space-y-6">
      <p className="text-xs text-muted-foreground">
        Choose which model handles each pipeline tier. Changes apply to new mini
        creations and chat sessions.
      </p>

      {/* Provider selector */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          Provider
        </label>
        <div className="flex gap-2">
          {PROVIDERS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => handleProviderChange(p)}
              className={cn(
                "flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-all capitalize",
                provider === p
                  ? "border-chart-1/50 bg-chart-1/10 text-foreground"
                  : "border-border/50 text-muted-foreground hover:border-border hover:bg-secondary/50"
              )}
            >
              {p === "openai" ? "OpenAI" : p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Tier selectors */}
      <div className="space-y-4">
        {tierData.tiers.map((tier) => {
          const models = tierData.providers[provider]?.[tier] ?? [];
          const currentVal = preferences[tier] ?? "";
          const defaultVal = tierData.defaults[provider]?.[tier] ?? "";

          return (
            <div key={tier} className="rounded-lg border border-border/50 p-4 space-y-2">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-medium">{TIER_LABELS[tier] ?? tier}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {TIER_DESCRIPTIONS[tier] ?? ""}
                  </p>
                </div>
                {currentVal === defaultVal && (
                  <Badge
                    variant="outline"
                    className="text-[10px] border-muted-foreground/30 text-muted-foreground"
                  >
                    default
                  </Badge>
                )}
              </div>
              {models.length > 0 ? (
                <select
                  value={currentVal}
                  onChange={(e) =>
                    setPreferences((prev) => ({ ...prev, [tier]: e.target.value }))
                  }
                  className="h-9 w-full appearance-none rounded-md border border-input bg-background px-3 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 dark:bg-input/30 dark:border-input"
                >
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>
              ) : (
                <p className="text-xs text-muted-foreground">
                  No models available for this tier.
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* Save */}
      <div className="flex items-center gap-3">
        <Button
          onClick={handleSave}
          disabled={saving}
          size="sm"
          className="gap-1.5"
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : saved ? (
            <Check className="h-3.5 w-3.5" />
          ) : null}
          {saved ? "Saved" : "Save Preferences"}
        </Button>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
    </div>
  );
}

function UsageTab() {
  const [usage, setUsage] = useState<UsageInfo | null>(null);
  const [adminControls, setAdminControls] = useState<AdminCostControls | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getUsage(), getAdminCostControls()])
      .then(([usageData, adminData]) => {
        setUsage(usageData);
        setAdminControls(adminData);
      })
      .catch(() => setError("Failed to load usage data"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  if (!usage) return null;

  return (
    <div className="space-y-6">
      {usage.is_exempt && (
        <div className="flex items-center gap-2">
          <Badge className="gap-1 bg-chart-1/20 text-chart-1 border-chart-1/30">
            <Shield className="h-3 w-3" />
            Unlimited
          </Badge>
          <span className="text-xs text-muted-foreground">
            Rate limits do not apply to your account
          </span>
        </div>
      )}

      {/* Chat messages */}
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <span className="text-sm font-medium">Chat Messages</span>
          <span className="font-mono text-xs text-muted-foreground">
            {usage.is_exempt ? (
              <span className="text-chart-1">{usage.chat_messages_today} sent today</span>
            ) : (
              <>
                {usage.chat_messages_today}
                <span className="text-muted-foreground/60">
                  /{usage.chat_message_limit}
                </span>{" "}
                today
              </>
            )}
          </span>
        </div>
        {!usage.is_exempt && (
          <ProgressBar
            value={usage.chat_messages_today}
            max={usage.chat_message_limit}
          />
        )}
      </div>

      {/* Mini creations */}
      <div className="space-y-2">
        <div className="flex items-baseline justify-between">
          <span className="text-sm font-medium">Mini Creations</span>
          <span className="font-mono text-xs text-muted-foreground">
            {usage.is_exempt ? (
              <span className="text-chart-1">{usage.mini_creates_today} created today</span>
            ) : (
              <>
                {usage.mini_creates_today}
                <span className="text-muted-foreground/60">
                  /{usage.mini_create_limit}
                </span>{" "}
                today
              </>
            )}
          </span>
        </div>
        {!usage.is_exempt && (
          <ProgressBar
            value={usage.mini_creates_today}
            max={usage.mini_create_limit}
          />
        )}
      </div>

      <p className="text-[11px] text-muted-foreground">
        Limits reset daily at midnight UTC. Add your own API key to remove
        limits.
      </p>

      {adminControls && (
        <div className="rounded-lg border border-border/60 bg-secondary/30 p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Admin Cost Controls</h3>
              <p className="text-xs text-muted-foreground">
                Platform LLM budget, pipeline cap, and kill-switch state.
              </p>
            </div>
            <Badge
              variant={adminControls.llm_kill_switch_enabled ? "destructive" : "secondary"}
            >
              {adminControls.llm_kill_switch_enabled ? "LLM disabled" : "LLM enabled"}
            </Badge>
          </div>

          <div className="grid gap-3 text-xs sm:grid-cols-3">
            <div>
              <p className="text-muted-foreground">Global spend</p>
              <p className="font-mono">
                ${adminControls.global_total_spent_usd.toFixed(2)}
                <span className="text-muted-foreground">
                  /${adminControls.global_monthly_budget_usd.toFixed(2)}
                </span>
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">Pipeline token cap</p>
              <p className="font-mono">
                {adminControls.max_pipeline_tokens_per_mini.toLocaleString()}
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">Token-budget failures</p>
              <p className="font-mono">
                {adminControls.token_budget_exceeded_minis.length}
              </p>
            </div>
          </div>

          {adminControls.token_budget_exceeded_minis.length > 0 && (
            <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs">
              Token budget exceeded:{" "}
              {adminControls.token_budget_exceeded_minis
                .map((mini) => `@${mini.username}`)
                .join(", ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AccountTab() {
  const { user, logout } = useAuth();

  if (!user) return null;

  const githubLabel = user.github_username ? `@${user.github_username}` : "GitHub login unknown";
  const displayLabel = user.display_name || user.github_username || "Signed-in user";
  const avatarAlt = user.github_username ?? user.display_name ?? "User";
  const initials = displayLabel.slice(0, 2).toUpperCase();

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Avatar className="h-14 w-14">
          <AvatarImage
            src={user.avatar_url || undefined}
            alt={avatarAlt}
          />
          <AvatarFallback className="font-mono text-lg">
            {initials}
          </AvatarFallback>
        </Avatar>
        <div>
          <p className="text-base font-medium">
            {displayLabel}
          </p>
          <p className="font-mono text-sm text-muted-foreground">
            {githubLabel}
          </p>
        </div>
      </div>

      <div className="border-t border-border/50 pt-4">
        <Button
          variant="outline"
          size="sm"
          onClick={logout}
          className="gap-1.5 text-muted-foreground hover:text-destructive"
        >
          <LogOut className="h-3.5 w-3.5" />
          Sign Out
        </Button>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("api-keys");

  return (
    <AuthGate icon={Key} message="Log in with GitHub to access settings.">
    <div className="mx-auto max-w-2xl px-4 py-12">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage your API keys, model preferences, and account.
        </p>
      </div>

      <Card className="border-border/50">
        {/* Tab navigation */}
        <div className="flex border-b border-border/50 px-6">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-1.5 border-b-2 px-3 py-3 text-sm transition-colors",
                activeTab === tab.id
                  ? "border-chart-1 text-foreground font-medium"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              <tab.icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          ))}
        </div>

        <CardContent className="pt-6">
          {activeTab === "api-keys" && <ApiKeysTab />}
          {activeTab === "models" && <ModelTiersTab />}
          {activeTab === "usage" && <UsageTab />}
          {activeTab === "account" && <AccountTab />}
        </CardContent>
      </Card>
    </div>
    </AuthGate>
  );
}
