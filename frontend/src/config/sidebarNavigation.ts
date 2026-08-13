/**
 * Navegação do workspace BrainfyOS.
 *
 * A estrutura conceitual é INÍCIO / OPERAÇÃO / CRESCIMENTO / INTELIGÊNCIA /
 * IA E AUTOMAÇÃO / GESTÃO. Nem todo grupo existe hoje: INTELIGÊNCIA (Brain,
 * Resultados, Insights) não tem nenhuma página construída, então o grupo
 * simplesmente não aparece — nada de tela falsa com dado inventado.
 *
 * Um grupo sem item visível é filtrado no ProtectedLayout, então adicionar o
 * primeiro item real de INTELIGÊNCIA faz o grupo surgir sozinho.
 *
 * Nenhuma rota existente foi removida nesta reorganização; algumas apenas
 * mudaram de grupo.
 */

import {
  BarChart3,
  Bot,
  Brain,
  Building2,
  Calendar,
  ClipboardCheck,
  Compass,
  CreditCard,
  GitMerge,
  KeyRound,
  LayoutDashboard,
  Megaphone,
  MessageSquare,
  Package,
  Plug,
  Receipt,
  Rocket,
  Share2,
  Users,
  UserRound,
  Webhook,
  Workflow,
  type LucideIcon,
} from 'lucide-react';
import WhatsAppIcon from '../components/icons/WhatsAppIcon.tsx';
import type { MenuItem, Permission, SubItem } from '../services/permissionService.ts';

export type ModuleKey =
  | 'inicio'
  | 'operacao'
  | 'crescimento'
  | 'inteligencia'
  | 'ia'
  | 'gestao';

export interface ModuleMeta {
  label: string;
  description: string;
}

export interface SidebarPermissionItem {
  depth: number;
  icon?: LucideIcon;
  isBeta?: boolean;
  isNew?: boolean;
  label: string;
  moduleKey: ModuleKey;
  moduleLabel: string;
  parentLabel?: string;
  path: string;
  type: 'menu' | 'submenu';
}

export interface SidebarPermissionGroup {
  icon: LucideIcon;
  items: SidebarPermissionItem[];
  key: Permission;
  label: string;
  moduleLabels: string[];
}

export const MODULE_META: Record<ModuleKey, ModuleMeta> = {
  inicio: {
    label: 'Início',
    description: 'Visão geral e primeiros passos',
  },
  operacao: {
    label: 'Operação',
    description: 'Atendimento, pipeline, contatos e agenda',
  },
  crescimento: {
    label: 'Crescimento',
    description: 'Campanhas e aquisição',
  },
  inteligencia: {
    label: 'Inteligência',
    description: 'Brain, resultados e insights',
  },
  ia: {
    label: 'IA e Automação',
    description: 'Agentes e automações',
  },
  gestao: {
    label: 'Gestão',
    description: 'Clientes, conexões e configurações',
  },
};

/** Ordem em que os grupos aparecem na sidebar. */
export const MODULE_ORDER: ModuleKey[] = [
  'inicio',
  'operacao',
  'crescimento',
  'inteligencia',
  'ia',
  'gestao',
];

export const MODULE_ICON: Record<ModuleKey, LucideIcon> = {
  inicio: LayoutDashboard,
  operacao: MessageSquare,
  crescimento: Megaphone,
  inteligencia: Brain,
  ia: Bot,
  gestao: Building2,
};

