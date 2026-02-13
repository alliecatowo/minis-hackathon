import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Rocket,
  Users,
  Zap,
  Globe,
  Bot,
  Sparkles,
  MessageSquare,
  GitBranch,
} from "lucide-react";

const roadmap = [
  {
    phase: "Now",
    icon: Rocket,
    items: [
      {
        title: "Multi-source analysis",
        description: "GitHub, Stack Overflow, Hacker News, blogs, and more",
        status: "live",
      },
      {
        title: "Agentic explorer pipeline",
        description: "ReAct agents that mine personality from each data source",
        status: "live",
      },
      {
        title: "Team assembly",
        description: "Combine minis for parallel reviews and debates",
        status: "live",
      },
      {
        title: "Claude Code integration",
        description: "MCP server and agent definitions for terminal workflows",
        status: "live",
      },
    ],
  },
  {
    phase: "Next",
    icon: Zap,
    items: [
      {
        title: "Slack integration",
        description: "@mention any mini in Slack channels for instant feedback",
        status: "in-progress",
      },
      {
        title: "GitHub PR reviews",
        description: "Install the GitHub App and get automatic reviews from your team's minis",
        status: "in-progress",
      },
      {
        title: "Private repo analysis",
        description: "Connect GitHub for deeper personality capture",
        status: "planned",
      },
    ],
  },
  {
    phase: "Soon",
    icon: Globe,
    items: [
      {
        title: "Multi-agent teams",
        description: "20 versions of your team working across agents on different features",
        status: "planned",
      },
      {
        title: "Task delegation",
        description: "Assign tasks to minis and they'll handle it in their style",
        status: "planned",
      },
      {
        title: "Learning mode",
        description: "Minis that improve as you give them feedback",
        status: "planned",
      },
    ],
  },
  {
    phase: "Future",
    icon: Sparkles,
    items: [
      {
        title: "Organization knowledge base",
        description: "Your entire team's collective expertise, searchable",
        status: "envisioned",
      },
      {
        title: "Cross-team collaboration",
        description: "Minis from different teams working together",
        status: "envisioned",
      },
      {
        title: "Autonomous agents",
        description: "Minis that can take action, not just give advice",
        status: "envisioned",
      },
    ],
  },
];

const vision = [
  {
    icon: Users,
    title: "Dev Velocity, Exponentially",
    description:
      "Request a review from your busy senior and predict what they'll say—without bothering them. Ship faster with instant feedback loops.",
  },
  {
    icon: MessageSquare,
    title: "@mention Anyone",
    description:
      "@alliecatowo in Slack, GitHub, or your terminal. Talk to the mini version of any teammate instantly.",
  },
  {
    icon: Bot,
    title: "Not Smarter AI. Specific AI.",
    description:
      "The value isn't in how smart an AI is. It's in capturing the specific combination of decisions, expertise, values, and experiences that make each person unique.",
  },
  {
    icon: GitBranch,
    title: "Parallel Team Clones",
    description:
      "Imagine 20 versions of your team all collaborating across agents, working on different features simultaneously. That's the future.",
  },
];

export default function RoadmapPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-20">
      <div className="mb-16 text-center">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Roadmap
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
          Where we&apos;re headed. No dates, just direction.
        </p>
      </div>

      {/* Vision */}
      <section className="mb-20">
        <h2 className="mb-8 text-center text-2xl font-bold tracking-tight">
          The Vision
        </h2>
        <div className="grid gap-6 sm:grid-cols-2">
          {vision.map((item) => (
            <Card key={item.title} className="border-border/50">
              <CardHeader className="flex-row items-center gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-r from-chart-1 to-chart-2">
                  <item.icon className="h-5 w-5 text-white" />
                </div>
                <CardTitle className="text-base">{item.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  {item.description}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Roadmap */}
      <section>
        {roadmap.map((phase) => (
          <div key={phase.phase} className="mb-12">
            <div className="mb-6 flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary">
                <phase.icon className="h-4 w-4 text-muted-foreground" />
              </div>
              <h3 className="text-xl font-bold">{phase.phase}</h3>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {phase.items.map((item) => (
                <Card key={item.title} className="border-border/50">
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-sm">{item.title}</CardTitle>
                      <Badge
                        variant="outline"
                        className={
                          item.status === "live"
                            ? "border-chart-2 text-chart-2"
                            : item.status === "in-progress"
                              ? "border-chart-1 text-chart-1"
                              : "border-muted-foreground/50 text-muted-foreground"
                        }
                      >
                        {item.status === "live"
                          ? "Live"
                          : item.status === "in-progress"
                            ? "In Progress"
                            : item.status === "planned"
                              ? "Planned"
                              : "Envisioned"}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-xs text-muted-foreground">
                      {item.description}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
