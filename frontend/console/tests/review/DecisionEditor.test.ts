import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import DecisionEditor from '../../src/lib/components/review/DecisionEditor.svelte';
import { detail, unitFlag } from './fixtures';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return { ...real, dryRun: vi.fn(), editCase: vi.fn(), reopenCase: vi.fn() };
});

const decided = (channel: string, unit: string, gauge: 'gauge' | 'absolute') =>
	unitFlag({
		flag_id: `flag-${channel}`,
		anchor: { channel },
		status: 'RESOLVED',
		resolution: { action: 'set_unit', channel, unit, quantity: 'pressure', gauge_or_abs: gauge, ambient_condition: gauge === 'gauge' ? 'SEA_LEVEL' : null, ambient_pressure_bar_abs: null, expression: null, canonical_name: `pt_${channel}` },
		resolved_by: 'asha@manastuspace.com',
		resolved_at: '2026-10-23T10:00:00Z'
	});
const file = detail([decided('y0', 'bar', 'absolute'), decided('y1', 'bar', 'gauge')]);

beforeEach(() => {
	vi.mocked(api.dryRun).mockReset().mockResolvedValue({
		affected_documents: 1,
		channels: [{ canonical_name: 'y1', unit_si: 'bar', stat_min: 2.5, stat_max: 3.1, stat_mean: null, stat_p99: null, sanity_min: 0, sanity_max: 30, within_sanity: true }],
		messages: [],
		new_flags: [],
		preview: null
	} as unknown as api.DryRunResponse);
	vi.mocked(api.editCase).mockReset().mockResolvedValue({ case_key: 'k', flags: [], rebuild_doc_id: 'd', resumed_doc_ids: [] });
	vi.mocked(api.reopenCase).mockReset().mockResolvedValue({ case_key: 'k', reopened_flag_ids: [], rebuild_doc_id: null });
});
afterEach(cleanup);

