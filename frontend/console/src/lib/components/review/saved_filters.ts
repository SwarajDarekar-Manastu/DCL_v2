// Saved queue filters (file 08 §4.2 QueueList): named filter sets kept in this browser per signed-in user. They are
// a convenience: storage can be missing or blocked, and the queue works without it.

import type { CaseFilters } from '$lib/api_endpoint';
import { filtersFromUrl, urlFor } from './filters';

export interface SavedFilter {
	name: string;
	query: string; // URL query of the filters, without the open case
}

const keyFor = (owner: string) => `dcl-queue-filters:${owner.toLowerCase()}`;

function safeStorage(): Storage | null {
	try {
		return globalThis.localStorage ?? null;
	} catch {
		return null;
	}
}

export function loadSaved(owner: string, storage: Storage | null = safeStorage()): SavedFilter[] {
	try {
		const parsed = JSON.parse(storage?.getItem(keyFor(owner)) ?? '[]');
		return Array.isArray(parsed) ? parsed.filter((f) => typeof f?.name === 'string' && typeof f?.query === 'string') : [];
	} catch {
		return [];
	}
}

function write(owner: string, list: SavedFilter[], storage: Storage | null): SavedFilter[] {
	try {
		storage?.setItem(keyFor(owner), JSON.stringify(list));
	} catch {
		// storage full or blocked: the list lasts for this page only
	}
	return list;
}

export function queryOf(filters: CaseFilters): string {
	return urlFor(filters, null).split('?')[1] ?? '';
}

/** Saves (or replaces, by name) the current filters; returns the new list sorted by name. */
export function saveFilter(owner: string, name: string, filters: CaseFilters, storage: Storage | null = safeStorage()): SavedFilter[] {
	const clean = name.trim();
	const rest = loadSaved(owner, storage).filter((f) => f.name !== clean);
	return write(owner, [...rest, { name: clean, query: queryOf(filters) }].sort((a, b) => a.name.localeCompare(b.name)), storage);
}

export function deleteFilter(owner: string, name: string, storage: Storage | null = safeStorage()): SavedFilter[] {
	return write(
		owner,
		loadSaved(owner, storage).filter((f) => f.name !== name),
		storage
	);
}

export const filtersOf = (saved: SavedFilter): CaseFilters => filtersFromUrl(new URLSearchParams(saved.query));
