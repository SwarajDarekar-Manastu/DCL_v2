// Links shared by the Benchmark screens.

/** Viewer deep link for a document and a serialized stable anchor (`<kind>:<value>:<hash>`). */
export function viewerHref(docId: string, anchor?: string | null): string {
	const base = `/docs/${encodeURIComponent(docId)}/viewer`;
	return anchor ? `${base}?anchor=${encodeURIComponent(anchor)}` : base;
}

export const caseHref = (caseId: string) => `/benchmark/cases/${encodeURIComponent(caseId)}`;
export const runHref = (runId: string) => `/benchmark/runs/${encodeURIComponent(runId)}`;
export const suiteHref = (suite: string) => `/benchmark/suites/${encodeURIComponent(suite)}`;
export const compareHref = (base: string, head: string) =>
	`/benchmark/compare?base=${encodeURIComponent(base)}&head=${encodeURIComponent(head)}`;

/** "a, b , c" → ["a", "b", "c"] */
export function splitList(text: string): string[] {
	return text
		.split(',')
		.map((part) => part.trim())
		.filter(Boolean);
}

export function percent(value: unknown): string {
	return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '—';
}

export function score(value: number | null | undefined, digits = 3): string {
	return value === null || value === undefined ? '—' : value.toFixed(digits);
}
