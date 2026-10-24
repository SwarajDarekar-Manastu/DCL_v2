import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import { session } from '../../src/lib/auth/session.svelte';
import Page from '../../src/routes/review/rules/+page.svelte';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return { ...real, listRules: vi.fn(), createRule: vi.fn(), deactivateRule: vi.fn(), simulateRule: vi.fn(), listFolders: vi.fn(), previewRule: vi.fn() };
});

const rule = (rule_type: api.RuleType, over: Partial<api.RuleView> = {}): api.RuleView => ({
	rule_id: `id-${rule_type}`,
	rule_type,
	origin: 'operator',
	scope: { scope_root: 'APU Heater', scope_folder_id: 'F1', scope_filename_glob: null, scope_extension: null },
	body: {},
	precedence: 0,
	source_blob_sha256: null,
	supersedes_rule_id: null,
	active: true,
	created_by: 'asha@manastuspace.com',
	created_at: '2026-10-24T09:00:00Z',
	flags_resolved: 0,
	runs_mapped: 0,
	scope_folder_path: 'APU Heater/Test Plan 30',
	flags_proposed: 0,
	flags_decided: 0,
	files_waiting: 0,
	...over
});

const RULES = [
	rule('column_unit', { body: { column: 'Pressure*', unit: 'psi' }, flags_resolved: 4 }),
	rule('origin_override', { body: { source_origin: 'external_kept' } }),
	rule('channel_proposal', { flags_proposed: 12, flags_decided: 3, files_waiting: 9 })
];

const row = (type: string) => screen.getByText(type, { selector: 'strong' }).closest('tr') as HTMLElement;

beforeEach(() => {
	session.user = { email: 'asha@manastuspace.com', name: 'Asha', oid: 'o', roles: ['reviewer'] };
	vi.mocked(api.listRules).mockReset().mockResolvedValue({ items: RULES });
	vi.mocked(api.listFolders).mockReset().mockResolvedValue({ items: [] });
	vi.mocked(api.previewRule).mockReset();
	vi.mocked(api.deactivateRule).mockReset().mockResolvedValue(rule('column_unit', { active: false }));
	vi.mocked(api.createRule).mockReset();
});
afterEach(() => {
	cleanup();
	session.user = null;
});

describe('Rules page', () => {
	it('marks no kind "stored only" and says what each saved rule has done', async () => {
		render(Page);
		await screen.findByText('column_unit', { selector: 'strong' });
		expect(screen.queryByText('stored only')).toBeNull();
		expect(screen.queryByText(/Nothing reads this kind/)).toBeNull();
		expect(within(row('column_unit')).getByText('4 flags answered')).toBeTruthy();
		expect(within(row('origin_override')).getByText('Changes the matching files at their rebuild.')).toBeTruthy();
		expect(within(row('channel_proposal')).getByText('12 proposed · 3 decided · 9 files waiting')).toBeTruthy();
		expect(within(row('channel_proposal')).getByRole('link', { name: 'Review the waiting files' }).getAttribute('href')).toBe('/review?proposed_by_rule_id=id-channel_proposal');
		expect(within(row('column_unit')).queryByRole('link', { name: 'Review the waiting files' })).toBeNull();
	});

	it('names the off button by what the rule did, and says in its tooltip what switching off does', async () => {
		render(Page);
		await screen.findByText('column_unit', { selector: 'strong' });
		const off = within(row('column_unit')).getByRole('button', { name: 'Switch off' });
		expect(off.getAttribute('title')).toBe('Switches the rule off. The flags it answered are open again and those files are rebuilt.');
		expect(within(row('origin_override')).getByRole('button', { name: 'Switch off' }).getAttribute('title')).toMatch(/rebuilt without it/);
		const stop = within(row('channel_proposal')).getByRole('button', { name: 'Stop proposing' });
		expect(stop.getAttribute('title')).toBe('Stops new proposals. Files a person has already approved are never changed.');
	});

	it('says after switching off that the flags are open again and the files rebuilt', async () => {
		render(Page);
		await screen.findByText('column_unit', { selector: 'strong' });
		await fireEvent.click(within(row('column_unit')).getByRole('button', { name: 'Switch off' }));
		await waitFor(() => expect(api.deactivateRule).toHaveBeenCalledWith('id-column_unit'));
		expect(await screen.findByText('Rule switched off. The flags it answered are open again and those files are being rebuilt.')).toBeTruthy();
	});

	it('says after saving a rule that acts how many flags it answered and how many files are rebuilt', async () => {
		vi.mocked(api.createRule).mockResolvedValue({ ...rule('source_choice'), proposed_files: 0, resolved_flags: 7, rebuilt_doc_ids: ['a', 'b'] });
		render(Page);
		await screen.findByText('column_unit', { selector: 'strong' });
		await fireEvent.click(screen.getByText('Advanced: write a rule as JSON'));
		await fireEvent.change(screen.getByRole('combobox', { name: 'Rule type' }), { target: { value: 'source_choice' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save rule' }));
		await waitFor(() => expect(api.createRule).toHaveBeenCalledOnce());
		expect(vi.mocked(api.createRule).mock.calls[0][0]).toMatchObject({ rule_type: 'source_choice', body: { subject: 'test_plan_id', prefer: 'content' } });
		expect(await screen.findByText('Rule saved. It answered 7 open flags; 2 files are being rebuilt or resumed.')).toBeTruthy();
	});

	it('says after saving a document rule how many files are rebuilt', async () => {
		vi.mocked(api.createRule).mockResolvedValue({ ...rule('origin_override'), proposed_files: 0, resolved_flags: 0, rebuilt_doc_ids: ['a'] });
		render(Page);
		await screen.findByText('column_unit', { selector: 'strong' });
		await fireEvent.click(screen.getByText('Advanced: write a rule as JSON'));
		await fireEvent.change(screen.getByRole('combobox', { name: 'Rule type' }), { target: { value: 'origin_override' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save rule' }));
		expect(await screen.findByText('Rule saved. 1 file is being rebuilt to apply it.')).toBeTruthy();
	});

	it('words a simulation of a rule that acts without "never changed"', async () => {
		vi.mocked(api.simulateRule).mockResolvedValue({ matched_documents: 5, waiting_documents: 2, finished_documents: 3, sample: [] });
		render(Page);
		await screen.findByText('column_unit', { selector: 'strong' });
		await fireEvent.click(within(row('column_unit')).getByRole('button', { name: 'Simulate' }));
		expect(await screen.findByText('Reaches 5 files: 2 waiting, 3 already processed.')).toBeTruthy();
	});
});
