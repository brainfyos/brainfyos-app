import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  ArrowLeft,
  Bell,
  Building2,
  Cpu,
  LayoutDashboard,
  Plug,
} from 'lucide-react';
import { branding } from '../../config/branding.ts';

export interface ControlNavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  end?: boolean;
}

export const CONTROL_NAV: ControlNavItem[] = [
  { to: '/control', label: 'Visão geral', icon: LayoutDashboard, end: true },
  { to: '/control/accounts', label: 'Contas', icon: Building2 },
  { to: '/control/ai', label: 'Consumo de IA', icon: Cpu },
  { to: '/control/integrations', label: 'Integrações', icon: Plug },
  { to: '/control/alerts', label: 'Alertas', icon: Bell },
];

interface ControlSidebarProps {
  /** Contagem de alertas abertos, exibida ao lado do item. */
  alertCount?: number | null;
}

const ControlSidebar: React.FC<ControlSidebarProps> = ({ alertCount }) => (
  <aside className="ctl-sidebar" aria-label="Navegação do Control">
    <div className="ctl-sidebar-header">
      <img className="ctl-sidebar-mark" src={branding.assets.icon} alt="" aria-hidden />
      <span className="ctl-sidebar-title">
        <strong>{branding.appName}</strong>
        <span>Control</span>
      </span>
    </div>

    <nav className="ctl-sidebar-nav">
      <span className="ctl-nav-label">Plataforma</span>
      {/* NavLink marca aria-current="page" sozinho quando a rota casa, e o
          estilo ativo pendura nesse atributo — nada de className condicional. */}
      {CONTROL_NAV.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink key={item.to} to={item.to} end={item.end} className="ctl-nav-item">
            <Icon aria-hidden />
            <span>{item.label}</span>
            {item.to === '/control/alerts' && alertCount ? (
              <span className="ctl-nav-count">{alertCount}</span>
            ) : null}
          </NavLink>
        );
      })}
    </nav>

    <div className="ctl-sidebar-footer">
      <NavLink to="/dashboard" className="ctl-nav-item">
        <ArrowLeft aria-hidden />
        <span>Voltar ao workspace</span>
      </NavLink>
    </div>
  </aside>
);

export default ControlSidebar;
