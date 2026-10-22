// Results dashboard helpers (file 08 §5.4–§5.5). Aggregate and metric keys follow the runner contract with S2.

import type { BenchmarkCase, BenchmarkResult, BenchmarkRun, FailureClass, RunRequest } from '$lib/api_endpoint';

export interface RibbonItem {
	key: string;
	label: string;
	value: string;
	delta: string | null;
	better: boolean | null; // null when there is no baseline
}

const RIBBON: { key: string; label: string; kind: 'ratio' | 'ms' | 'cost'; higherIsBetter: boolean }[] = [
	{ key: 'pass_rate', label: 'Pass rate', kind: 'ratio', higherIsBetter: true },
	{ key: 'numeric_exactness', label: 'Numeric exactness', kind: 'ratio', higherIsBetter: true },
	{ key: 'citation_recall', label: 'Citation recall', kind: 'ratio', higherIsBetter: true },
	{ key: 'faithfulness', label: 'Faithfulness', kind: 'ratio', higherIsBetter: true },
	{ key: 'recall_at_8', label: 'Retrieval recall@8', kind: 'ratio', higherIsBetter: true },
	{ key: 'recall_at_30', label: 'Retrieval recall@30', kind: 'ratio', higherIsBetter: true },
	{ key: 'latency_p95_ms', label: 'p95 latency', kind: 'ms', higherIsBetter: false },
	{ key: 'cost_total', label: 'Cost', kind: 'cost', higherIsBetter: false }
];

const fmt = (kind: 'ratio' | 'ms' | 'cost', v: number) =>
	kind === 'ratio' ? `${(v * 100).toFixed(1)}%` : kind === 'ms' ? `${Math.round(v)} ms` : `$${v.toFixed(2)}`;
const fmtDelta = (kind: 'ratio' | 'ms' | 'cost', d: number) =>
	(d > 0 ? '+' : d < 0 ? '−' : '±') +
	(kind === 'ratio' ? `${Math.abs(d * 100).toFixed(1)} pt` : kind === 'ms' ? `${Math.round(Math.abs(d))} ms` : `$${Math.abs(d).toFixed(2)}`);

/** The summary ribbon: known aggregate keys that are present, with the delta against a baseline. */
export function ribbon(aggregate: Record<string, unknown>, baseline?: Record<string, unknown> | null): RibbonItem[] {
	return RIBBON.filter((r) => typeof aggregate[r.key] === 'number').map((r) => {
		const value = aggregate[r.key] as number;
		const base = baseline?.[r.key];
		const delta = typeof base === 'number' ? value - base : null;
		return {
			key: r.key,
			label: r.label,
			value: fmt(r.kind, value),
			delta: delta === null ? null : fmtDelta(r.kind, delta),
			better: delta === null || delta === 0 ? null : r.higherIsBetter ? delta > 0 : delta < 0
		};
	});
}

/** Failure classes with their counts, largest first; passing and unscored results are not counted. */
export function failureCounts(results: BenchmarkResult[]): [FailureClass, number][] {
	const counts = new Map<FailureClass, number>();
	for (const r of results) if (r.passed === false && r.failure_class) counts.set(r.failure_class, (counts.get(r.failure_class) ?? 0) + 1);
	return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export interface CategoryRow {
	category: string;
	passed: number;
	total: number;
}

/** Pass counts per category; cases unknown to the suite list are grouped as "unknown". */
export function byCategory(results: BenchmarkResult[], cases: Pick<BenchmarkCase, 'case_id' | 'category'>[]): CategoryRow[] {
	const categoryOf = new Map(cases.map((c) => [c.case_id, c.category as string]));
	const rows = new Map<string, CategoryRow>();
	for (const r of results) {
		const category = categoryOf.get(r.case_id) ?? 'unknown';
		const row = rows.get(category) ?? { category, passed: 0, total: 0 };
		row.total += 1;
		if (r.passed) row.passed += 1;
		rows.set(category, row);
	}
	const unknownLast = (c: string) => (c === 'unknown' ? 1 : 0);
	return [...rows.values()].sort((a, b) => unknownLast(a.category) - unknownLast(b.category) || a.category.localeCompare(b.category));
}

export interface NumericCheck {
	metric: string;
	expected: unknown;
	actual: unknown;
	unit: string;
	within: boolean | null;
}

/** metrics.numeric from the runner, tolerant of missing fields. */
export function numericChecks(metrics: Record<string, unknown>): NumericCheck[] {
	const rows = Array.isArray(metrics.numeric) ? metrics.numeric : [];
	return rows
		.filter((r): r is Record<string, unknown> => r !== null && typeof r === 'object')
		.map((r) => ({
			metric: String(r.metric ?? ''),
			expected: r.expected,
			actual: r.actual,
			unit: String(r.unit ?? ''),
			within: typeof r.within === 'boolean' ? r.within : null
		}));
}

/** How often a run page re-reads a queued or running run; the runner may not publish websocket events. */
export const POLL_MS = 5000;

/** Queued and running runs can still change; the other statuses are final. */
export function isActive(status: BenchmarkRun['status']): boolean {
	return status === 'queued' || status === 'running';
}

export interface RunProgress {
	done: number;
	total: number;
	label: string;
}

/** Results recorded so far against the run's case snapshot. */
export function runProgress(run: Pick<BenchmarkRun, 'case_versions'>, results: Pick<BenchmarkResult, 'case_id'>[]): RunProgress {
	const total = Object.keys(run.case_versions).length;
	const done = Math.min(results.length, total);
	return { done, total, label: `${done} of ${total} cases` };
}

/** A run of the whole suite's active cases, or of the picked subset in suite order. */
export function runRequest(suite: string, picked: readonly string[] = [], order: readonly string[] = []): RunRequest {
	if (picked.length === 0) return { suite };
	const chosen = new Set(picked);
	const ordered = order.filter((id) => chosen.has(id));
	return { suite, case_ids: [...ordered, ...picked.filter((id) => !ordered.includes(id))] };
}
