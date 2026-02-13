"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Check } from "lucide-react";

const tiers = [
  {
    name: "Free",
    price: "$0",
    period: "/month",
    description: "Get started with public data",
    features: [
      "5 minis",
      "Public data only",
      "Community gallery",
      "Basic radar chart",
    ],
    cta: "Get Started",
    href: "/",
    highlighted: false,
    comingSoon: false,
  },
  {
    name: "Team",
    price: "$19",
    period: "/month",
    description: "For teams building with minis",
    features: [
      "25 minis",
      "Organization teams",
      "Private repo analysis",
      "Slack integration",
      "Priority processing",
    ],
    cta: "Coming Soon",
    href: "#",
    highlighted: true,
    comingSoon: true,
  },
  {
    name: "Enterprise",
    price: "Custom",
    period: "",
    description: "For large-scale deployments",
    features: [
      "Unlimited minis",
      "SSO / SAML",
      "Self-hosted option",
      "Dedicated support",
      "Custom integrations",
    ],
    cta: "Contact Us",
    href: "/",
    highlighted: false,
    comingSoon: false,
  },
];

const faqs = [
  {
    question: "How accurate are the personality clones?",
    answer:
      "Accuracy depends on the developer's public footprint. More activity = more accurate clone. The more they've written, the better we capture their decision-making style.",
  },
  {
    question: "Can I use minis commercially?",
    answer:
      "Yes, all paid plans include commercial usage rights.",
  },
  {
    question: "What's the difference between a mini and a generic AI assistant?",
    answer:
      "A mini captures the specific combination of a person's decisions, expertise, values, and experiences. It's not about intelligence—it's about predicting what *that specific person* would say.",
  },
];

export default function PricingPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-20">
      <div className="mb-16 text-center">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Pricing
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
          Start free. Scale when you need to.
        </p>
      </div>

      <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-3">
        {tiers.map((tier) => (
          <Card
            key={tier.name}
            className={
              tier.highlighted
                ? "relative border-chart-1/50 shadow-lg shadow-chart-1/5"
                : "border-border/50"
            }
          >
            {tier.highlighted && (
              <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                <Badge className="bg-chart-1 text-white">Popular</Badge>
              </div>
            )}
            <CardHeader>
              <CardTitle className="text-lg">
                {tier.name}
                {tier.comingSoon && (
                  <span className="ml-2 inline-block rounded-full bg-chart-1/20 px-2 py-0.5 text-[10px] font-medium text-chart-1">
                    Coming Soon
                  </span>
                )}
              </CardTitle>
              <CardDescription>{tier.description}</CardDescription>
              <div className="pt-2">
                <span className="text-3xl font-bold">{tier.price}</span>
                {tier.period && (
                  <span className="text-sm text-muted-foreground">
                    {tier.period}
                  </span>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <ul className="space-y-3">
                {tier.features.map((feature) => (
                  <li key={feature} className="flex items-center gap-2 text-sm">
                    <Check className="h-4 w-4 shrink-0 text-chart-2" />
                    <span className="text-muted-foreground">{feature}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
            <CardFooter>
              <Button
                asChild
                variant={tier.highlighted ? "default" : "outline"}
                className="w-full"
                disabled={tier.comingSoon}
              >
                <Link href={tier.href}>{tier.cta}</Link>
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>

      <div className="mx-auto mt-24 max-w-2xl">
        <h2 className="mb-8 text-center text-2xl font-bold tracking-tight">
          Frequently Asked Questions
        </h2>
        <div className="space-y-6">
          {faqs.map((faq) => (
            <div key={faq.question}>
              <h3 className="font-medium">{faq.question}</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {faq.answer}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
