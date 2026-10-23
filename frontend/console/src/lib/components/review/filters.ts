// Queue filters live in the URL (?severity=HARD&sort=impact&case=…) so a view can be shared and reloaded.

import type { CaseFilters } from '$lib/api_endpoint';

const KEYS = ['severity', 'flag_type', 'route', 'root_name', 'test_plan_id', 'assignee', 'status', 'has_suggestion', 'older_than_days', 'proposed_by_rule_id', 'q', 'sort'] as const;

export function filtersFromUrl(params: URLSearchParams): CaseFilters {
	const filters: Record<string, unknown> = {};
	for (const key of KEYS) {
		const value = params.get(key);
		if (value === null || value === '') continue;
		if (key === 'has_suggestion') filters[key] = value === 'true';
		else if (key === 'older_than_days') filters[key] = Number(value);
		else filters[key] = value;
	}
	return filters as CaseFilters;
}

export function urlFor(filters: CaseFilters, caseKey: string | null): string {
	const params = new URLSearchParams();
	for (const key of KEYS) {
		const value = filters[key];
		if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
	}
	if (caseKey) params.set('case', caseKey);
	const text = params.toString();
	return text ? `/review?${text}` : '/review';
}
