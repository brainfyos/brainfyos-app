/**
 * Gráfico temporal de consumo de IA.
 *
 * Recharts já é dependência do projeto (usado no Dashboard do workspace);
 * nenhuma biblioteca nova entra por causa do Control.
 *
 * As cores vêm dos tokens via `getComputedStyle` porque o SVG do Recharts não
 * aceita `var()` em todas as props — resolvemos uma vez, no mount, em vez de
 * espalhar hex pelo componente.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { UsagePoint } from '../../services/controlApi.ts';
import { EmptyState, formatCompact, formatCurrency } from './ControlPrimitives.tsx';

export type UsageMetric = 'cost_brl' | 'total_tokens' | 'events';

const METRIC_LABEL: Record<UsageMetric, string> = {
  cost_brl: 'Custo estimado',
  total_tokens: 'Tokens',
  events: 'Eventos',
};

interface Palette {
  accent: string;
  grid: string;
  axis: string;
  surface: string;
  border: string;
  text: string;
}

const FALLBACK_PALETTE: Palette = {
  accent: '#3b82f6',
  grid: 'rgba(255,255,255,0.06)',
  axis: '#6f778c',
  surface: '#0e1118',
  border: 'rgba(255,255,255,0.11)',
  text: '#e7eaf2',
};

const readPalette = (element: HTMLElement | null): Palette => {
  if (!element || typeof window === 'undefined') return FALLBACK_PALETTE;
  const computed = window.getComputedStyle(element);
  const token = (name: string, fallback: string) => computed.getPropertyValue(name).trim() || fallback;
  return {
    accent: token('--ctl-accent', FALLBACK_PALETTE.accent),
    grid: token('--ctl-border', FALLBACK_PALETTE.grid),
    axis: token('--ctl-text-muted', FALLBACK_PALETTE.axis),
    surface: token('--ctl-surface-raised', FALLBACK_PALETTE.surface),
    border: token('--ctl-border-strong', FALLBACK_PALETTE.border),
    text: token('--ctl-text', FALLBACK_PALETTE.text),
  };
};

interface UsageChartProps {
  data: UsagePoint[];
  metric: UsageMetric;
  height?: number;
}

const UsageChart: React.FC<UsageChartProps> = ({ data, metric, height = 220 }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [palette, setPalette] = useState<Palette>(FALLBACK_PALETTE);

  useEffect(() => {
    setPalette(readPalette(containerRef.current));
  }, []);

  const chartData = useMemo(
    () =>
      data.map((point) => ({
        ...point,
        label: new Date(`${point.date}T00:00:00`).toLocaleDateString('pt-BR', {
          day: '2-digit',
          month: '2-digit',
        }),
      })),
    [data],
  );

  const hasSignal = chartData.some((point) => Number(point[metric]) > 0);

  const formatValue = (value: number) =>
    metric === 'cost_brl' ? formatCurrency(value) : formatCompact(value);

  if (!hasSignal) {
    return (
      <div ref={containerRef}>
        <EmptyState
          title="Nenhum consumo no período"
          description="Assim que os agentes processarem mensagens, a evolução aparece aqui."
        />
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="ctlUsageFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={palette.accent} stopOpacity={0.28} />
              <stop offset="100%" stopColor={palette.accent} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={palette.grid} vertical={false} />
          <XAxis
            dataKey="label"
            stroke={palette.axis}
            tick={{ fontSize: 11, fill: palette.axis }}
            tickLine={false}
            axisLine={false}
            minTickGap={24}
          />
          <YAxis
            stroke={palette.axis}
            tick={{ fontSize: 11, fill: palette.axis }}
            tickLine={false}
            axisLine={false}
            width={56}
            tickFormatter={(value: number) => formatCompact(value)}
          />
          <Tooltip
            contentStyle={{
              background: palette.surface,
              border: `1px solid ${palette.border}`,
              borderRadius: 10,
              fontSize: 12,
              color: palette.text,
            }}
            labelStyle={{ color: palette.axis, fontSize: 11 }}
            formatter={(value: number) => [formatValue(value), METRIC_LABEL[metric]]}
          />
          <Area
            type="monotone"
            dataKey={metric}
            stroke={palette.accent}
            strokeWidth={1.75}
            fill="url(#ctlUsageFill)"
            dot={false}
            activeDot={{ r: 3, strokeWidth: 0 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};

export default UsageChart;
