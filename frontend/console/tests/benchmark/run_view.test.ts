import { describe, expect, it } from 'vitest';
import { byCategory, failureCounts, numericChecks, ribbon } from '../../src/lib/components/benchmark/run_view';
import { compareHref, splitList, viewerHref } from '../../src/lib/components/benchmark/links';
import { result } from './fixtures';

describe('results dashboard helpers', () => {
	it('shows known aggregates with deltas, judging direction per metric', () => {
		const items = ribbon(
			{ pass_rate: 0.8, recall_at_8: 0.6, latency_p95_ms: 7000, unknown_key: 3 },
			{ pass_rate: 0.9, recall_at_8: 0.6, latency_p95_ms: 9000 }
		);
		expect(items).toEqual([
			{ key: 'pass_rate', label: 'Pass rate', value: '80.0%', delta: '−10.0 pt', better: false },
			{ key: 'recall_at_8', label: 'Retrieval recall@8', value: '60.0%', delta: '±0.0 pt', better: null },
			{ key: 'latency_p95_ms', label: 'p95 latency', value: '7000 ms', delta: '−2000 ms', better: true }
		]);
		expect(ribbon({ pass_rate: 1 }).map((i) => i.delta)).toEqual([null]);
	});

	it('counts failure classes and passes per category', () => {
		const results = [
			result({ case_id: 'a' }),
			result({ case_id: 'b', failure_class: 'RETRIEVAL_MISS' }),
			result({ case_id: 'c' }),
			result({ case_id: 'd', passed: true, failure_class: null }),
			result({ case_id: 'e', passed: null, failure_class: null })
		];
		expect(failureCounts(results)).toEqual([
			['RERANK_MISS', 2],
			['RETRIEVAL_MISS', 1]
		]);
		const cases = [
			{ case_id: 'a', category: 'CODE' as const },
			{ case_id: 'd', category: 'CODE' as const },
			{ case_id: 'b', category: 'VISUAL' as const }
		];
		expect(byCategory(results, cases)).toEqual([
			{ category: 'CODE', passed: 1, total: 2 },
			{ category: 'VISUAL', passed: 0, total: 1 },
			{ category: 'unknown', passed: 0, total: 2 }
		]);
	});

	it('reads numeric checks defensively and builds links', () => {
		expect(numericChecks({ numeric: [{ metric: 'p', expected: 1, actual: 2, unit: 'bar', within: false }, null] })).toEqual([
			{ metric: 'p', expected: 1, actual: 2, unit: 'bar', within: false }
		]);
		expect(numericChecks({})).toEqual([]);
		expect(viewerHref('d-1', 'cells:Run 1!A1:D20:')).toBe('/docs/d-1/viewer?anchor=cells%3ARun%201!A1%3AD20%3A');
		expect(compareHref('a', 'b')).toBe('/benchmark/compare?base=a&head=b');
		expect(splitList(' a, ,b ,c')).toEqual(['a', 'b', 'c']);
	});
});
