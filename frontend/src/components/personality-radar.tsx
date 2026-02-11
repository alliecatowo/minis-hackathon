"use client";

import { useState } from "react";
import type { Value } from "@/lib/api";

// Standardized trait order matching backend TRAIT_DEFINITIONS.
// The radar chart draws traits in this order around the circle.
const TRAIT_ORDER = [
  "Collaboration",
  "Mentoring",
  "Directness",
  "Humor",
  "Systems",
  "Web",
  "DevOps",
  "AI/ML",
  "Code Quality",
  "Pragmatism",
  "Open Source",
  "Breadth",
];

// Category grouping for trait display
const TRAIT_CATEGORIES: Record<string, string[]> = {
  Personality: ["Collaboration", "Mentoring", "Directness", "Humor"],
  Coding: ["Systems", "Web", "DevOps", "AI/ML"],
  Engineering: ["Code Quality", "Pragmatism", "Open Source", "Breadth"],
};

// Category colors (oklch values for consistency with design system)
const CATEGORY_COLORS: Record<string, string> = {
  Personality: "oklch(0.696 0.17 162.48)",  // teal/green
  Coding: "oklch(0.646 0.222 264.376)",     // blue/purple
  Engineering: "oklch(0.705 0.213 47.604)", // orange/amber
};

function sortByTraitOrder(values: Value[]): Value[] {
  const byName = new Map(values.map((v) => [v.name, v]));
  const ordered: Value[] = [];
  for (const name of TRAIT_ORDER) {
    const v = byName.get(name);
    if (v) ordered.push(v);
  }
  // Append any that didn't match the standard order
  for (const v of values) {
    if (!TRAIT_ORDER.includes(v.name)) ordered.push(v);
  }
  return ordered;
}

function getCategoryForTrait(name: string): string {
  for (const [cat, traits] of Object.entries(TRAIT_CATEGORIES)) {
    if (traits.includes(name)) return cat;
  }
  return "Other";
}

