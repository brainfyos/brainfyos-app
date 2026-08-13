import React from 'react';
import { PeriodPicker } from './ControlPrimitives.tsx';

interface ControlTopbarProps {
  title: string;
  periodDays: number;
  onPeriodChange: (days: number) => void;
  /** Ex.: "Atualizado às 14:32". Fica discreto, à direita. */
  meta?: string;
  actions?: React.ReactNode;
}

const ControlTopbar: React.FC<ControlTopbarProps> = ({
  title,
  periodDays,
  onPeriodChange,
  meta,
  actions,
}) => (
  <header className="ctl-topbar">
    <span className="ctl-topbar-title">{title}</span>
    <span className="ctl-topbar-spacer" />
    {meta && <span className="ctl-topbar-meta">{meta}</span>}
    {actions}
    <PeriodPicker value={periodDays} onChange={onPeriodChange} />
  </header>
);

export default ControlTopbar;
