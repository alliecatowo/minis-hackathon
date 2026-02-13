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
  Zap,
  MessageSquare,
} from "lucide-react";

const features = [
  {
    icon: Zap,
    title: "Predict Before Asking",
    description:
      "Request a review from your busy senior and predict what they'll say—without bothering them. Dev velocity, exponentially.",
  },
  {
    icon: Bot,
    title: "Agentic Explorer Pipeline",
    description:
      "Each data source gets its own AI explorer agent running a ReAct loop — think, search, analyze, repeat — until it deeply understands the developer.",
  },
  {
    icon: Users,
    title: "Team Assembly",
    description:
      "Combine multiple minis into teams. Get Linus and DHH to debate your architecture. Different perspectives, same conversation.",
  },
  {
    icon: Wrench,
    title: "Claude Code Integration",
    description:
      "@alliecatowo in your terminal. Talk to minis while you code. MCP server and agent definitions for native workflows.",
  },
  {
    icon: MessageSquare,
    title: "Slack & GitHub",
    coming_soon: true,
    description:
      "@mention any mini in Slack or GitHub PRs. Instant feedback in the tools you already use.",
  },
  {
    icon: Globe,
    title: "Multi-Source Intelligence",
    description:
      "Not just GitHub. We pull from Stack Overflow, Hacker News, personal blogs, Dev.to — anywhere they leave a digital footprint.",
  },
  {
    icon: Radar,
    title: "Personality Radar",
    description:
      "Quantified engineering values on a radar chart. See at a glance whether someone values correctness over speed, documentation over code, etc.",
  },
  {
    icon: Tags,
    title: "Roles, Skills & Traits",
    description:
      "AI-extracted metadata: primary role, secondary roles, technical skills, personality traits. Searchable and filterable.",
  },
];

const whyMinis = [
  {
    title: "Not Smarter AI. Specific AI.",
    description:
      "The value isn't in raw intelligence. It's in capturing the specific combination of decisions, expertise, values, and past experiences that make each developer unique on your team.",
  },
  {
    title: "How Teams Actually Work",
    description:
      "Teams succeed because of the specific roles people play, their decision-making patterns, their accumulated context. Minis captures that.",
  },
  {
    title: "Delegate Without Blocking",
    description:
      "Need feedback from someone who's in back-to-back meetings? Ask their mini. Get the same perspective, zero wait time.",
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

      {/* Why Minis */}
      <section className="mb-16">
        <div className="mx-auto max-w-3xl">
          <div className="grid gap-6">
            {whyMinis.map((item) => (
              <Card key={item.title} className="border-border/50">
                <CardHeader>
                  <CardTitle className="text-lg">{item.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-muted-foreground">
                    {item.description}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

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
