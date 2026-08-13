/**
 * Shell do BrainfyOS Control.
 *
 * Deliberadamente separado do `ProtectedLayout` do workspace: o Control não
 * tem seletor de empresa, nem permissões de equipe, nem notificações de
 * tarefa — reaproveitar aquele layout significaria carregar tudo isso e depois
 * escondê-lo.
 *
 * O período fica aqui, no shell, porque é o filtro que todas as páginas
 * compartilham: trocá-lo na topbar não pode ressetar quando o operador navega
 * entre Contas e Consumo de IA.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Outlet } from 'react-router-dom';
import ControlSidebar from './ControlSidebar.tsx';
import ControlTopbar from './ControlTopbar.tsx';
import '../../styles/control.css';

const DEFAULT_PERIOD_DAYS = 30;
const PERIOD_STORAGE_KEY = 'brainfyos_control_period_days';
const VALID_PERIODS = [7, 30, 90];

interface ControlContextValue {
  periodDays: number;
  setPeriodDays: (days: number) => void;
  setTitle: (title: string) => void;
  setMeta: (meta: string | undefined) => void;
  alertCount: number | null;
  setAlertCount: (count: number | null) => void;
}

const ControlContext = createContext<ControlContextValue | null>(null);

export const useControl = (): ControlContextValue => {
  const context = useContext(ControlContext);
  if (!context) {
    throw new Error('useControl precisa estar dentro de ControlLayout');
  }
  return context;
};

/** Fixa o título da topbar enquanto a página estiver montada. */
export const useControlPage = (title: string): ControlContextValue => {
  const control = useControl();
  const { setTitle } = control;
  useEffect(() => {
    setTitle(title);
  }, [setTitle, title]);
  return control;
};

const readStoredPeriod = (): number => {
  if (typeof window === 'undefined') return DEFAULT_PERIOD_DAYS;
  const stored = Number(window.localStorage.getItem(PERIOD_STORAGE_KEY));
  return VALID_PERIODS.includes(stored) ? stored : DEFAULT_PERIOD_DAYS;
};

const ControlLayout: React.FC = () => {
  const [periodDays, setPeriodDaysState] = useState<number>(readStoredPeriod);
  const [title, setTitle] = useState('Visão geral');
  const [meta, setMeta] = useState<string | undefined>(undefined);
  const [alertCount, setAlertCount] = useState<number | null>(null);

  const setPeriodDays = useCallback((days: number) => {
    setPeriodDaysState(days);
    try {
      window.localStorage.setItem(PERIOD_STORAGE_KEY, String(days));
    } catch {
      // Modo privado bloqueia localStorage; o período apenas não persiste.
    }
  }, []);

  const value = useMemo<ControlContextValue>(
    () => ({ periodDays, setPeriodDays, setTitle, setMeta, alertCount, setAlertCount }),
    [alertCount, periodDays, setPeriodDays],
  );

  return (
    <ControlContext.Provider value={value}>
      <div className="ctl-scope">
        <div className="ctl-shell">
          <ControlSidebar alertCount={alertCount} />
          <div className="ctl-main">
            <ControlTopbar
              title={title}
              periodDays={periodDays}
              onPeriodChange={setPeriodDays}
              meta={meta}
            />
            <div className="ctl-content">
              <Outlet />
            </div>
          </div>
        </div>
      </div>
    </ControlContext.Provider>
  );
};

export default ControlLayout;