describe('DecisionEditor', () => {
	it('lists the approved units with who approved them and when', () => {
		render(DecisionEditor, { detail: file, onChanged: vi.fn(), onReopened: vi.fn() });
		const rows = screen.getAllByRole('row').slice(1);
		const cells = (row: HTMLElement) => within(row).getAllByRole('cell').map((c) => c.textContent?.trim());
		expect(rows.map((r) => cells(r).slice(0, 3))).toEqual([
			['y0', 'bar (absolute)', 'pt_y0'],
			['y1', 'bar (gauge)', 'pt_y1']
		]);
		expect(cells(rows[0])[3]).toContain('asha@manastuspace.com');
		expect(screen.getByRole('button', { name: 'Edit units' })).toBeTruthy();
	});

	it('will not save before the new numbers are previewed and a reason is written', async () => {
		const onChanged = vi.fn();
		render(DecisionEditor, { detail: file, onChanged, onReopened: vi.fn() });
		await fireEvent.click(screen.getByRole('button', { name: 'Edit units' }));
		const save = () => screen.getByRole('button', { name: 'Save change' }) as HTMLButtonElement;
		expect(save().disabled).toBe(true);
		expect(screen.getByText('Change a unit or a name first.')).toBeTruthy();

		await fireEvent.change(screen.getByLabelText('Unit of y1'), { target: { value: 'psia' } });
		expect(screen.getByText('Write why you are changing it.')).toBeTruthy();
		await fireEvent.input(screen.getByPlaceholderText(/the rig sheet says psig/), { target: { value: 'the rig sheet says psia' } });
		expect(save().disabled).toBe(true); // changed and explained, but not previewed
		expect(screen.getByText('Preview the columns before saving.')).toBeTruthy();

		await fireEvent.click(screen.getByRole('button', { name: 'Preview changes' }));
		await waitFor(() => expect(screen.getByText('2.5 … 3.1 bar')).toBeTruthy());
		expect(vi.mocked(api.dryRun).mock.calls).toHaveLength(1); // only the changed column
		expect(save().disabled).toBe(false);

		await fireEvent.click(save());
		await waitFor(() => expect(api.editCase).toHaveBeenCalledOnce());
		const [key, body] = vi.mocked(api.editCase).mock.calls[0];
		expect(key).toBe(file.summary.case_key);
		expect(body.reason).toBe('the rig sheet says psia');
		expect(body.resolutions).toHaveLength(1);
		expect(body.resolutions[0].flag_id).toBe('flag-y1');
		expect(body.resolutions[0].resolution).toMatchObject({ action: 'set_unit', channel: 'y1', unit: 'psi', gauge_or_abs: 'absolute', ambient_condition: null, canonical_name: 'pt_y1' });
		expect(await screen.findByText(/Saved. The file is being rebuilt/)).toBeTruthy();
		expect(onChanged).toHaveBeenCalledOnce();
	});

	it('asks for a new preview when the unit changes again after one', async () => {
		render(DecisionEditor, { detail: file, onChanged: vi.fn(), onReopened: vi.fn() });
		await fireEvent.click(screen.getByRole('button', { name: 'Edit units' }));
		await fireEvent.change(screen.getByLabelText('Unit of y1'), { target: { value: 'psia' } });
		await fireEvent.input(screen.getByPlaceholderText(/the rig sheet says psig/), { target: { value: 'because' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Preview changes' }));
		await waitFor(() => expect((screen.getByRole('button', { name: 'Save change' }) as HTMLButtonElement).disabled).toBe(false));
		await fireEvent.change(screen.getByLabelText('Unit of y1'), { target: { value: 'kpa_a' } });
		expect((screen.getByRole('button', { name: 'Save change' }) as HTMLButtonElement).disabled).toBe(true);
	});

	it('shows the reason for a refused edit in words and keeps the form', async () => {
		vi.mocked(api.editCase).mockRejectedValueOnce(new api.ApiError(422, 'flag x is OPEN: only a decided flag is edited here'));
		render(DecisionEditor, { detail: file, onChanged: vi.fn(), onReopened: vi.fn() });
		await fireEvent.click(screen.getByRole('button', { name: 'Edit units' }));
		await fireEvent.change(screen.getByLabelText('Unit of y0'), { target: { value: 'degc' } });
		await fireEvent.input(screen.getByPlaceholderText(/the rig sheet says psig/), { target: { value: 'because' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Preview changes' }));
		await waitFor(() => expect((screen.getByRole('button', { name: 'Save change' }) as HTMLButtonElement).disabled).toBe(false));
		await fireEvent.click(screen.getByRole('button', { name: 'Save change' }));
		expect((await screen.findByRole('alert')).textContent).toContain('only a decided flag is edited here');
		expect(screen.getByRole('button', { name: 'Save change' })).toBeTruthy();
	});

	it('reopens all the columns with a reason, then hands the file back to the review', async () => {
		const onReopened = vi.fn();
		render(DecisionEditor, { detail: file, onChanged: vi.fn(), onReopened });
		await fireEvent.click(screen.getByRole('button', { name: 'Reopen all columns' }));
		const reopen = () => screen.getByRole('button', { name: 'Reopen' }) as HTMLButtonElement;
		expect(reopen().disabled).toBe(true);
		await fireEvent.input(screen.getByLabelText('Reason for reopening'), { target: { value: 'wrong sensor list' } });
		await fireEvent.click(reopen());
		await waitFor(() => expect(api.reopenCase).toHaveBeenCalledWith(file.summary.case_key, { flag_ids: ['flag-y0', 'flag-y1'], reason: 'wrong sensor list' }));
		expect(onReopened).toHaveBeenCalledOnce();
	});

	describe('units a rule applied while nobody checked', () => {
		const auto = (channel: string) =>
			unitFlag({ flag_id: `flag-${channel}`, anchor: { channel }, status: 'AUTO_RESOLVED', resolution: null, resolved_by: 'pipeline', resolved_at: '2026-10-23T13:28:57Z' });
		const unchecked = detail([auto('y0'), auto('y1')], {
			applied_units: ['y0', 'y1'].map((channel) => ({
				flag_id: `flag-${channel}`,
				channel,
				unit: 'bar',
				quantity: 'pressure',
				gauge_or_abs: 'absolute',
				canonical_name: channel,
				ambient_condition: null,
				rule_id: 'rule-old',
				rule_created_by: 'ai@manastuspace.com',
				rule_created_at: '2026-10-23T13:28:52Z',
				rule_active: false
			}))
		});

		it('says nobody checked them and who the rule was saved by', () => {
			render(DecisionEditor, { detail: unchecked, onChanged: vi.fn(), onReopened: vi.fn() });
			expect(screen.getByText(/2 of these units were applied by a rule and no person has checked them/)).toBeTruthy();
			const row = screen.getAllByRole('row')[1];
			expect(row.textContent).toContain('Nobody checked it');
			expect(row.textContent).toContain('ai@manastuspace.com');
			expect(row.textContent).toContain('now switched off');
		});

		it('lets a person confirm them as they are, with a reason, after previewing the numbers', async () => {
			render(DecisionEditor, { detail: unchecked, onChanged: vi.fn(), onReopened: vi.fn() });
			await fireEvent.click(screen.getByRole('button', { name: 'Edit units' }));
			expect(screen.queryByText('Change a unit or a name first.')).toBeNull();
			await fireEvent.input(screen.getByPlaceholderText(/the rig sheet says psig/), { target: { value: 'checked against the rig sheet' } });
			await fireEvent.click(screen.getByRole('button', { name: 'Preview the numbers' }));
			await waitFor(() => expect(api.dryRun).toHaveBeenCalledTimes(2));
			await fireEvent.click(await screen.findByRole('button', { name: 'Confirm units' }));
			await waitFor(() => expect(api.editCase).toHaveBeenCalledOnce());
			const body = vi.mocked(api.editCase).mock.calls[0][1];
			expect(body.reason).toBe('checked against the rig sheet');
			expect(body.resolutions.map((r) => r.flag_id)).toEqual(['flag-y0', 'flag-y1']);
			expect(body.resolutions[0].resolution).toMatchObject({ unit: 'bar', gauge_or_abs: 'absolute', channel: 'y0' });
		});
	});

	it('says so when nothing has been approved yet', () => {
		render(DecisionEditor, { detail: detail([unitFlag()]), onChanged: vi.fn(), onReopened: vi.fn() });
		expect(screen.getByText('No unit has been approved on this file yet.')).toBeTruthy();
		expect(screen.queryByRole('button', { name: 'Edit units' })).toBeNull();
	});
});
