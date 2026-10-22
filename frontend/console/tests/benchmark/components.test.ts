import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import CaseEditor from '../../src/lib/components/benchmark/CaseEditor.svelte';
import ResultDrilldown from '../../src/lib/components/benchmark/ResultDrilldown.svelte';
import RetrievalLab from '../../src/lib/components/benchmark/RetrievalLab.svelte';
import { emptyForm, formFromCase } from '../../src/lib/components/benchmark/case_form';
import { reactive } from '../review/state.svelte';
import { benchCase, DOC, result } from './fixtures';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => ({
	...(await importOriginal<object>()),
	retrievalSearch: vi.fn()
}));

const HIT = {
	doc_id: DOC,
	title: 'Test Report 37',
	anchor: 'page:8:3f2a9c1b7d4e5f60',
	parent_text: 'Section 4 Results …',
	passage: 'steady state 12.5 bar',
	node_type: 'child',
	breadcrumb: 'Test Report 37 › 4 Results',
	page_no: 8,
	doc_kind: 'test_report',
	source_origin: 'internal',
	trust_tier: 2,
	language: 'en',
	needs_review: true,
	doc_date: null,
	test_plan_id: 'TP37',
	test_run_id: null,
	hardware_item: null,
	web_url: null,
	asset_id: null,
	rrf_score: 0.0325,
	rerank_score: 0.912,
	also_in: []
};

describe('RetrievalLab', () => {
	beforeEach(() => {
		vi.mocked(api.retrievalSearch).mockReset().mockResolvedValue({
			hits: [HIT],
			warnings: ['reranker unavailable; results are in RRF order'],
			dense_path: 'exact',
			rerank_margin_1_5: 0.41,
			leg_counts: { dense: 30, lexical: 18 }
		});
	});

	it('sends the query with filters and shows scored hits linked to the viewer', async () => {
		render(RetrievalLab);
		await fireEvent.input(screen.getByLabelText('Query'), { target: { value: 'C-103 thermal margin' } });
		await fireEvent.input(screen.getByLabelText('Test plans'), { target: { value: 'TP37, TP30' } });
		await fireEvent.click(screen.getByLabelText('external library'));
		await fireEvent.click(screen.getByRole('button', { name: 'Search' }));
		await waitFor(() => expect(screen.getByText('0.912')).toBeTruthy());

		const body = vi.mocked(api.retrievalSearch).mock.calls[0][0];
		expect(body).toMatchObject({ query: 'C-103 thermal margin', scope: 'child', k: 30, rerank: true });
		expect(body.filters).toMatchObject({ test_plan_ids: ['TP37', 'TP30'], source_origins: ['external_kept'], include_needs_review: true });

		expect(screen.getByRole('link', { name: 'Test Report 37, p. 8' }).getAttribute('href')).toBe(
			`/docs/${DOC}/viewer?anchor=page%3A8%3A3f2a9c1b7d4e5f60`
		);
		expect(screen.getByText('0.0325')).toBeTruthy();
		expect(screen.getByRole('status').textContent).toContain('reranker unavailable');
		expect(screen.getByLabelText('Search summary').textContent).toContain('dense path exact');
	});
});

describe('CaseEditor', () => {
	it('submits only a valid form', async () => {
		const onSubmit = vi.fn();
		render(CaseEditor, { form: reactive(emptyForm('telemetry')), busy: false, submitLabel: 'Save', onSubmit });
		const save = screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement;
		expect(save.disabled).toBe(true);
		expect(screen.getByRole('alert').textContent).toContain('question is required');
		await fireEvent.input(screen.getByLabelText('Question'), { target: { value: 'Peak pressure?' } });
		expect(save.disabled).toBe(false);
		await fireEvent.click(save);
		expect(onSubmit).toHaveBeenCalledOnce();
	});

	it('edits rows of the spec', async () => {
		const form = reactive(formFromCase(benchCase()));
		render(CaseEditor, { form, busy: false, submitLabel: 'Save', onSubmit: () => {} });
		expect((screen.getByLabelText('Value 1') as HTMLInputElement).value).toBe('12.4');
		await fireEvent.click(screen.getByRole('button', { name: 'Add number' }));
		expect(screen.getByLabelText('Metric 2')).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'Remove gold 1' }));
		expect(screen.queryByLabelText('Gold anchor 1')).toBeNull();
		expect((screen.getByLabelText('must label external sources') as HTMLInputElement).checked).toBe(true);
	});
});

describe('ResultDrilldown', () => {
	it('shows expected numbers, every check, retrieval and gold passages', () => {
		render(ResultDrilldown, { result: result(), testCase: benchCase() });
		expect(screen.getByText('not found').closest('tr')?.textContent).toContain('12.4 bar');
		expect(screen.getByText('not found').closest('tr')?.textContent).toContain('±1%');
		const checks = screen.getByRole('list', { name: 'Checks' }).textContent ?? '';
		expect(checks).toContain('the verifier dropped the right number');
		expect(checks).toContain('expected query_telemetry · used search_documents · missing query_telemetry');
		expect(checks).toContain('must_present_both_conflicting_values · by judge: Only the folder value was given.');
		expect(screen.getByText(/recall@8 0\.0% · recall@30 100\.0% · rerank margin 0\.050/)).toBeTruthy();
		expect(screen.getByText('answer')).toBeTruthy();
		expect(screen.getByRole('link', { name: 'page:8:3f2a9c1b7d4e5f60' }).getAttribute('href')).toBe(
			`/docs/${DOC}/viewer?anchor=page%3A8%3A3f2a9c1b7d4e5f60`
		);
	});

	it('shows the runner error instead of empty scores when a case could not be scored', () => {
		const errored = result({ passed: false, failure_class: null, latency_ms: null, metrics: { error: 'RuntimeError: bound to a different event loop' } });
		render(ResultDrilldown, { result: errored, testCase: benchCase() });
		expect(screen.getByText(/The runner could not score this case: RuntimeError: bound to a different event loop/)).toBeTruthy();
		expect(screen.queryByRole('list', { name: 'Checks' })).toBeNull();
	});
});
