// Unsent answers of a case, kept in this tab (sessionStorage) so a trip to the viewer or a reload loses
// nothing (UX review 2026-10-27, finding 7). Only drafts of flags that are still open come back.

import type { Resolution } from '$lib/api_endpoint';

type Drafts = Record<string, Resolution | null>;

const key = (caseKey: string) => `dcl.review.drafts:${caseKey}`;

export function loadDrafts(caseKey: string, openFlagIds: string[]): Drafts {
	try {
		const saved = JSON.parse(sessionStorage.getItem(key(caseKey)) ?? '{}') as Drafts;
		return Object.fromEntries(Object.entries(saved).filter(([id, draft]) => draft && openFlagIds.includes(id)));
	} catch {
		return {};
	}
}

export function saveDrafts(caseKey: string, drafts: Drafts): void {
	try {
		const kept = Object.entries(drafts).filter(([, draft]) => draft);
		if (kept.length) sessionStorage.setItem(key(caseKey), JSON.stringify(Object.fromEntries(kept)));
		else sessionStorage.removeItem(key(caseKey));
	} catch {
		// storage blocked (private window): drafts live only in this page
	}
}