export const SIDEBAR_MODULE_MENUS: Record<ModuleKey, MenuItem[]> = {
  inicio: [
    { path: '/dashboard', label: 'Visão Geral', icon: LayoutDashboard, permission: 'dashboard' },
    { path: '/getting_started', label: 'Começar', icon: Rocket, permission: 'dashboard', isNew: true },
  ],

  operacao: [
    { path: '/chat', label: 'Atendimento', icon: MessageSquare, permission: 'chat' },
    {
      path: '/crm',
      label: 'Pipeline',
      icon: Workflow,
      permission: 'crm',
      subItems: [
        { path: '/crm', label: 'Board', permission: 'crm' },
        { path: '/tags', label: 'Filtros & Tags', permission: 'crm' },
      ],
    },
    { path: '/contacts', label: 'Contatos', icon: Users, permission: 'crm' },
    { path: '/calendar-config', label: 'Agenda', icon: Calendar, permission: 'company' },
  ],

  // Marketing, Funis, Anúncios e Conteúdo ainda não existem. Campanhas existe
  // e é aquisição, então mantém o grupo com conteúdo real.
  crescimento: [
    {
      path: '/campaigns',
      label: 'Campanhas',
      icon: Megaphone,
      permission: 'company',
      subItems: [
        { path: '/campaigns/whatsapp', label: 'WhatsApp', icon: WhatsAppIcon, permission: 'company', isNew: true },
        { path: '/prompt/indicacoes', label: 'Indicações', icon: Share2, permission: 'company' },
      ],
    },
  ],

  // Brain existe desde a Fase 2. Resultados e Insights continuam ocultos até
  // terem página real — o grupo aparece com o que já funciona.
  inteligencia: [
    { path: '/brain', label: 'Brain', icon: Brain, permission: 'company', isNew: true },
  ],

  ia: [
    { path: '/agents', label: 'Agentes', icon: Brain, permission: 'prompt', isNew: true },
    { path: '/flows', label: 'Automações', icon: GitMerge, permission: 'prompt', isNew: true },
  ],

  gestao: [
    {
      path: '/customers',
      label: 'Clientes',
      icon: Users,
      permission: 'crm',
      // Um workspace gerenciado não administra a carteira de quem o criou.
      hiddenForManagedWorkspace: true,
      subItems: [
        { path: '/customers', label: 'Carteira', icon: Users, permission: 'crm' },
        { path: '/customers/invoices', label: 'Faturas', icon: Receipt, permission: 'crm' },
        { path: '/customers/plans', label: 'Planos', icon: Package, permission: 'crm' },
        { path: '/customers/revenue', label: 'Receita & Churn', icon: CreditCard, permission: 'crm' },
      ],
    },
    {
      path: '/integrations',
      label: 'Conexões',
      icon: Plug,
      permission: 'company',
      subItems: [
        { path: '/whatsapp', label: 'WhatsApp', icon: WhatsAppIcon, permission: 'whatsapp' },
        { path: '/integrations', label: 'Integrações', icon: Plug, permission: 'company' },
        { path: '/config/midias', label: 'Canais & Origens', icon: Share2, permission: 'company' },
        { path: '/webhooks', label: 'Webhooks', icon: Webhook, isBeta: true, permission: 'prompt' },
      ],
    },
    {
      path: '/company',
      label: 'Configurações',
      icon: Building2,
      permission: 'company',
      subItems: [
        { path: '/company', label: 'Minha Empresa', icon: Building2, permission: 'company' },
        { path: '/account/profile', label: 'Perfil da conta', icon: UserRound, permission: 'company' },
        { path: '/company/ai-provider', label: 'Provedor de IA', icon: KeyRound, permission: 'company' },
        { path: '/company/custom-fields', label: 'Campos Personalizados', icon: ClipboardCheck, permission: 'company' },
        { path: '/company/controle-fluxos', label: 'Controle de Fluxos', icon: BarChart3, permission: 'company' },
      ],
    },
  ],
};

const PERMISSION_META: Record<Permission, { icon: LucideIcon; label: string }> = {
  dashboard: { icon: LayoutDashboard, label: 'Dashboard' },
  crm: { icon: Users, label: 'CRM' },
  chat: { icon: MessageSquare, label: 'Chat ao vivo' },
  whatsapp: { icon: WhatsAppIcon, label: 'WhatsApp' },
  'follow-up': { icon: ClipboardCheck, label: 'Follow-up' },
  prompt: { icon: Brain, label: 'Agentes e automações' },
  company: { icon: Compass, label: 'Configurações e gestão' },
};

