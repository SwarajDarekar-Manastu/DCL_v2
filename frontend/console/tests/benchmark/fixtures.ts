import type { BenchmarkCase, BenchmarkResult } from '../../src/lib/api_endpoint';

export const DOC = '6f1c2a3e-0000-4000-8000-000000000001';

export function benchCase(overrides: Partial<BenchmarkCase> = {}): BenchmarkCase {
	return {
		case_id: 'tp07-t04-peak',
		version: 2,
		suite: 'telemetry',
		status: 'active',
		category: 'TELEMETRY_MATH',
		question: 'Peak chamber pressure of TP07 T04?',
		spec: {
			language: 'en',
			paraphrases: ['Max Pc in TP07 run 4?'],
			expected_numeric: [{ metric: 'peak_pressure', value: 12.4, unit: 'bar', tolerance_pct: 1 }],
			expected_citations: [{ file_name: 'TR37.pdf', doc_id: null, standard_id: null, page: 8 }],
			must_not_cite: [{ file_name: null, doc_id: null, standard_id: 'ECSS-E-ST-32-01C Rev.1', page: null }],
			expected_tools: { tools: ['query_telemetry'], ordered: false },
			expected_entities: ['TP07'],
			retrieval_gold_anchors: [{ doc_id: DOC, anchor: 'page:8:3f2a9c1b7d4e5f60' }],
			expected_behavior: ['must_label_external'],
			clarification_answer: null
		},
		difficulty: 2,
		notes: 'Excel-verified',
		source_trace_id: null,
		created_by: 'asha@manastuspace.com',
		created_at: '2026-10-22T09:00:00Z',
		...overrides
	};
}

export function result(overrides: Partial<BenchmarkResult> = {}): BenchmarkResult {
	return {
		case_id: 'tp07-t04-peak',
		case_version: 2,
		trace_id: null,
		passed: false,
		failure_class: 'RERANK_MISS',
		latency_ms: 6100,
		cost_estimate: 0.0123,
		metrics: {
			numeric: [{ metric: 'peak_pressure', expected: 12.4, actual: 11.0, unit: 'bar', within: false }],
			citations: { recall: 0.5, precision: 1, forbidden_cited: [] },
			tools: { expected: ['query_telemetry'], actual: ['search_documents'], match: false },
			faithfulness: 0.9,
			recall_at_8: 0,
			recall_at_30: 1,
			reranker_margin: 0.05,
			judge_rationale: 'Gold passage ranked 12th after rerank.',
			warnings: ['reranker unavailable; results are in RRF order']
		},
		...overrides
	};
}
