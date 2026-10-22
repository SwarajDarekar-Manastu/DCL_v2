import { describe, expect, it } from 'vitest';
import { byCategory, checks, failureCounts, isActive, numericChecks, outcome, ribbon, RUN_TONE, runProgress, runRequest } from '../../src/lib/components/benchmark/run_view';
import { compareHref, splitList, viewerHref } from '../../src/lib/components/benchmark/links';
import { result } from './fixtures';

describe('results dashboard helpers', () => {
	it('shows known aggregates with deltas, judging direction per metric', () => {
		const items = ribbon(
			{ pass_rate: 0.8, retrieval_recall_at_8: 0.6, latency_p95_ms: 7000, unknown_key: 3 },
			{ pass_rate: 0.9, retrieval_recall_at_8: 0.6, latency_p95_ms: 9000 }
		);
		expect(items).toEqual([
			{ key: 'pass_rate', label: 'Pass rate', value: '80.0%', delta: '−10.0 pt', better: false },
			{ key: 'retrieval_recall_at_8', label: 'Retrieval recall@8', value: '60.0%', delta: '±0.0 pt', better: null },
			{ key: 'latency_p95_ms', label: 'p95 latency', value: '7000 ms', delta: '−2000 ms', better: true }
		]);
		expect(ribbon({ pass_rate: 1 }).map((i) => i.delta)).toEqual([null]);
	});

	it('says that a running run is scored only so far', () => {
		expect(ribbon({ pass_rate: 0, cases_done: 3, cases_total: 8 })[0].label).toBe('Pass rate (3 of 8 so far)');
		expect(ribbon({ pass_rate: 0.5, cases_done: 8, cases_total: 8 })[0].label).toBe('Pass rate');
	});

	it('counts failure classes and passes per category', () => {
		const results = [
			result({ case_id: 'a' }),
			result({ case_id: 'b', failure_class: 'RETRIEVAL_MISS' }),
			result({ case_id: 'c' }),
			result({ case_id: 'd', passed: true, failure_class: null }),
			result({ case_id: 'e', passed: null, failure_class: null }),
			result({ case_id: 'f', passed: false, failure_class: null, metrics: { error: 'RuntimeError: x' } })
		];
		expect(failureCounts(results)).toEqual([
			['RERANK_MISS', 2],
			['RETRIEVAL_MISS', 1],
			['RUN_ERROR', 1]
		]);
		expect(results.map(outcome)).toEqual(['fail', 'fail', 'fail', 'pass', 'pending', 'error']);
		const cases = [
			{ case_id: 'a', category: 'CODE' as const },
			{ case_id: 'd', category: 'CODE' as const },
			{ case_id: 'b', category: 'VISUAL' as const }
		];
		expect(byCategory(results, cases)).toEqual([
			{ category: 'CODE', passed: 1, total: 2 },
			{ category: 'VISUAL', passed: 0, total: 1 },
			{ category: 'unknown', passed: 0, total: 3 }
		]);
	});

	it('reads numeric checks defensively and builds links', () => {
		expect(numericChecks(result().metrics)).toEqual([
			{ metric: 'peak_pressure', expected: 12.4, unit: 'bar', tolerancePct: 1, found: null, ok: false }
		]);
		expect(numericChecks({})).toEqual([]);
		expect(checks({ out_of_scope: { passed: true }, provenance_labeling: { by: 'judge', passed: false, rationale: 'unlabelled' } })).toEqual([
			{ name: 'Provenance labeling', passed: false, detail: 'unlabelled' },
			{ name: 'Out of scope', passed: true, detail: 'no tools and no citations expected' }
		]);
		expect(viewerHref('d-1', 'cells:Run 1!A1:D20:')).toBe('/docs/d-1/viewer?anchor=cells%3ARun%201!A1%3AD20%3A');
		expect(compareHref('a', 'b')).toBe('/benchmark/compare?base=a&head=b');
		expect(splitList(' a, ,b ,c')).toEqual(['a', 'b', 'c']);
	});
});

describe('run progress', () => {
	it('counts results against the case snapshot', () => {
		const run = { case_versions: { a: 1, b: 3, c: 1, d: 2 } };
		expect(runProgress(run, [result({ case_id: 'a' }), result({ case_id: 'b' })])).toEqual({ done: 2, total: 4, label: '2 of 4 cases' });
		expect(runProgress({ case_versions: {} }, [])).toEqual({ done: 0, total: 0, label: '0 of 0 cases' });
	});

	it('keeps polling only while the run can still change', () => {
		expect(['queued', 'running', 'completed', 'failed', 'cancelled'].map((s) => isActive(s as never))).toEqual([true, true, false, false, false]);
	});
});

describe('run requests', () => {
	it('runs every active case unless a subset is picked', () => {
		expect(runRequest('telemetry')).toEqual({ suite: 'telemetry' });
		expect(runRequest('telemetry', ['c', 'a'], ['a', 'b', 'c'])).toEqual({ suite: 'telemetry', case_ids: ['a', 'c'] });
		expect(runRequest('telemetry', ['tp07-t04-peak'])).toEqual({ suite: 'telemetry', case_ids: ['tp07-t04-peak'] });
	});
});

describe('run status tone', () => {
	it('colours the five run statuses by outcome', () => {
		expect(RUN_TONE).toEqual({ queued: 'neutral', running: 'info', completed: 'ok', failed: 'hard', cancelled: 'neutral' });
	});
});