export function PersonalityRadar({ values }: { values: Value[] }) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  if (!values || values.length === 0) return null;

  const sorted = sortByTraitOrder(values);
  const n = sorted.length;
  // Fixed max of 10 for standardized traits (0-10 scale)
  const maxIntensity = 10;
  const size = 260;
  const cx = size / 2;
  const cy = size / 2;
  const radius = 85;
  const labelRadius = radius + 30;

  // Generate points for the polygon
  const points = sorted.map((v, i) => {
    const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
    const r = (v.intensity / maxIntensity) * radius;
    const category = getCategoryForTrait(v.name);
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
      labelX: cx + labelRadius * Math.cos(angle),
      labelY: cy + labelRadius * Math.sin(angle),
      axisEndX: cx + radius * Math.cos(angle),
      axisEndY: cy + radius * Math.sin(angle),
      name: v.name,
      description: v.description,
      intensity: v.intensity,
      category,
      color: CATEGORY_COLORS[category] || CATEGORY_COLORS.Coding,
      angle,
    };
  });

  const polygonPoints = points.map((p) => `${p.x},${p.y}`).join(" ");

  // Grid rings at 2.5, 5.0, 7.5, 10.0
  const rings = [0.25, 0.5, 0.75, 1];

  // Determine text-anchor based on angle
  const getTextAnchor = (angle: number) => {
    const deg = ((angle + Math.PI / 2) * 180) / Math.PI;
    const normalized = ((deg % 360) + 360) % 360;
    if (normalized > 45 && normalized < 135) return "start";
    if (normalized > 225 && normalized < 315) return "end";
    return "middle";
  };

  return (
    <div className="flex flex-col items-center">
      <svg viewBox={`0 0 ${size} ${size}`} className="w-full max-w-[260px]">
        {/* Grid rings */}
        {rings.map((scale) => {
          const ringPoints = sorted
            .map((_, i) => {
              const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
              const r = scale * radius;
              return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
            })
            .join(" ");
          return (
            <polygon
              key={scale}
              points={ringPoints}
              fill="none"
              stroke="currentColor"
              strokeWidth="0.5"
              opacity={0.2}
              className="text-muted-foreground"
            />
          );
        })}

        {/* Axis lines — colored by category */}
        {points.map((p, i) => (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={p.axisEndX}
            y2={p.axisEndY}
            stroke={p.color}
            strokeWidth="0.5"
            opacity={0.35}
          />
        ))}

        {/* Data polygon — gradient fill */}
        <defs>
          <linearGradient id="radar-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="oklch(0.646 0.222 264.376)" stopOpacity="0.25" />
            <stop offset="100%" stopColor="oklch(0.696 0.17 162.48)" stopOpacity="0.15" />
          </linearGradient>
        </defs>
        <polygon
          points={polygonPoints}
          fill="url(#radar-gradient)"
          stroke="oklch(0.646 0.222 264.376)"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />

        {/* Data points */}
        {points.map((p, i) => (
          <g key={i}>
            {/* Hover target (larger invisible circle) */}
            <circle
              cx={p.x}
              cy={p.y}
              r="10"
              fill="transparent"
              className="cursor-pointer"
              onMouseEnter={() => setHoveredIndex(i)}
              onMouseLeave={() => setHoveredIndex(null)}
            />
            {/* Visible dot */}
            <circle
              cx={p.x}
              cy={p.y}
              r={hoveredIndex === i ? "4.5" : "3"}
              fill={p.color}
              className="transition-all duration-150"
            />
            {/* Halo on hover */}
            {hoveredIndex === i && (
              <circle
                cx={p.x}
                cy={p.y}
                r="7"
                fill={p.color}
                opacity="0.15"
              />
            )}
          </g>
        ))}

        {/* Labels */}
        {points.map((p, i) => (
          <text
            key={i}
            x={p.labelX}
            y={p.labelY}
            textAnchor={getTextAnchor(p.angle)}
            dominantBaseline="middle"
            className={`text-[7px] cursor-pointer transition-opacity duration-150 ${
              hoveredIndex === i
                ? "fill-foreground font-medium"
                : "fill-muted-foreground"
            }`}
            onMouseEnter={() => setHoveredIndex(i)}
            onMouseLeave={() => setHoveredIndex(null)}
          >
            {p.name.length > 12 ? p.name.slice(0, 11) + "..." : p.name}
            {p.description && <title>{p.name}: {p.description}</title>}
          </text>
        ))}
      </svg>

      {/* Tooltip */}
      {hoveredIndex !== null && points[hoveredIndex] && (
        <div className="mt-2 rounded-md bg-secondary px-3 py-2 text-center animate-slide-up">
          <p className="text-[10px] text-muted-foreground/60">
            {points[hoveredIndex].category}
          </p>
          <p className="text-xs font-medium text-foreground">
            {points[hoveredIndex].name}
          </p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            {points[hoveredIndex].description}
          </p>
          <p className="mt-1 font-mono text-[10px] text-chart-1">
            {points[hoveredIndex].intensity}/10
          </p>
        </div>
      )}

      {/* Legend */}
      <div className="mt-3 flex flex-wrap justify-center gap-x-3 gap-y-1">
        {Object.entries(CATEGORY_COLORS).map(([cat, color]) => (
          <div key={cat} className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span className="text-[9px] text-muted-foreground">{cat}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PersonalityBars({ values }: { values: Value[] }) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  if (!values || values.length === 0) return null;

  const maxIntensity = 10;

  return (
    <div className="space-y-3">
      {values.map((v, i) => (
        <div
          key={v.name}
          className="space-y-1"
          onMouseEnter={() => setHoveredIndex(i)}
          onMouseLeave={() => setHoveredIndex(null)}
        >
          <div className="flex items-center justify-between">
            <span className={`text-xs transition-colors ${hoveredIndex === i ? "text-foreground" : "text-muted-foreground"}`}>
              {v.name}
            </span>
            <span className="font-mono text-[10px] text-muted-foreground/70">
              {v.intensity}/10
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
            <div
              className="h-full rounded-full bg-gradient-to-r from-chart-1 to-chart-2 transition-all duration-500"
              style={{
                width: `${(v.intensity / maxIntensity) * 100}%`,
              }}
            />
          </div>
          {hoveredIndex === i && v.description && (
            <p className="text-[10px] text-muted-foreground/70 animate-slide-up">
              {v.description}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

export function TraitGroups({ values }: { values: Value[] }) {
  if (!values || values.length === 0) return null;

  const byName = new Map(values.map((v) => [v.name, v]));
  const maxIntensity = 10;

  return (
    <div className="space-y-4">
      {Object.entries(TRAIT_CATEGORIES).map(([category, traitNames]) => {
        const traits = traitNames
          .map((name) => byName.get(name))
          .filter((v): v is Value => v !== undefined);
        if (traits.length === 0) return null;

        const color = CATEGORY_COLORS[category] || CATEGORY_COLORS.Coding;

        return (
          <div key={category}>
            <div className="mb-2 flex items-center gap-1.5">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: color }}
              />
              <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {category}
              </span>
            </div>
            <div className="space-y-1.5">
              {traits.map((v) => (
                <div key={v.name} className="flex items-center gap-2">
                  <span className="w-20 shrink-0 truncate text-[11px] text-muted-foreground" title={v.description}>
                    {v.name}
                  </span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-secondary">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${(v.intensity / maxIntensity) * 100}%`,
                        backgroundColor: color,
                        opacity: 0.7,
                      }}
                    />
                  </div>
                  <span className="w-6 shrink-0 text-right font-mono text-[10px] text-muted-foreground/70">
                    {v.intensity}
                  </span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
