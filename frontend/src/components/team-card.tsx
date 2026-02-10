"use client";

import Link from "next/link";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Users } from "lucide-react";

interface TeamSummary {
  id: number;
  name: string;
  description: string | null;
  member_count: number;
  owner_username: string;
}

export function TeamCard({ team }: { team: TeamSummary }) {
  return (
    <Link href={`/teams/${team.id}`}>
      <Card className="group cursor-pointer border-border/50 transition-all duration-200 hover:border-border hover:bg-card/80 hover:shadow-lg hover:shadow-black/5">
        <CardHeader className="flex-row items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-secondary">
            <Users className="h-5 w-5 text-muted-foreground" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-medium">
                {team.name}
              </span>
            </div>
            <p className="truncate font-mono text-xs text-muted-foreground">
              by @{team.owner_username}
            </p>
          </div>
        </CardHeader>
        <CardContent>
          <p className="line-clamp-2 text-sm text-muted-foreground">
            {team.description || "No description."}
          </p>
          <div className="mt-3 flex items-center gap-2">
            <Badge variant="outline" className="text-[10px]">
              <Users className="mr-1 h-3 w-3" />
              {team.member_count} {team.member_count === 1 ? "member" : "members"}
            </Badge>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
