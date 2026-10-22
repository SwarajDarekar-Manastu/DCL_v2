// Results dashboard helpers (file 08 §5.4–§5.5). Aggregate and per-result metric keys are those S2's runner writes
// (backend/benchmark/metrics.py: `aggregate` and `score_case`).

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
	{ key: 'retrieval_recall_at_8', label: 'Retrieval recall@8', kind: 'ratio', higherIsBetter: true },
	{ key: 'retrieval_recall_at_30', label: 'Retrieval recall@30', kind: 'ratio', higherIsBetter: true },
	{ key: 'latency_p50_ms', label: 'p50 latency', kind: 'ms', higherIsBetter: false },
	{ key: 'latency_p95_ms', label: 'p95 latency', kind: 'ms', higherIsBetter: false },
	{ key: 'cost_total', label: 'Cost', kind: 'cost', higherIsBetter: false }
];

const fmt = (kind: 'ratio' | 'ms' | 'cost', v: number) =>
	kind === 'ratio' ? `${(v * 100).toFixed(1)}%` : kind === 'ms' ? `${Math.round(v)} ms` : `$${v.toFixed(2)}`;
const fmtDelta = (kind: 'ratio' | 'ms' | 'cost', d: number) =>
	(d > 0 ? '+' : d < 0 ? '−' : '±') +
	(kind === 'ratio' ? `${Math.abs(d * 100).toFixed(1)} pt` : kind === 'ms' ? `${Math.round(Math.abs(d))} ms` : `$${Math.abs(d).toFixed(2)}`);

/**
 * The summary ribbon: known aggregate keys that are present, with the delta against a baseline. While a run is
 * still going (`cases_done` < `cases_total`) the values cover only the finished cases, and the labels say so.
 */
export function ribbon(aggregate: Record<string, unknown>, baseline?: Record<string, unknown> | null): RibbonItem[] {
	const done = aggregate.cases_done;
	const total = aggregate.cases_total;
	const partial = typeof done === 'number' && typeof total === 'number' && done < total ? ` (${done} of ${total} so far)` : '';
	return RIBBON.filter((r) => typeof aggregate[r.key] === 'number').map((r) => {
		const value = aggregate[r.key] as number;
		const base = baseline?.[r.key];
		const delta = typeof base === 'number' ? value - base : null;
		return {
			key: r.key,
			label: r.key === 'pass_rate' ? r.label + partial : r.label,
			value: fmt(r.kind, value),
			delta: delta === null ? null : fmtDelta(r.kind, delta),
			better: delta === null || delta === 0 ? null : r.higherIsBetter ? delta > 0 : delta < 0
		};
	});
}

export type Outcome = 'pass' | 'fail' | 'error' | 'pending';

/** The runner's own error for a case (`metrics.error`): the case was not scored. */
export function resultError(r: Pick<BenchmarkResult, 'metrics'>): string | null {
	const e = (r.metrics ?? {}).error;
	return typeof e === 'string' && e ? e : null;
}

export function outcome(r: Pick<BenchmarkResult, 'passed' | 'metrics'>): Outcome {
	if (resultError(r)) return 'error';
	return r.passed === true ? 'pass' : r.passed === false ? 'fail' : 'pending';
}

export const RUN_ERROR = 'RUN_ERROR'; // not a failure class: the runner could not score the case

