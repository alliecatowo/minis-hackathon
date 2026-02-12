import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Globe,
  Bot,
  Radar,
  Users,
  Wrench,
  Download,
  Tags,
  Lock,
} from "lucide-react";

const features = [
  {
    icon: Globe,
    title: "Multi-Source Intelligence",
    description:
      "Not just GitHub. We pull from Stack Overflow, Hacker News, personal blogs, Dev.to \u2014 anywhere they leave a digital footprint.",
  },
  {
    icon: Bot,
    title: "Agentic Explorer Pipeline",
    description:
      "Each data source gets its own AI explorer agent running a ReAct loop \u2014 think, search, analyze, repeat \u2014 until it deeply understands the developer.",
  },
  {
    icon: Radar,
    title: "Personality Radar",
    description:
      "Quantified engineering values on a radar chart. See at a glance whether someone values correctness over speed, documentation over code, etc.",
  },
  {
    icon: Users,
    title: "Team Assembly",
    description:
      "Combine multiple minis into teams. Get parallel code reviews from different perspectives, or have them debate architecture decisions.",
  },
  {
    icon: Wrench,
    title: "MCP Tool Integration",
    description:
      "Use minis as tools in Claude Code. Ask Linus\u2019s opinion while you code. Get DHH\u2019s take on your Rails PR.",
  },
  {
    icon: Download,
    title: "Subagent Export",
    description:
      "Export any mini as a Claude Code agent definition. Drop it in .claude/agents/ and interact naturally from your terminal.",
  },
  {
    icon: Tags,
    title: "Roles, Skills & Traits",
    description:
      "AI-extracted metadata: primary role, secondary roles, technical skills, personality traits. Searchable and filterable.",
  },
  {
    icon: Lock,
    title: "Private Repos",
    coming_soon: true,
    description:
      "Connect your GitHub account to analyze private repository activity for more accurate personality clones.",
  },
];

export default function FeaturesPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-20">
      <div className="mb-16 text-center">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Features
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
          Everything you need to create, interact with, and deploy AI
          personality clones of any developer.
        </p>
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        {features.map((feature) => (
          <Card
            key={feature.title}
            className="border-border/50 transition-colors hover:border-border"
          >
            <CardHeader className="flex-row items-center gap-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-secondary">
                <feature.icon className="h-5 w-5 text-muted-foreground" />
              </div>
              <CardTitle className="text-base">
                {feature.title}
                {feature.coming_soon && (
                  <span className="ml-2 inline-block rounded-full bg-chart-1/20 px-2 py-0.5 text-[10px] font-medium text-chart-1">
                    Coming Soon
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                {feature.description}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
