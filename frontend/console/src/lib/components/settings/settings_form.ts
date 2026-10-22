// Settings editor logic (file 08 §3.2) over S1's /settings API: which keys a section shows, how a value is
// edited, and how an edit becomes a change. Values are JSON; the API validates and answers 422 per key.

import type { ConfigEntry } from '$lib/api_endpoint';

/** `gate.*` (family), `routes.<X>.enabled` (one segment), or an exact key. */
export function keyMatches(pattern: string, key: string): boolean {
	if (pattern.endsWith('.*')) return key.startsWith(pattern.slice(0, -1));
	if (pattern.includes('<X>')) {
		const escaped = pattern.split('<X>').map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
		return new RegExp(`^${escaped.join('[^.]+')}$`).test(key);
	}
	return pattern === key;
}

const isExact = (pattern: string) => !pattern.endsWith('.*') && !pattern.includes('<X>') && !pattern.includes(' ');

export interface SectionKey {
	key: string;
	entry: ConfigEntry | null; // null: not set yet (expected_version 0)
}

/** The section's keys: every stored key matching a pattern, plus exact keys not set yet, sorted. */
export function sectionKeys(patterns: string[], entries: ConfigEntry[]): SectionKey[] {
	const rows = new Map<string, SectionKey>();
	for (const entry of entries) if (patterns.some((p) => keyMatches(p, entry.key))) rows.set(entry.key, { key: entry.key, entry });
	for (const p of patterns) if (isExact(p) && !rows.has(p)) rows.set(p, { key: p, entry: null });
	return [...rows.values()].sort((a, b) => a.key.localeCompare(b.key));
}

export type ValueKind = 'boolean' | 'number' | 'text' | 'lines' | 'json';

export function kindOf(value: unknown): ValueKind {
	if (typeof value === 'boolean') return 'boolean';
	if (typeof value === 'number') return 'number';
	if (typeof value === 'string') return 'text';
	if (Array.isArray(value) && value.every((v) => typeof v === 'string')) return 'lines';
	return 'json';
}

/** What the editor shows for a value of that kind. */
export function toDraft(kind: ValueKind, value: unknown): string {
	if (kind === 'boolean') return value ? 'true' : 'false';
	if (kind === 'number') return String(value);
	if (kind === 'text') return String(value ?? '');
	if (kind === 'lines') return (value as string[]).join('\n');
	return value === undefined ? '' : JSON.stringify(value, null, 2);
}

export type Parsed = { ok: true; value: unknown } | { ok: false; error: string };

/** The value an edited draft stands for; malformed input is caught here, before anything is sent. */
export function fromDraft(kind: ValueKind, draft: string): Parsed {
	if (kind === 'boolean') return { ok: true, value: draft === 'true' };
	if (kind === 'number') {
		const n = Number(draft.trim());
		return draft.trim() !== '' && Number.isFinite(n) ? { ok: true, value: n } : { ok: false, error: 'not a number' };
	}
	if (kind === 'text') return { ok: true, value: draft };
	if (kind === 'lines') {
		return {
			ok: true,
			value: draft
				.split('\n')
				.map((line) => line.trim())
				.filter(Boolean)
		};
	}
	try {
		return { ok: true, value: JSON.parse(draft) };
	} catch (e) {
		return { ok: false, error: `invalid JSON: ${(e as Error).message}` };
	}
}

/** Same JSON value, ignoring key order in objects. */
export function sameValue(a: unknown, b: unknown): boolean {
	const canonical = (v: unknown): unknown =>
		Array.isArray(v)
			? v.map(canonical)
			: v !== null && typeof v === 'object'
				? Object.fromEntries(
						Object.keys(v as object)
							.sort()
							.map((k) => [k, canonical((v as Record<string, unknown>)[k])])
					)
				: v;
	return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
}

/** A one-line preview of a value for history rows. */
export function summary(value: unknown, max = 120): string {
	const text = typeof value === 'string' ? value : JSON.stringify(value);
	return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