/** Failure classes with their counts, largest first; runner errors are counted apart as RUN_ERROR. */
export function failureCounts(results: BenchmarkResult[]): [FailureClass | typeof RUN_ERROR, number][] {
	const counts = new Map<FailureClass | typeof RUN_ERROR, number>();
	for (const r of results) {
		const key = outcome(r) === 'error' ? RUN_ERROR : r.passed === false ? r.failure_class : null;
		if (key) counts.set(key, (counts.get(key) ?? 0) + 1);
	}
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

const obj = (v: unknown): Record<string, unknown> => (v !== null && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);
const num = (v: unknown): number | null => (typeof v === 'number' ? v : null);
const bool = (v: unknown): boolean | null => (typeof v === 'boolean' ? v : null);

export interface NumericCheck {
	metric: string;
	expected: number | null;
	unit: string;
	tolerancePct: number | null;
	found: string | null; // value and unit the answer gave, when one matched
	ok: boolean | null;
}

/** metrics.numeric.details: one row per expected number. */
export function numericChecks(metrics: Record<string, unknown>): NumericCheck[] {
	const details = obj(metrics.numeric).details;
	return (Array.isArray(details) ? details : []).map((d) => {
		const r = obj(d);
		return {
			metric: String(r.metric ?? ''),
			expected: num(r.expected),
			unit: String(r.unit ?? ''),
			tolerancePct: num(r.tolerance_pct),
			found: typeof r.found === 'string' ? r.found : null,
			ok: bool(r.ok)
		};
	});
}

export interface Check {
	name: string;
	passed: boolean | null;
	detail: string;
}

/** The scored checks of one result, in score_case order; only the checks the case asked for are present. */
export function checks(metrics: Record<string, unknown>): Check[] {
	const out: Check[] = [];
	const numeric = obj(metrics.numeric);
	if ('numeric' in metrics) {
		const flags = [numeric.unit_error === true && 'right number, wrong unit', numeric.verifier_dropped === true && 'the verifier dropped the right number'].filter(Boolean);
		out.push({ name: 'Numbers', passed: bool(numeric.passed), detail: flags.join('; ') });
	}
	if ('citations' in metrics) {
		const c = obj(metrics.citations);
		const pct = (v: unknown) => (typeof v === 'number' ? `${(v * 100).toFixed(0)}%` : '—');
		const forbidden = strings(c.forbidden_cited);
		out.push({ name: 'Citations', passed: bool(c.passed), detail: `recall ${pct(c.recall)} · precision ${pct(c.precision)}${forbidden.length ? ` · cited forbidden: ${forbidden.join(', ')}` : ''}` });
	}
	if ('tools' in metrics) {
		const t = obj(metrics.tools);
		const missing = strings(t.missing);
		out.push({
			name: 'Tools',
			passed: bool(t.passed),
			detail: `expected ${strings(t.expected).join(', ') || '—'} · used ${strings(t.actual).join(', ') || 'none'}${missing.length ? ` · missing ${missing.join(', ')}` : ''}`
		});
	}
	if ('entities' in metrics) {
		const e = obj(metrics.entities);
		const missing = strings(e.missing);
		out.push({ name: 'Entities', passed: bool(e.passed), detail: missing.length ? `missing ${missing.join(', ')}` : 'all named' });
	}
	for (const [name, v] of Object.entries(obj(obj(metrics.behavior).checks))) {
		const c = obj(v);
		out.push({ name, passed: bool(c.passed), detail: [c.by ? `by ${c.by}` : '', typeof c.rationale === 'string' ? c.rationale : ''].filter(Boolean).join(': ') });
	}
	if ('provenance_labeling' in metrics) {
		const p = obj(metrics.provenance_labeling);
		out.push({ name: 'Provenance labeling', passed: bool(p.passed), detail: typeof p.rationale === 'string' ? p.rationale : '' });
	}
	if ('out_of_scope' in metrics) out.push({ name: 'Out of scope', passed: bool(obj(metrics.out_of_scope).passed), detail: 'no tools and no citations expected' });
	return out;
}

export interface RetrievalView {
	recallAt8: number | null;
	recallAt30: number | null;
	rerankMargin: number | null;
}

export function retrievalOf(metrics: Record<string, unknown>): RetrievalView {
	const r = obj(metrics.retrieval);
	return { recallAt8: num(r.recall_at_8), recallAt30: num(r.recall_at_30), rerankMargin: num(r.rerank_margin) };
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

/** Badge tone per run status: outcomes in colour (completed green, failed red), the rest neutral or info. */
export const RUN_TONE: Record<BenchmarkRun['status'], 'ok' | 'hard' | 'info' | 'neutral'> = {
	queued: 'neutral',
	running: 'info',
	completed: 'ok',
	failed: 'hard',
	cancelled: 'neutral'
};
