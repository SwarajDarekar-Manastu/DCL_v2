import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import CaseView from '../../src/lib/components/review/CaseView.svelte';
import { CASE_KEY, detail, unitFlag } from './fixtures';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return {
		...real,
		dryRun: vi.fn(),
		resolveCase: vi.fn(),
		rejectCase: vi.fn(),
		assignCase: vi.fn(),
		undoCase: vi.fn(),
		presignAsset: vi.fn(async () => ({ url: 'https://minio.example/x', expires_in_s: 900 }))
	};
});

const preview = {
	channels: [
		{ canonical_name: 'pt_ain0_bar_g', unit_si: 'bar', stat_min: 0.01, stat_max: 12.59, stat_mean: 11.82, stat_p99: 12.54, sanity_min: 0, sanity_max: 30, within_sanity: true }
	],
	preview: {},
	new_flags: [],
	affected_documents: 116,
	messages: []
};

const applyButton = () => screen.getByRole('button', { name: /Apply & resume/ });

async function chooseSetUnit() {
	await fireEvent.change(screen.getByRole('combobox', { name: 'Resolution' }), { target: { value: 'set_unit' } });
}

describe('CaseView', () => {
	beforeEach(() => {
		vi.mocked(api.dryRun).mockReset().mockResolvedValue(preview);
		vi.mocked(api.resolveCase).mockReset().mockResolvedValue({ case_key: CASE_KEY, flags: [], rule: null, resumed_doc_ids: ['d1', 'd2', 'd3'] });
		vi.mocked(api.rejectCase).mockReset().mockResolvedValue(detail());
	});

	it('enables Apply only after a preview of the current draft', async () => {
		const onChanged = vi.fn();
		render(CaseView, { detail: detail(), me: 'asha@manastuspace.com', onChanged });
		expect((applyButton() as HTMLButtonElement).disabled).toBe(true);
		expect(screen.getByText('Choose a resolution for at least one flag.')).toBeTruthy();

		await chooseSetUnit();
		expect(screen.getByText('Preview the conversion before applying.')).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'Preview conversion' }));
		await waitFor(() => expect(screen.getByText('pt_ain0_bar_g')).toBeTruthy());
		expect(vi.mocked(api.dryRun).mock.calls[0][0]).toEqual({
			case_key: CASE_KEY,
			resolution: { flag_id: 'flag-unit', resolution: unitFlag().suggested_resolution!.resolution },
			rule: null
		});
		expect((applyButton() as HTMLButtonElement).disabled).toBe(false);

		await fireEvent.click(applyButton());
		await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
		expect(vi.mocked(api.resolveCase)).toHaveBeenCalledWith(CASE_KEY, {
			resolutions: [{ flag_id: 'flag-unit', resolution: unitFlag().suggested_resolution!.resolution }],
			rule: null
		});
		expect(screen.getByRole('status').textContent).toBe('Resolved. 3 documents resuming.');
	});

	it('resolves a folder-wide unit case in one action with a folder-scoped rule', async () => {
		render(CaseView, { detail: detail(), me: 'asha@manastuspace.com', onChanged: () => {} });
		await chooseSetUnit();
		await fireEvent.click(screen.getByRole('button', { name: 'Preview conversion' }));
		await waitFor(() => expect(screen.getByText('pt_ain0_bar_g')).toBeTruthy());

		await fireEvent.click(screen.getByLabelText('this folder'));
		expect((applyButton() as HTMLButtonElement).disabled).toBe(true);
		expect(screen.getByText(/The draft changed since the preview/)).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'Preview conversion' }));
		await waitFor(() => expect(applyButton().textContent).toContain('(116 files)'));
		const rule = vi.mocked(api.dryRun).mock.calls[1][0].rule;
		expect(rule).toMatchObject({ rule_type: 'unit_mapping', scope: { scope_root: 'APU Heater', scope_folder_id: 'FOLDER-TP30' } });

		await fireEvent.click(applyButton());
		await waitFor(() => expect(api.resolveCase).toHaveBeenCalledOnce());
		expect(vi.mocked(api.resolveCase).mock.calls[0][1].rule).toEqual(rule);
	});

	it('marks the file as junk and reports backend errors in words', async () => {
		vi.mocked(api.rejectCase).mockRejectedValueOnce(new api.ApiError(501, 'Not Implemented'));
		render(CaseView, { detail: detail(), me: 'asha@manastuspace.com', onChanged: () => {} });
		await fireEvent.click(screen.getByRole('button', { name: 'Mark junk' }));
		await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('The review backend is not connected yet.'));
		expect(api.rejectCase).toHaveBeenCalledWith(CASE_KEY, { action: 'mark_junk' });
	});

	it('offers folder scopes only when the case has a folder id, and undo only after a resolution', async () => {
		const noFolder = detail([unitFlag()], { locations: [{ ...detail().locations[0], folder_id: null }] });
		render(CaseView, { detail: noFolder, me: 'asha@manastuspace.com', onChanged: () => {} });
		expect(screen.queryByLabelText('this folder')).toBeNull();
		await chooseSetUnit();
		expect((screen.getByLabelText('this file') as HTMLInputElement).disabled).toBe(false);
		expect((screen.getByLabelText('this folder') as HTMLInputElement).disabled).toBe(true);
		expect((screen.getByRole('button', { name: 'Undo last resolution' }) as HTMLButtonElement).disabled).toBe(true);
	});

	it('enables undo once a flag is resolved', () => {
		render(CaseView, { detail: detail([unitFlag({ status: 'RESOLVED' })]), me: 'a', onChanged: () => {} });
		expect((screen.getByRole('button', { name: 'Undo last resolution' }) as HTMLButtonElement).disabled).toBe(false);
	});
});
