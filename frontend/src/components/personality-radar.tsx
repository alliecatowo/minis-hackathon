"use client";

import { useState } from "react";
import type { Value } from "@/lib/api";

export function PersonalityRadar({ values }: { values: Value[] }) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  if (!values || values.length === 0) return null;

  const top = values.slice(0, 8);
  const maxIntensity = Math.max(...top.map((v) => v.intensity), 1);
  const n = top.length;
  const size = 240;
  const cx = size / 2;
  const cy = size / 2;
  const radius = 80;
  const labelRadius = radius + 28;

  // Generate points for the polygon
  const points = top.map((v, i) => {
    const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
    const r = (v.intensity / maxIntensity) * radius;
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
      angle,
    };
  });

  const polygonPoints = points.map((p) => `${p.x},${p.y}`).join(" ");

  // Grid rings
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
      <svg viewBox={`0 0 ${size} ${size}`} className="w-full max-w-[240px]">
        {/* Grid rings */}
        {rings.map((scale) => {
          const ringPoints = top
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
              opacity={0.3}
              className="text-muted-foreground"
            />
          );
        })}

        {/* Axis lines */}
        {points.map((p, i) => (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={p.axisEndX}
            y2={p.axisEndY}
            stroke="currentColor"
            strokeWidth="0.5"
            opacity={0.3}
            className="text-muted-foreground"
          />
        ))}

        {/* Data polygon - gradient fill */}
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
              fill="oklch(0.646 0.222 264.376)"
              className="transition-all duration-150"
            />
            {/* Halo on hover */}
            {hoveredIndex === i && (
              <circle
                cx={p.x}
                cy={p.y}
                r="7"
                fill="oklch(0.646 0.222 264.376)"
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
            className={`text-[8px] cursor-pointer transition-opacity duration-150 ${
              hoveredIndex === i
                ? "fill-foreground font-medium"
                : "fill-muted-foreground"
            }`}
            onMouseEnter={() => setHoveredIndex(i)}
            onMouseLeave={() => setHoveredIndex(null)}
          >
            {p.name.length > 14 ? p.name.slice(0, 13) + "..." : p.name}
            {p.description && <title>{p.name}: {p.description}</title>}
          </text>
        ))}
      </svg>

      {/* Tooltip */}
      {hoveredIndex !== null && points[hoveredIndex] && (
        <div className="mt-2 rounded-md bg-secondary px-3 py-2 text-center animate-slide-up">
          <p className="text-xs font-medium text-foreground">
            {points[hoveredIndex].name}
          </p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            {points[hoveredIndex].description}
          </p>
          <p className="mt-1 font-mono text-[10px] text-chart-1">
            {Math.round((points[hoveredIndex].intensity / maxIntensity) * 100)}% intensity
          </p>
        </div>
      )}
    </div>
  );
}

export function PersonalityBars({ values }: { values: Value[] }) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  if (!values || values.length === 0) return null;

  const top = values.slice(0, 8);
  const maxIntensity = Math.max(...top.map((v) => v.intensity), 1);

  return (
    <div className="space-y-3">
      {top.map((v, i) => (
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
              {Math.round((v.intensity / maxIntensity) * 100)}%
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
