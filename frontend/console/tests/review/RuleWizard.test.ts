import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import RuleWizard from '../../src/lib/components/review/RuleWizard.svelte';

const api = vi.hoisted(() => ({ listFolders: vi.fn(), previewRule: vi.fn(), createRule: vi.fn() }));
vi.mock('../../src/lib/api_endpoint', async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const FOLDER = { folder_id: 'F1', root_name: 'APU Injector', path: 'APU Injector/Injector 14/Pressure_Data_Files', files: 12, waiting: 12 };
const preview = (over = {}) => ({
	matched_documents: 12,
	waiting_documents: 12,
	finished_documents: 0,
	sample: [{ doc_id: 'd1', title: 'Test_01', path: 'APU Injector/Injector 14/Pressure_Data_Files/Test_01.dat', status: 'HALTED' }],
	effect: 'proposes',
	open_channels: [
		{ channel: 'y0', files: 12 },
		{ channel: 'y1', files: 12 }
	],
	problem: null,
	...over
});

beforeEach(() => {
	api.listFolders.mockResolvedValue({ items: [FOLDER] });
	api.previewRule.mockResolvedValue(preview());
	api.createRule.mockResolvedValue({ rule_id: 'r1', proposed_files: 12 });
});
afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

const pick = async (name: RegExp) => fireEvent.click(await screen.findByRole('button', { name }));

describe('RuleWizard', () => {
	it('walks from a folder to a saved proposal that approves nothing', async () => {
		const onSaved = vi.fn();
		render(RuleWizard, { onSaved });

		await pick(/Pressure_Data_Files/);
		expect(await screen.findByText(/reaches 12 files; 12 are waiting/)).toBeTruthy();
		expect(screen.getByText(/They wait on the columns y0, y1/)).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));

		const next = screen.getByRole('button', { name: /Next/ }) as HTMLButtonElement;
		expect(next.disabled).toBe(true);
		for (const channel of ['y0', 'y1']) {
			const select = screen.getByRole('combobox', { name: `Unit of ${channel}` }) as HTMLSelectElement;
			await fireEvent.change(select, { target: { value: 'bar_a' } });
		}
		expect((screen.getByRole('button', { name: /Next/ }) as HTMLButtonElement).disabled).toBe(false);
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));

		expect(await screen.findByText(/12 waiting files will show these units as a proposal/)).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'Save rule and propose to 12 files' }));

		await waitFor(() => expect(api.createRule).toHaveBeenCalledOnce());
		expect(api.createRule.mock.calls[0][0]).toEqual({
			rule_type: 'channel_proposal',
			scope: { scope_root: 'APU Injector', scope_folder_id: 'F1', scope_filename_glob: null, scope_extension: null },
			body: {
				channels: {
					y0: { canonical_name: 'y0', physical_quantity: 'pressure', unit: 'bar', gauge_or_abs: 'absolute' },
					y1: { canonical_name: 'y1', physical_quantity: 'pressure', unit: 'bar', gauge_or_abs: 'absolute' }
				}
			},
			precedence: 0
		});
		expect(await screen.findByText('Rule saved.')).toBeTruthy();
		expect(screen.getByText(/12 files now show these units as a proposal. Nothing is approved/)).toBeTruthy();
		expect(screen.getByRole('link', { name: 'Review the 12 files' }).getAttribute('href')).toBe('/review?proposed_by_rule_id=r1');
		expect(onSaved).toHaveBeenCalledOnce();
	});

	it('does not let the reviewer leave the first step without a folder', async () => {
		render(RuleWizard);
		expect((screen.getByRole('button', { name: /Next/ }) as HTMLButtonElement).disabled).toBe(true);
		expect(screen.getByText('Pick a folder first.')).toBeTruthy();
	});

	it('says plainly when the server will not accept the rule and offers no save', async () => {
		api.previewRule.mockResolvedValueOnce(preview()).mockResolvedValue(preview({ problem: 'channels must not be empty' }));
		render(RuleWizard);
		await pick(/Pressure_Data_Files/);
		await screen.findByText(/reaches 12 files/);
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));
		await fireEvent.change(screen.getByRole('combobox', { name: 'Unit of y0' }), { target: { value: 'degc' } });
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));
		expect(await screen.findByText(/will not accept this rule: channels must not be empty/)).toBeTruthy();
		expect((screen.getByRole('button', { name: /Save rule/ }) as HTMLButtonElement).disabled).toBe(true);
	});

	it('tells the reviewer when nothing is waiting, so the rule only covers later files', async () => {
		api.previewRule.mockResolvedValue(preview({ matched_documents: 0, would_resume: 0, sample: [], open_channels: [] }));
		render(RuleWizard);
		await pick(/Pressure_Data_Files/);
		expect(await screen.findByText(/No file matches yet/)).toBeTruthy();
	});
});
