// Audit filters live in the URL so a case's history can be linked (?entity_id=<case_key>&entity_id=<flag>…).

import type { AuditFilters, AuditItem } from '$lib/api_endpoint';
import { caseHref } from './format';

export function auditFiltersFromUrl(params: URLSearchParams): AuditFilters {
	const filters: AuditFilters = {};
	const type = params.get('entity_type');
	if (type) filters.entity_type = type as AuditFilters['entity_type'];
	const ids = params.getAll('entity_id').filter(Boolean);
	if (ids.length) filters.entity_id = ids;
	for (const key of ['actor', 'action', 'since', 'until'] as const) {
		const value = params.get(key);
		if (value) filters[key] = value;
	}
	return filters;
}

export function auditUrl(filters: AuditFilters): string {
	const params = new URLSearchParams();
	if (filters.entity_type) params.set('entity_type', filters.entity_type);
	for (const id of filters.entity_id ?? []) params.append('entity_id', id);
	for (const key of ['actor', 'action', 'since', 'until'] as const) {
		const value = filters[key];
		if (value) params.set(key, value);
	}
	const text = params.toString();
	return text ? `/audit?${text}` : '/audit';
}

/** One file's decisions and the means to correct them (the Audit page for a case). */
export const decisionsHref = (caseKey: string): string => `/audit/case/${encodeURIComponent(caseKey)}`;

/** Where an audit entry's entity can be opened in the Console, if anywhere. */
export function entityHref(item: Pick<AuditItem, 'entity_type' | 'entity_id'>): string | null {
	if (item.entity_type === 'case') return caseHref(item.entity_id);
	if (item.entity_type === 'rule') return '/review/rules';
	if (item.entity_type === 'document') return `/docs/${encodeURIComponent(item.entity_id)}/viewer`;
	return null;
}

/** Keys whose value differs between before and after (top level), for a compact change summary. */
export function changedKeys(before: Record<string, unknown> | null, after: Record<string, unknown> | null): string[] {
	const keys = new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})]);
	return [...keys].filter((k) => JSON.stringify(before?.[k]) !== JSON.stringify(after?.[k])).sort();
}