const collectSubItems = (
  subItems: SubItem[] | undefined,
  moduleKey: ModuleKey,
  parentLabel: string,
  depth: number,
  groups: Map<Permission, SidebarPermissionGroup>,
) => {
  subItems?.forEach((subItem) => {
    if (subItem.permission) {
      addPermissionItem(groups, subItem.permission, {
        depth,
        icon: subItem.icon,
        isBeta: subItem.isBeta,
        isNew: subItem.isNew,
        label: subItem.label,
        moduleKey,
        moduleLabel: MODULE_META[moduleKey].label,
        parentLabel,
        path: subItem.path,
        type: 'submenu',
      });
    }

    collectSubItems(subItem.subItems, moduleKey, subItem.label, depth + 1, groups);
  });
};

const addPermissionItem = (
  groups: Map<Permission, SidebarPermissionGroup>,
  permission: Permission,
  item: SidebarPermissionItem,
) => {
  const meta = PERMISSION_META[permission];
  const current = groups.get(permission) || {
    icon: meta.icon,
    items: [],
    key: permission,
    label: meta.label,
    moduleLabels: [],
  };

  const itemKey = `${item.type}:${item.moduleKey}:${item.parentLabel || ''}:${item.path}:${item.label}`;
  const alreadyAdded = current.items.some(existing =>
    `${existing.type}:${existing.moduleKey}:${existing.parentLabel || ''}:${existing.path}:${existing.label}` === itemKey
  );

  if (!alreadyAdded) {
    current.items.push(item);
  }

  if (!current.moduleLabels.includes(item.moduleLabel)) {
    current.moduleLabels.push(item.moduleLabel);
  }

  groups.set(permission, current);
};

export const getSidebarPermissionGroups = (): SidebarPermissionGroup[] => {
  const groups = new Map<Permission, SidebarPermissionGroup>();

  Object.entries(SIDEBAR_MODULE_MENUS).forEach(([moduleKey, menuItems]) => {
    const typedModuleKey = moduleKey as ModuleKey;

    menuItems.forEach((item) => {
      if (item.permission) {
        addPermissionItem(groups, item.permission, {
          depth: 0,
          icon: item.icon,
          isBeta: item.isBeta,
          isNew: item.isNew,
          label: item.label,
          moduleKey: typedModuleKey,
          moduleLabel: MODULE_META[typedModuleKey].label,
          path: item.path,
          type: 'menu',
        });
      }

      collectSubItems(item.subItems, typedModuleKey, item.label, 1, groups);
    });
  });

  return Array.from(groups.values());
};

export const resolveActiveModule = (pathname: string): ModuleKey => {
  if (pathname.startsWith('/dashboard') || pathname.startsWith('/getting_started')) return 'inicio';

  if (
    pathname.startsWith('/chat') ||
    pathname.startsWith('/crm') ||
    pathname.startsWith('/contacts') ||
    pathname.startsWith('/tags') ||
    pathname.startsWith('/calendar')
  ) {
    return 'operacao';
  }

  if (pathname.startsWith('/campaigns') || pathname.startsWith('/prompt/indicacoes')) return 'crescimento';

  if (pathname.startsWith('/brain')) return 'inteligencia';

  if (pathname.startsWith('/agents') || pathname.startsWith('/flows') || pathname.startsWith('/prompt')) {
    return 'ia';
  }

  if (
    pathname.startsWith('/customers') ||
    pathname.startsWith('/whatsapp') ||
    pathname.startsWith('/integrations') ||
    pathname.startsWith('/webhooks') ||
    pathname.startsWith('/config') ||
    pathname.startsWith('/company') ||
    pathname.startsWith('/account')
  ) {
    return 'gestao';
  }

  return 'inicio';
};
