import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Users,
  MessageSquare,
  MessageCircle,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Check,
  Loader2,
  Headphones,
  Stethoscope,
  Shield,
  Handshake,
  Bell,
  Clock,
  Sun,
  Moon,
  LogOut,
  Apple,
  Target,
  RefreshCw,
  Bot,
  Layers,
  Database,
  BellRing,
  MoreVertical,
  User,
  HelpCircle,
  Tag,
  History,
  type LucideIcon
} from 'lucide-react';

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './ui/dropdown-menu';
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from './ui/avatar';

import {
  getCompanyInfo,
  getCurrentTeamPermissions,
  getUserCompanies,
  selectActiveCompany,
  getPendingNotifications,
  type TaskNotification,
  type UserCompany
} from '../services/api';
import { useUserPermissions } from '../hooks/useUserPermissions.ts';
import { filterMenusByPermissions, type MenuItem, type SubItem } from '../services/permissionService.ts';
import {
  MODULE_ICON,
  MODULE_META,
  MODULE_ORDER,
  SIDEBAR_MODULE_MENUS,
  resolveActiveModule,
  type ModuleKey,
} from '../config/sidebarNavigation.ts';
import { controlApi } from '../services/controlApi.ts';
import LogoutConfirmModal from './LogoutConfirmModal.tsx';
import AllTasksModal from './AllTasksModal.tsx';
import { unifiedWebSocketManager } from '../services/api.ts';
import { useTheme } from '../contexts/ThemeContext.tsx';
import WhatsAppIcon from './icons/WhatsAppIcon.tsx';
import { AgentiveConfirmModal } from './AgentiveUI.tsx';


import Sidebar from './Sidebar/Sidebar';
import MobileNav from './MobileNav/MobileNav';
import { getInitials } from './WorkspaceAccountNav/WorkspaceAccountNav';

type CompanyListItem = UserCompany;

