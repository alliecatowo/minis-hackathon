"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CheckCircle2, XCircle, ArrowLeft } from "lucide-react";

export default function JoinOrgPage() {
  const params = useParams();
  const router = useRouter();
  const code = params.code as string;

  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [orgId, setOrgId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;

    import("@/lib/api").then(({ joinOrg }) =>
      joinOrg(code)
        .then((result) => {
          setOrgId(result.org_id ?? result.id);
          setStatus("success");
        })
        .catch((err) => {
          setErrorMsg(err instanceof Error ? err.message : "Failed to join organization");
          setStatus("error");
        })
    );
  }, [code]);

  if (status === "loading") {
    return (
      <div className="mx-auto max-w-lg px-4 py-12">
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4">
          <Skeleton className="h-16 w-16 rounded-full" />
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-4 w-32" />
        </div>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="mx-auto max-w-lg px-4 py-12">
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
            <XCircle className="h-8 w-8 text-destructive" />
          </div>
          <div className="text-center">
            <p className="font-medium text-foreground">Unable to join</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {errorMsg}
            </p>
          </div>
          <Link href="/orgs">
            <Button variant="outline" className="mt-2 gap-1.5">
              <ArrowLeft className="h-3.5 w-3.5" />
              Go to Organizations
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg px-4 py-12">
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-green-500/10">
          <CheckCircle2 className="h-8 w-8 text-green-500" />
        </div>
        <div className="text-center">
          <p className="font-medium text-foreground">You&apos;re in!</p>
          <p className="mt-1 text-sm text-muted-foreground">
            You have successfully joined the organization.
          </p>
        </div>
        <Button
          className="mt-2"
          onClick={() => router.push(orgId ? `/orgs/${orgId}` : "/orgs")}
        >
          Go to Organization
        </Button>
      </div>
    </div>
  );
}
