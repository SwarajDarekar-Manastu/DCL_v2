// Breadcrumb trail for the top bar, derived from the pathname so every page gets one without extra state.

import { findSection } from '$lib/components/settings/sections';

export interface Crumb {
	label: string;
	/** absent on the current page and on groupings without a page of their own */
	href?: string;
}

const SECTIONS: Record<string, string> = {
	review: 'Review',
	benchmark: 'Benchmark',
	entities: 'Entities',
	settings: 'Settings',
	ops: 'Ops',
	audit: 'Audit'
};

const shortId = (id: string) => (/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(id) ? id.slice(0, 8) : id);

export function breadcrumbs(pathname: string): Crumb[] {
	const parts = pathname.split('/').filter(Boolean).map(decodeURIComponent);
	if (parts.length === 0) return [{ label: 'Home' }];
	const [section, second, third] = parts;

	if (section === 'docs') return [{ label: 'Documents' }, { label: shortId(second ?? '') }, { label: 'Viewer' }];

	const root: Crumb = { label: SECTIONS[section] ?? section, href: `/${section}` };
	if (parts.length === 1) return [{ label: root.label }];

	if (section === 'review' && second === 'rules') return [root, { label: 'Rules' }];
	if (section === 'settings') return [root, { label: findSection(second)?.title ?? second }];
	if (section === 'benchmark') {
		if (second === 'suites') return [root, { label: 'Suites' }, { label: third ?? '' }];
		if (second === 'cases') return [root, { label: 'Cases' }, { label: third === 'new' ? 'New case' : (third ?? '') }];
		if (second === 'runs') return [root, { label: 'Runs' }, { label: shortId(third ?? '') }];
		if (second === 'compare') return [root, { label: 'Compare' }];
		if (second === 'retrieval') return [root, { label: 'Retrieval lab' }];
	}
	return [root, ...parts.slice(1, -1).map((p) => ({ label: p })), { label: parts[parts.length - 1] }];
}

/** The document title for a path: "Rules · Review · DCL Console". */
export function documentTitle(pathname: string): string {
	const trail = breadcrumbs(pathname)
		.map((c) => c.label)
		.reverse();
	return [...(trail[0] === 'Home' ? [] : trail), 'DCL Console'].join(' · ');
}
