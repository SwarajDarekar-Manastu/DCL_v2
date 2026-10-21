// Display helpers shared by the Review UI.

import type { CaseSummary, FlagType } from '$lib/api_endpoint';

/** Whole working days (Mon–Fri) between two instants. */
export function workingDaysBetween(from: Date, to: Date): number {
	let days = 0;
	const cursor = new Date(Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), from.getUTCDate()));
	const end = Date.UTC(to.getUTCFullYear(), to.getUTCMonth(), to.getUTCDate());
	while (cursor.getTime() < end) {
		cursor.setUTCDate(cursor.getUTCDate() + 1);
		const weekday = cursor.getUTCDay();
		if (weekday !== 0 && weekday !== 6) days += 1;
	}
	return days;
}

/** File 06 §9: HARD cases older than 3 working days are highlighted. */
export const AGING_WORKING_DAYS = 3;

export function isAging(item: Pick<CaseSummary, 'max_severity' | 'oldest_created_at'>, now = new Date()): boolean {
	return item.max_severity === 'HARD' && workingDaysBetween(new Date(item.oldest_created_at), now) > AGING_WORKING_DAYS;
}

export function ageText(iso: string, now = new Date()): string {
	const minutes = Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / 60000));
	if (minutes < 60) return `${minutes}m`;
	if (minutes < 60 * 24) return `${Math.floor(minutes / 60)}h`;
	return `${Math.floor(minutes / (60 * 24))}d`;
}

const SHORT: Record<FlagType, string> = {
	UNIT_AMBIGUITY: 'UNIT',
	SCHEMA_UNKNOWN: 'SCHEMA',
	LOW_CONFIDENCE_EXTRACTION: 'LOW CONF',
	PARSE_FAILURE: 'PARSE',
	UNSUPPORTED_FORMAT: 'FORMAT',
	CONFLICT: 'CONFLICT',
	SENSITIVE_CONTENT: 'SENSITIVE',
	HELD_LARGE_FILE: 'LARGE',
	CLOUD_RESTRICTED: 'CLOUD'
};

export function flagCountsText(counts: Partial<Record<string, number>>): string {
	return Object.entries(counts)
		.filter(([, n]) => (n ?? 0) > 0)
		.map(([type, n]) => `${SHORT[type as FlagType] ?? type} (${n})`)
		.join(' · ');
}

/** The Console link that opens a case beside the queue. */
export function caseHref(caseKey: string): string {
	return `/review?case=${encodeURIComponent(caseKey)}`;
}
