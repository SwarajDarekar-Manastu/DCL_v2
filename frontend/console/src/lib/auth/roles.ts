// Console roles (file 08 §2.3). The server decides; the UI only hides what the server would refuse.

export type ConsoleRole = 'viewer' | 'reviewer' | 'admin';

const RANK: Record<ConsoleRole, number> = { viewer: 0, reviewer: 1, admin: 2 };

export function hasRole(roles: readonly string[], required: ConsoleRole): boolean {
	return roles.some((r) => r in RANK && RANK[r as ConsoleRole] >= RANK[required]);
}

export interface NavItem {
	href: string;
	label: string;
	role: ConsoleRole;
}

// Order and names follow the layout of file 08 §4.1.
export const NAV_ITEMS: NavItem[] = [
	{ href: '/review', label: 'Review', role: 'reviewer' },
	{ href: '/benchmark', label: 'Benchmark', role: 'viewer' },
	{ href: '/entities', label: 'Entities', role: 'viewer' },
	{ href: '/settings', label: 'Settings', role: 'admin' },
	{ href: '/ops', label: 'Ops', role: 'viewer' },
	{ href: '/audit', label: 'Audit', role: 'reviewer' }
];

export function visibleNav(roles: readonly string[]): NavItem[] {
	return NAV_ITEMS.filter((item) => hasRole(roles, item.role));
}
