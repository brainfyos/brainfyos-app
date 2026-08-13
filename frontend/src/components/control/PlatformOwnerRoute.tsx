/**
 * Guarda de rota do Control.
 *
 * Isto é conveniência de navegação, **não** segurança: quem chamar
 * `/api/control/*` sem o papel recebe 403 do backend independentemente do que
 * o React acredite. A verificação vai ao servidor (`/control/me`) em vez de
 * ler o localStorage justamente para que revogar o papel valha no próximo
 * carregamento, sem depender de logout.
 */

import React, { useEffect, useState } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { controlApi } from '../../services/controlApi.ts';
// O estado de verificação já usa a paleta do Control, então os tokens
// precisam existir antes do ControlLayout montar.
import '../../styles/control.css';

type Verdict = 'checking' | 'allowed' | 'denied';

const PlatformOwnerRoute: React.FC = () => {
  const [verdict, setVerdict] = useState<Verdict>('checking');

  useEffect(() => {
    let active = true;

    controlApi
      .getSession()
      .then((session) => {
        if (active) setVerdict(session.is_platform_owner ? 'allowed' : 'denied');
      })
      .catch(() => {
        if (active) setVerdict('denied');
      });

    return () => {
      active = false;
    };
  }, []);

  if (verdict === 'checking') {
    return (
      <div
        className="ctl-scope"
        style={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}
        aria-busy="true"
      >
        <span className="ctl-skeleton" style={{ width: 200, height: 12 }} />
      </div>
    );
  }

  if (verdict === 'denied') {
    return <Navigate to="/dashboard" replace />;
  }

  return <Outlet />;
};

export default PlatformOwnerRoute;