// Main Component
const ProtectedLayout: React.FC = () => {
  const location = useLocation();
  const { toggleTheme, isDark } = useTheme();
  const [showLogoutModal, setShowLogoutModal] = useState(false);
  const [layoutError, setLayoutError] = useState<string | null>(null);

  // Navigation State
  const [activeModule, setActiveModule] = useState<ModuleKey>('inicio');
  // Só quem tem o papel de plataforma enxerga a entrada do Control. Isso é
  // navegação, não autorização — o backend recusa /api/control/* de qualquer
  // conta sem o papel, independentemente do que o React exiba.
  const [isPlatformOwner, setIsPlatformOwner] = useState(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState(true);
  // Nenhum submenu aberto por padrão: o efeito abaixo abre o que contém a
  // rota ativa assim que a navegação resolve.
  const [openSubmenu, setOpenSubmenu] = useState<string | null>(null);
  const [openNestedSubmenu, setOpenNestedSubmenu] = useState<string | null>(null);

  // Data State
  const [companyName, setCompanyName] = useState<string | null>(null);
  const [companyLogoUrl, setCompanyLogoUrl] = useState<string | null>(null);
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [userCompanies, setUserCompanies] = useState<CompanyListItem[]>([]);
  const [websocketMessage, setWebsocketMessage] = useState<any>(null);

  const permissions = useUserPermissions();

  // Load Initial Data
  useEffect(() => {
    const refreshCurrentPermissions = async () => {
      try {
        const permissionsPayload = await getCurrentTeamPermissions();
        localStorage.setItem('sidebar_permissions', JSON.stringify(permissionsPayload.sidebar_permissions || []));
        localStorage.setItem('contact_permissions', JSON.stringify(permissionsPayload.contact_permissions || {}));
        if (permissionsPayload.team) {
          localStorage.setItem('user_team_data', JSON.stringify(permissionsPayload.team));
          localStorage.setItem('user_team', permissionsPayload.team.code);
        } else {
          localStorage.removeItem('user_team_data');
          localStorage.removeItem('user_team');
        }
        window.dispatchEvent(new CustomEvent('userPermissionsChanged'));
      } catch (error) {
        console.error("Falha ao atualizar permissões do usuário", error);
      }
    };

    const loadCompanies = async () => {
      try {
        const companies = await getUserCompanies();
        setUserCompanies(companies);
      } catch (e) {
        console.error("Falha ao carregar lista de empresas", e);
      }
    };
    const resolvePlatformRole = async () => {
      try {
        const session = await controlApi.getSession();
        setIsPlatformOwner(session.is_platform_owner);
      } catch {
        // Conta sem papel, sessão expirada ou backend antigo: sem Control.
        setIsPlatformOwner(false);
      }
    };

    refreshCurrentPermissions();
    loadCompanies();
    resolvePlatformRole();
  }, []);

  useEffect(() => {
    const storedCompanyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));
    if (storedCompanyId) {
      setCompanyId(storedCompanyId);
    }

    const fetchCompanyInfo = async () => {
      try {
        const info = await getCompanyInfo();
        const finalName = info.name_company?.trim() || info.name?.trim() || null;
        const finalLogo = info.logo_url?.trim() || null;

        setCompanyName(finalName);
        setCompanyLogoUrl(finalLogo);
      } catch (error) {
        console.error("Erro ao obter informações da Empresa:", error);
        setCompanyName(null);
        setCompanyLogoUrl(null);
      }
    };

    const fetchInitialNotifications = async () => {
      try {
        const notifications = await getPendingNotifications();
        if (notifications && notifications.type !== 'none') {
          console.log('[ProtectedLayout] Notificações iniciais encontradas:', notifications);
          setWebsocketMessage(notifications);
        }
      } catch (error) {
        console.error("Erro ao buscar notificações iniciais:", error);
      }
    };

    fetchCompanyInfo();
    fetchInitialNotifications();
  }, []);

  // WebSocket
  useEffect(() => {
    unifiedWebSocketManager.connect();

    const unsubscribeGlobal = unifiedWebSocketManager.onMessage('__global__', (data) => {
      if (data.type === 'task_reminder' || data.type === 'overdue_tasks') {
        setWebsocketMessage(data);
      }
    });

    const unsubscribeAll = unifiedWebSocketManager.onMessage('*', (data) => {
      if (data.type === 'task_reminder' || data.type === 'overdue_tasks') {
        setWebsocketMessage(data);
      }
    });

    const handleReconnect = () => {
      console.log('WebSocket reconectado');
      if (!unifiedWebSocketManager.isConnected()) {
        unifiedWebSocketManager.connect();
      }
    };

    window.addEventListener('websocket:reconnected', handleReconnect);

    return () => {
      unsubscribeGlobal();
      unsubscribeAll();
      window.removeEventListener('websocket:reconnected', handleReconnect);
    };
  }, []);

  const handleSelectCompany = async (selectedId: number) => {
    try {
      await selectActiveCompany(selectedId);
      const id = selectedId.toString();
      localStorage.setItem('company_id', id);
      localStorage.setItem('clinic_id', id);
      setCompanyId(selectedId.toString());
      window.location.reload();
    } catch (error) {
      console.error("Erro ao selecionar Empresa:", error);
      setLayoutError("Não foi possível selecionar a empresa.");
    }
  };


  useEffect(() => {
    setActiveModule(resolveActiveModule(location.pathname));
  }, [location.pathname]);

  const workspaceName = companyName || 'Minha Empresa';
  const workspaceInitials = getInitials(workspaceName);
  const userEmail = localStorage.getItem('user_email') || 'usuario@exemplo.com';
  const activeCompany = companyId
    ? userCompanies.find((company) => company.company_id.toString() === companyId)
    : undefined;
  const isManagedCustomerWorkspace = Boolean(activeCompany?.managed_link_id || activeCompany?.managed_customer_id);
  const navigationModule = activeModule;
  const sidebarModuleMenus = useMemo(() => (
    MODULE_ORDER.reduce((menus, moduleKey) => {
      const allowed = filterMenusByPermissions(SIDEBAR_MODULE_MENUS[moduleKey] || []);
      menus[moduleKey] = isManagedCustomerWorkspace
        ? allowed.filter((item) => !item.hiddenForManagedWorkspace)
        : allowed;
      return menus;
    }, {} as Record<ModuleKey, MenuItem[]>)
  ), [permissions, isManagedCustomerWorkspace]);
  const currentMenuItems = sidebarModuleMenus[navigationModule] || [];

  const allMobileMenuItems = [
    {
      path: '/dashboard',
      icon: LayoutDashboard,
      label: 'Dash',
      permission: 'dashboard'
    },
    {
      path: '/chat',
      icon: MessageSquare,
      label: 'Chat',
      permission: 'chat'
    },
    {
      path: '/crm',
      icon: Users,
      label: 'CRM',
      permission: 'crm'
    },
    {
      path: '/whatsapp',
      icon: WhatsAppIcon,
      label: 'Whats',
      permission: 'whatsapp',
    },
  ];

  // Um grupo sem item visível não aparece. É assim que INTELIGÊNCIA (Brain,
  // Resultados, Insights) fica escondido até existir a primeira página real —
  // e é assim que ele volta sozinho quando ela existir.
  const railItems = MODULE_ORDER.map((moduleKey) => ({
    icon: MODULE_ICON[moduleKey],
    label: MODULE_META[moduleKey].label,
    moduleKey,
    hidden: (sidebarModuleMenus[moduleKey] || []).length === 0,
  }));

  const isMobilePathActive = (path: string) => {
    if (path === '/crm') {
      return ['/crm', '/contacts', '/tags'].some((crmPath) =>
        location.pathname === crmPath || location.pathname.startsWith(`${crmPath}/`)
      );
    }

    return location.pathname === path || (path !== '/dashboard' && location.pathname.startsWith(path));
  };

  const mobileMenuItems = allMobileMenuItems.filter(item => {
    if (!item.permission) return true;
    return permissions.hasPermission(item.permission as any);
  }).map(item => ({
    ...item,
    isActive: isMobilePathActive(item.path)
  }));
  const isDrawerPathActive = (path: string, peerPaths: string[] = []) => {
    if (path === '/dashboard') return location.pathname === path;
    if (path === '/company') return location.pathname === '/company' || location.pathname === '/clinic';
    const isActive = location.pathname === path || location.pathname.startsWith(`${path}/`);
    if (!isActive) return false;
    return !peerPaths.some(peerPath =>
      peerPath !== path &&
      peerPath.startsWith(`${path}/`) &&
      (location.pathname === peerPath || location.pathname.startsWith(`${peerPath}/`))
    );
  };
  const isMenuEntryActive = (entry: MenuItem | SubItem, peerPaths: string[] = []): boolean => {
    const childPaths = entry.subItems?.map(subItem => subItem.path) || [];
    return isDrawerPathActive(entry.path, peerPaths) || Boolean(entry.subItems?.some(subItem => isMenuEntryActive(subItem, childPaths)));
  };
  const getActiveSubmenuPath = (items: MenuItem[]) => {
    const activeItem = items.find(item => {
      const childPaths = item.subItems?.map(subItem => subItem.path) || [];
      return item.subItems?.some(subItem => isMenuEntryActive(subItem, childPaths));
    });
    return activeItem?.path || null;
  };

  useEffect(() => {
    const activeSubmenuPath = getActiveSubmenuPath(currentMenuItems);
    if (activeSubmenuPath) {
      setOpenSubmenu(activeSubmenuPath);
    }
  }, [navigationModule, location.pathname]);

  const sidebarWidth = isDrawerOpen ? 240 : 72;

  return (
    <div className="agentive-app-shell flex flex-col">

      {/* DESKTOP NAVIGATION */}
      <div className="flex flex-1 relative hidden sm:flex">
      <Sidebar
        isCollapsed={!isDrawerOpen}
        navigationModule={navigationModule}
        onToggleCollapse={() => setIsDrawerOpen((current) => !current)}
        setActiveModule={setActiveModule}
        isManagedCustomerWorkspace={isManagedCustomerWorkspace}
        isDark={isDark}
        moduleMenus={sidebarModuleMenus}
        openSubmenu={openSubmenu}
        setOpenSubmenu={setOpenSubmenu}
        isMenuEntryActive={isMenuEntryActive}
        isDrawerPathActive={isDrawerPathActive}
        websocketMessage={websocketMessage}
        companyId={companyId}
        companyLogoUrl={companyLogoUrl}
        userCompanies={userCompanies}
        setShowLogoutModal={setShowLogoutModal}
        handleSelectCompany={handleSelectCompany}
        toggleTheme={toggleTheme}
        userEmail={userEmail}
        workspaceInitials={workspaceInitials}
        workspaceName={workspaceName}
        railItems={railItems}
        showControlLink={isPlatformOwner}
      />

        {/* 3. MAIN CONTENT AREA */}
        <main
          className={`
            agentive-app-main min-h-screen transition-all duration-200
            p-0
          `}
          style={{ marginLeft: `${sidebarWidth}px`, width: `calc(100% - ${sidebarWidth}px)` }}
        >
          <Outlet />
        </main>

      </div>

      {/* MOBILE NAVIGATION */}
      <div className="sm:hidden flex flex-col min-h-screen">
        <main className="agentive-mobile-main flex-1 overflow-y-auto pb-[calc(7rem+env(safe-area-inset-bottom))]">
          <Outlet />
        </main>
        <MobileNav
          menuItems={mobileMenuItems}
          onLogout={() => setShowLogoutModal(true)}
        />
      </div>

      {/* Logout Modal */}
      <LogoutConfirmModal
        isOpen={showLogoutModal}
        onClose={() => setShowLogoutModal(false)}
        onConfirm={() => setShowLogoutModal(false)}
      />
      <AgentiveConfirmModal
        cancelText="Fechar"
        confirmText="Tentar novamente"
        isOpen={Boolean(layoutError)}
        message={layoutError || ''}
        onClose={() => setLayoutError(null)}
        onConfirm={() => {
          setLayoutError(null);
          window.location.reload();
        }}
        title="Erro na operação"
        variant="info"
      />
    </div>
  );
};

export default ProtectedLayout;
