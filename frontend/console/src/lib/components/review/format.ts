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

/** What a case asks, per flag type and count, in words: "2 readings to check", "6 units to set". */
const QUESTION: Record<FlagType, (n: number) => string> = {
	UNIT_AMBIGUITY: (n) => `${n} unit${n === 1 ? '' : 's'} to set`,
	SCHEMA_UNKNOWN: () => 'file layout to map',
	LOW_CONFIDENCE_EXTRACTION: (n) => `${n} reading${n === 1 ? '' : 's'} to check`,
	PARSE_FAILURE: () => 'file could not be read',
	UNSUPPORTED_FORMAT: () => 'no reader for this file type',
	CONFLICT: (n) => `${n} disagreement${n === 1 ? '' : 's'} to settle`,
	SENSITIVE_CONTENT: (n) => `${n} possible secret${n === 1 ? '' : 's'}`,
	HELD_LARGE_FILE: () => 'large file held',
	CLOUD_RESTRICTED: () => 'cloud reading not allowed'
};

export function questionText(counts: Partial<Record<string, number>>): string {
	return Object.entries(counts)
		.filter(([, n]) => (n ?? 0) > 0)
		.map(([type, n]) => QUESTION[type as FlagType]?.(n ?? 0) ?? `${n} ${type}`)
		.join(' · ');
}

/** Where in the file a case sits: "page 9", or the sheet's name. */
export function placeText(pageOrSheet: string): string {
	return /^\d+$/.test(pageOrSheet) ? `page ${pageOrSheet}` : pageOrSheet;
}

/** The Console link that opens a case beside the queue. */
export function caseHref(caseKey: string): string {
	return `/review?case=${encodeURIComponent(caseKey)}`;
}
