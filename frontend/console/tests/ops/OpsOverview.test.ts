import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { getStepFiles, type OpsSummary } from '../../src/lib/api_endpoint';
import OpsOverview from '../../src/lib/components/ops/OpsOverview.svelte';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => ({
	...(await importOriginal<object>()),
	getStepFiles: vi.fn(async (step: string) => ({
		step,
		total: 2,
		files: [
			{ name: 'Atlas user guide', path: 'Manuals/Atlas/atlas.pdf', doc_id: '11e7fa72-d20a-452f-baa4-1269b5d9ff3e', route: 'A1', updated_at: '2026-10-27T14:31:16Z', detail: 'place 1 in cpu_parse' },
			{ name: 'Setup', path: null, doc_id: '0455eabd-1012-40ec-8aa9-55e3b8fceae3', route: 'C', updated_at: null, detail: 'no job queued; sent again on its own after 2 hours' }
		]
	}))
}));

const SUMMARY: OpsSummary = {
	queues: [
		{ queue: 'io_light', waiting: 0 },
		{ queue: 'cpu_parse', waiting: 24 },
		{ queue: 'benchmark', waiting: 1 }
	],
	steps: [
		{ step: 'outside_scope', count: 3951 },
		{ step: 'in_line', count: 2 },
		{ step: 'failed', count: 0 }
	],
	documents_by_status: { ACTIVE: 9, HALTED: 22, PROCESSING: 28 },
	open_flags: { HARD: 176, SOFT: 77 },
	last_runs: [
		{ suite: 'documents', run_id: '74d76bf5-3037-47fc-8816-8969a02583f5', status: 'running', pass_rate: 0.0667, cases_done: 5, cases_total: 15, started_at: '2026-10-22T08:43:52Z', finished_at: null }
	],
	llm_today: null,
	notes: { llm_today: 'llm_calls is not available yet (S1 migration 0012)' }
};

describe('OpsOverview', () => {
	it('shows files by step, queue depths, flags, documents and runs, and a note for an unread part', () => {
		render(OpsOverview, { summary: SUMMARY });
		const steps = screen.getByRole('region', { name: 'Files by step' });
		expect(within(steps).getByRole('button', { name: /Outside the processing scope/ }).textContent?.replace(/\s+/g, '')).toBe('Outsidetheprocessingscope3,951');
		expect(within(steps).getByRole('button', { name: /Waiting for review/ }).textContent?.replace(/\s+/g, '')).toBe('Waitingforreview0');
		expect(within(steps).getByText('Jobs in queues:', { exact: false }).textContent?.replace(/\s+/g, ' ').trim()).toBe('Jobs in queues: cpu_parse 24 · benchmark 1');
		expect(screen.getByRole('region', { name: 'Review' }).textContent).toContain('176');
		const docs = [...screen.getByRole('region', { name: 'Documents' }).querySelectorAll('li')].map((li) => li.textContent?.replace(/\s+/g, ''));
		expect(docs).toEqual(['PROCESSING28', 'HALTED22', 'ACTIVE9']);
		expect(screen.getByRole('link', { name: '74d76bf5' }).getAttribute('href')).toBe('/benchmark/runs/74d76bf5-3037-47fc-8816-8969a02583f5');
		expect(screen.getByText('6.7% of 5/15')).toBeTruthy();
		expect(screen.getByText('llm_calls is not available yet (S1 migration 0012)')).toBeTruthy();
	});

	it('lists the files of a step when its count is clicked', async () => {
		render(OpsOverview, { summary: SUMMARY });
		await fireEvent.click(screen.getByRole('button', { name: /In line/ }));
		expect(getStepFiles).toHaveBeenCalledWith('in_line');
		const dialog = await screen.findByRole('dialog');
		await waitFor(() => expect(within(dialog).getByRole('heading', { name: 'In line · 2' })).toBeTruthy());
		const rows = within(dialog).getAllByRole('row').slice(1).map((r) => [...r.querySelectorAll('td')].map((td) => td.textContent?.replace(/\s+/g, ' ').trim()));
		expect(rows[0]).toEqual(['Atlas user guide Manuals/Atlas', 'A1', expect.stringMatching(/ago$/), 'place 1 in cpu_parse']);
		expect(rows[1]).toEqual(['Setup', 'C', '', 'no job queued; sent again on its own after 2 hours']);
		expect(within(dialog).getByRole('link', { name: 'Atlas user guide' }).getAttribute('href')).toBe('/docs/11e7fa72-d20a-452f-baa4-1269b5d9ff3e/viewer');
	});
});
