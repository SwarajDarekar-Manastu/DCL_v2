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
		vi.mocked(api.resolveCase).mockReset().mockResolvedValue({ case_key: CASE_KEY, flags: [], rule: null, resumed_doc_ids: ['d1'], proposed_files: 0 });
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
			resolution: { flag_id: 'flag-unit', resolution: unitFlag().suggested_resolution!.resolution }
		});
		expect((applyButton() as HTMLButtonElement).disabled).toBe(false);

		await fireEvent.click(applyButton());
		await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
		expect(vi.mocked(api.resolveCase)).toHaveBeenCalledWith(CASE_KEY, {
			resolutions: [{ flag_id: 'flag-unit', resolution: unitFlag().suggested_resolution!.resolution }],
			rule_scope: null
		});
		expect(screen.getByRole('status').textContent).toBe('Resolved. This file is resuming.');
	});

	it('approves this file and also proposes its units to the other files of the folder', async () => {
		vi.mocked(api.resolveCase).mockResolvedValue({ case_key: CASE_KEY, flags: [], rule: null, resumed_doc_ids: ['d1'], proposed_files: 11 } as unknown as api.ResolveResponse);
		render(CaseView, { detail: detail(), me: 'asha@manastuspace.com', onChanged: () => {} });
		await chooseSetUnit();
		await fireEvent.click(screen.getByRole('button', { name: 'Preview conversion' }));
		await waitFor(() => expect(screen.getByText('pt_ain0_bar_g')).toBeTruthy());

		await fireEvent.click(screen.getByLabelText('the other files in this folder'));
		expect(screen.getByText(/a person still checks and applies each one/)).toBeTruthy();
		await fireEvent.click(applyButton());
		await waitFor(() => expect(api.resolveCase).toHaveBeenCalledOnce());
		expect(vi.mocked(api.resolveCase).mock.calls[0][1].rule_scope).toEqual({ scope_root: 'APU Heater', scope_folder_id: 'FOLDER-TP30' });
		expect(vi.mocked(api.resolveCase).mock.calls[0][1]).not.toHaveProperty('rule');
		expect(await screen.findByText(/11 other files now show these units as a proposal/)).toBeTruthy();
	});

	it('asks for a file name pattern before it proposes to matching files', async () => {
		render(CaseView, { detail: detail(), me: 'asha@manastuspace.com', onChanged: () => {} });
		await chooseSetUnit();
		await fireEvent.click(screen.getByRole('button', { name: 'Preview conversion' }));
		await waitFor(() => expect(screen.getByText('pt_ain0_bar_g')).toBeTruthy());
		await fireEvent.click(screen.getByLabelText('files in this folder named'));
		expect(screen.getByText('Type a file name pattern such as T*.dat.')).toBeTruthy();
		expect((applyButton() as HTMLButtonElement).disabled).toBe(true);
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
		expect(screen.queryByLabelText('the other files in this folder')).toBeNull();
		await chooseSetUnit();
		expect((screen.getByLabelText('no other file') as HTMLInputElement).disabled).toBe(false);
		expect((screen.getByLabelText('the other files in this folder') as HTMLInputElement).disabled).toBe(true);
		expect((screen.getByRole('button', { name: 'Undo last resolution' }) as HTMLButtonElement).disabled).toBe(true);
	});

	it('enables undo once a flag is resolved', () => {
		render(CaseView, { detail: detail([unitFlag({ status: 'RESOLVED' })]), me: 'a', onChanged: () => {} });
		expect((screen.getByRole('button', { name: 'Undo last resolution' }) as HTMLButtonElement).disabled).toBe(false);
	});
});
