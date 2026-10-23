import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { OpsSummary } from '../../src/lib/api_endpoint';
import OpsOverview from '../../src/lib/components/ops/OpsOverview.svelte';

const SUMMARY: OpsSummary = {
	queues: [
		{ queue: 'io_light', waiting: 0 },
		{ queue: 'cpu_parse', waiting: 24 }
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
	it('shows queue depths, flags, documents and runs, and a note for an unread part', () => {
		render(OpsOverview, { summary: SUMMARY });
		expect(within(screen.getByRole('region', { name: 'Queues' })).getByText('24 waiting', { exact: false })).toBeTruthy();
		expect(screen.getByRole('region', { name: 'Review' }).textContent).toContain('176');
		const docs = [...screen.getByRole('region', { name: 'Documents' }).querySelectorAll('li')].map((li) => li.textContent?.replace(/\s+/g, ''));
		expect(docs).toEqual(['PROCESSING28', 'HALTED22', 'ACTIVE9']);
		expect(screen.getByRole('link', { name: '74d76bf5' }).getAttribute('href')).toBe('/benchmark/runs/74d76bf5-3037-47fc-8816-8969a02583f5');
		expect(screen.getByText('6.7% of 5/15')).toBeTruthy();
		expect(screen.getByText('llm_calls is not available yet (S1 migration 0012)')).toBeTruthy();
	});
});
