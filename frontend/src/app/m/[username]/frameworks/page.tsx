"use client";

/**
 * /m/[username]/frameworks — Owner-only frameworks-at-risk dashboard.
 *
 * Active-learning loop: surfaces decision frameworks with low confidence,
 * declining trends, or no validation so the mini owner can review, correct,
 * or retire them.
 *
 * Access: owner-only — non-owners are redirected to the mini profile page.
 */

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, AlertTriangle, TrendingDown, FileQuestion } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import {
  getMiniByUsername,
  getFrameworksAtRisk,
  retireFramework,
  type AtRiskFramework,
  type AtRiskReason,
  type Mini,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function reasonBadge(reason: AtRiskReason) {
  switch (reason) {
    case "low_band":
      return (
        <Badge variant="destructive" className="text-xs">
          LOW CONFIDENCE
        </Badge>
      );
    case "declining_trend":
      return (
        <Badge variant="destructive" className="text-xs bg-orange-600">
          DECLINING
        </Badge>
      );
    case "low_evidence":
      return (
        <Badge variant="secondary" className="text-xs">
          NO EVIDENCE
        </Badge>
      );
  }
}

function reasonDescription(reason: AtRiskReason): string {
  switch (reason) {
    case "low_band":
      return "Confidence below 0.3 — framework predictions are unreliable.";
    case "declining_trend":
      return "Consecutive negative outcome deltas — framework is degrading.";
    case "low_evidence":
      return "Never validated against real review outcomes (revision = 0).";
  }
}

function confidenceColor(confidence: number): string {
  if (confidence < 0.3) return "text-red-500";
  if (confidence >= 0.7) return "text-green-600";
  return "text-yellow-500";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function FrameworksAtRiskPage() {
  const params = useParams();
  const router = useRouter();
  const username = params.username as string;
  const { user, loading: authLoading } = useAuth();

  const [mini, setMini] = useState<Mini | null>(null);
  const [frameworks, setFrameworks] = useState<AtRiskFramework[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retiring, setRetiring] = useState<string | null>(null);
  const [retired, setRetired] = useState<Set<string>>(new Set());

  // Load mini and check ownership
  useEffect(() => {
    if (authLoading) return;

    async function load() {
      try {
        const m = await getMiniByUsername(username);
        setMini(m);

        // Redirect non-owners
        if (!user || user.id !== m.owner_id) {
          router.replace(`/m/${username}`);
          return;
        }

        const at_risk = await getFrameworksAtRisk(m.id);
        setFrameworks(at_risk);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load frameworks");
      } finally {
        setLoading(false);
      }
    }

    load();
  }, [username, user, authLoading, router]);

  const handleRetire = useCallback(
    async (frameworkId: string) => {
      if (!mini) return;
      setRetiring(frameworkId);
      try {
        await retireFramework(mini.id, frameworkId);
        setRetired((prev) => new Set([...prev, frameworkId]));
      } catch (err) {
        alert(err instanceof Error ? err.message : "Failed to retire framework");
      } finally {
        setRetiring(null);
      }
    },
    [mini],
  );

  // ---------------------------------------------------------------------------
  // Render states
  // ---------------------------------------------------------------------------

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-background p-6">
        <div className="max-w-3xl mx-auto space-y-4">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-background p-6">
        <div className="max-w-3xl mx-auto">
          <p className="text-destructive">{error}</p>
          <Button variant="outline" asChild className="mt-4">
            <Link href={`/m/${username}`}>
              <ChevronLeft className="mr-2 h-4 w-4" />
              Back to profile
            </Link>
          </Button>
        </div>
      </div>
    );
  }

  const visible = frameworks.filter((fw) => !retired.has(fw.framework_id));

  return (
    <div className="min-h-screen bg-background p-6">
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link href={`/m/${username}`}>
              <ChevronLeft className="mr-1 h-4 w-4" />
              {username}
            </Link>
          </Button>
        </div>

        <div>
          <h1 className="text-2xl font-bold">Frameworks at Risk</h1>
          <p className="text-muted-foreground text-sm mt-1">
            These decision frameworks need your review. Correct, ignore, or retire
            frameworks to keep predictions sharp.
          </p>
        </div>

        {/* Legend */}
        <div className="flex flex-wrap gap-4 text-xs text-muted-foreground border rounded-lg p-3 bg-muted/30">
          <span className="flex items-center gap-1">
            <AlertTriangle className="h-3 w-3 text-red-500" />
            <strong>LOW CONFIDENCE</strong> — confidence &lt; 0.3
          </span>
          <span className="flex items-center gap-1">
            <TrendingDown className="h-3 w-3 text-orange-500" />
            <strong>DECLINING</strong> — 3+ negative outcome deltas
          </span>
          <span className="flex items-center gap-1">
            <FileQuestion className="h-3 w-3 text-muted-foreground" />
            <strong>NO EVIDENCE</strong> — never validated, mini is mature
          </span>
        </div>

        {/* Framework cards */}
        {visible.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground">
              No frameworks at risk right now. Keep generating review predictions to
              build confidence.
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4">
            {visible.map((fw) => (
              <Card key={fw.framework_id} className="border-l-4 border-l-destructive/40">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="text-sm font-medium text-foreground/80 leading-relaxed">
                      {fw.condition || fw.framework_id}
                    </CardTitle>
                    <div className="flex items-center gap-2 shrink-0">
                      {reasonBadge(fw.reason)}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {/* Action / Value */}
                  {(fw.action || fw.value) && (
                    <div className="text-sm space-y-0.5">
                      {fw.action && (
                        <p>
                          <span className="text-muted-foreground font-medium">Action: </span>
                          {fw.action}
                        </p>
                      )}
                      {fw.value && (
                        <p>
                          <span className="text-muted-foreground font-medium">Value: </span>
                          {fw.value}
                        </p>
                      )}
                    </div>
                  )}

                  {/* Confidence + trend */}
                  <div className="flex flex-wrap items-center gap-4 text-sm">
                    <span>
                      <span className="text-muted-foreground">Confidence: </span>
                      <span className={`font-mono font-semibold ${confidenceColor(fw.confidence)}`}>
                        {(fw.confidence * 100).toFixed(0)}%
                      </span>
                    </span>
                    <span>
                      <span className="text-muted-foreground">Revisions: </span>
                      <span className="font-mono">{fw.revision}</span>
                    </span>
                    {fw.trend_summary && (
                      <span className="text-orange-500 font-mono text-xs">
                        {fw.trend_summary}
                      </span>
                    )}
                  </div>

                  {/* Reason description */}
                  <p className="text-xs text-muted-foreground italic">
                    {reasonDescription(fw.reason)}
                  </p>

                  {/* Retire button */}
                  <div className="flex justify-end pt-1">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={retiring === fw.framework_id}
                      onClick={() => handleRetire(fw.framework_id)}
                    >
                      {retiring === fw.framework_id ? "Retiring..." : "Retire"}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Retired count notice */}
        {retired.size > 0 && (
          <p className="text-xs text-muted-foreground text-center">
            {retired.size} framework{retired.size !== 1 ? "s" : ""} retired this session.
            They will no longer appear in review predictions or the system prompt.
          </p>
        )}
      </div>
    </div>
  );
}
