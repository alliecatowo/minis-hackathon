"use client";

import Link from "next/link";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { Mini } from "@/lib/api";

const statusColors: Record<Mini["status"], string> = {
  pending: "bg-yellow-500/20 text-yellow-400",
  processing: "bg-blue-500/20 text-blue-400",
  ready: "bg-emerald-500/20 text-emerald-400",
  failed: "bg-red-500/20 text-red-400",
};

export function MiniCard({ mini }: { mini: Mini }) {
  return (
    <Link href={mini.status === "ready" ? `/m/${mini.username}` : `/create?username=${mini.username}`}>
      <Card className="group cursor-pointer border-border/50 transition-all duration-200 hover:border-border hover:bg-card/80 hover:shadow-lg hover:shadow-black/5">
        <CardHeader className="flex-row items-center gap-3">
          <Avatar className="h-10 w-10">
            <AvatarImage src={mini.avatar_url} alt={mini.username} />
            <AvatarFallback className="font-mono text-xs">
              {mini.username.slice(0, 2).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate font-mono text-sm font-medium">
                {mini.display_name || mini.username}
              </span>
              <Badge
                variant="secondary"
                className={`shrink-0 text-[10px] ${statusColors[mini.status]}`}
              >
                {mini.status}
              </Badge>
            </div>
            <p className="truncate font-mono text-xs text-muted-foreground">
              @{mini.username}
            </p>
          </div>
        </CardHeader>
        <CardContent>
          <p className="line-clamp-2 text-sm text-muted-foreground">
            {mini.bio || "No bio yet."}
          </p>
          {mini.values && mini.values.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {mini.values.slice(0, 3).map((v) => (
                <Badge key={v.name} variant="outline" className="text-[10px]">
                  {v.name}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
