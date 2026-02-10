"use client";

import type { Value } from "@/lib/api";

export function PersonalityRadar({ values }: { values: Value[] }) {
  if (!values || values.length === 0) return null;

  const top = values.slice(0, 6);
  const maxIntensity = Math.max(...top.map((v) => v.intensity), 1);
  const n = top.length;
  const size = 200;
  const cx = size / 2;
  const cy = size / 2;
  const radius = 80;

  // Generate points for the polygon
  const points = top.map((v, i) => {
    const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
    const r = (v.intensity / maxIntensity) * radius;
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
      labelX: cx + (radius + 24) * Math.cos(angle),
      labelY: cy + (radius + 24) * Math.sin(angle),
      name: v.name,
      intensity: v.intensity,
    };
  });

  const polygonPoints = points.map((p) => `${p.x},${p.y}`).join(" ");

  // Grid rings
  const rings = [0.25, 0.5, 0.75, 1];

  return (
    <div className="flex flex-col items-center">
      <svg viewBox={`0 0 ${size} ${size}`} className="w-full max-w-[200px]">
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
              className="text-border"
            />
          );
        })}

        {/* Axis lines */}
        {top.map((_, i) => {
          const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
          return (
            <line
              key={i}
              x1={cx}
              y1={cy}
              x2={cx + radius * Math.cos(angle)}
              y2={cy + radius * Math.sin(angle)}
              stroke="currentColor"
              strokeWidth="0.5"
              className="text-border"
            />
          );
        })}

        {/* Data polygon */}
        <polygon
          points={polygonPoints}
          fill="currentColor"
          fillOpacity="0.15"
          stroke="currentColor"
          strokeWidth="1.5"
          className="text-chart-1"
        />

        {/* Data points */}
        {points.map((p, i) => (
          <circle
            key={i}
            cx={p.x}
            cy={p.y}
            r="3"
            fill="currentColor"
            className="text-chart-1"
          />
        ))}

        {/* Labels */}
        {points.map((p, i) => (
          <text
            key={i}
            x={p.labelX}
            y={p.labelY}
            textAnchor="middle"
            dominantBaseline="middle"
            className="fill-muted-foreground text-[7px]"
          >
            {p.name.length > 12 ? p.name.slice(0, 11) + "..." : p.name}
          </text>
        ))}
      </svg>
    </div>
  );
}

export function PersonalityBars({ values }: { values: Value[] }) {
  if (!values || values.length === 0) return null;

  const top = values.slice(0, 6);
  const maxIntensity = Math.max(...top.map((v) => v.intensity), 1);

  return (
    <div className="space-y-2">
      {top.map((v) => (
        <div key={v.name} className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">{v.name}</span>
            <span className="font-mono text-[10px] text-muted-foreground/70">
              {Math.round((v.intensity / maxIntensity) * 100)}%
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
            <div
              className="h-full rounded-full bg-chart-1 transition-all duration-500"
              style={{
                width: `${(v.intensity / maxIntensity) * 100}%`,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
