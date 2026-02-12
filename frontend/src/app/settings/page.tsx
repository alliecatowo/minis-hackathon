"use client";

import { useEffect, useState, useCallback } from "react";
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
  getAvailableModels,
  type UserSettings,
  type UsageInfo,
  type ModelInfo,
} from "@/lib/api";
import { cn } from "@/lib/utils";
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
} from "lucide-react";

type Tab = "api-keys" | "usage" | "account";

const TABS: { id: Tab; label: string; icon: typeof Key }[] = [
  { id: "api-keys", label: "API Keys", icon: Key },
  { id: "usage", label: "Usage", icon: BarChart3 },
  { id: "account", label: "Account", icon: User },
];

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

  useEffect(() => {
    Promise.all([getSettings(), getAvailableModels()])
      .then(([s, m]) => {
        setSettings(s);
        setModels(m);
        setProvider(s.llm_provider || "gemini");
        setModel(s.preferred_model || null);
      })
      .catch(() => setError("Failed to load settings"))
      .finally(() => setLoading(false));
  }, []);

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
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      setError("Failed to save settings");
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

function UsageTab() {
  const [usage, setUsage] = useState<UsageInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getUsage()
      .then(setUsage)
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
    </div>
  );
}

function AccountTab() {
  const { user, logout } = useAuth();

  if (!user) return null;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Avatar className="h-14 w-14">
          <AvatarImage
            src={user.avatar_url || undefined}
            alt={user.github_username}
          />
          <AvatarFallback className="font-mono text-lg">
            {user.github_username.slice(0, 2).toUpperCase()}
          </AvatarFallback>
        </Avatar>
        <div>
          <p className="text-base font-medium">
            {user.display_name || user.github_username}
          </p>
          <p className="font-mono text-sm text-muted-foreground">
            @{user.github_username}
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
  const { user, loading: authLoading, login } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>("api-keys");

  if (authLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Skeleton className="h-8 w-48" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-secondary">
          <Key className="h-7 w-7 text-muted-foreground" />
        </div>
        <div className="text-center">
          <p className="font-medium text-foreground">Sign in required</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Log in with GitHub to access settings.
          </p>
        </div>
        <Button onClick={login} size="sm" className="mt-2">
          Sign In
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-12">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage your API keys, usage, and account.
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
          {activeTab === "usage" && <UsageTab />}
          {activeTab === "account" && <AccountTab />}
        </CardContent>
      </Card>
    </div>
  );
}
