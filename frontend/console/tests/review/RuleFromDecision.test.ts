import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import CaseView from '../../src/lib/components/review/CaseView.svelte';
import { conflictFlag, detail, factUnitFlag, jsonSchemaFlag, unitFlag } from './fixtures';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return { ...real, dryRun: vi.fn(), resolveCase: vi.fn(), assignCase: vi.fn(), undoCase: vi.fn(), previewRule: vi.fn(), createRule: vi.fn() };
});

const answers = (flags: number, over: Partial<api.RulePreview> = {}): api.RulePreview => ({
	matched_documents: 14,
	waiting_documents: 0,
	finished_documents: 14,
	sample: [],
	effect: 'resolves',
	resolves_flags: flags,
	open_channels: [],
	problem: null,
	...over
});

const SCOPE = { scope_root: 'APU Heater', scope_folder_id: 'FOLDER-TP30' };
const heading = () => screen.queryByRole('heading', { name: 'Make a rule from this decision' });
const choose = (action: string) => fireEvent.change(screen.getByRole('combobox', { name: 'Resolution' }), { target: { value: action } });
const apply = () => fireEvent.click(screen.getByRole('button', { name: /Apply & resume/ }));

beforeEach(() => {
	vi.mocked(api.resolveCase).mockReset().mockResolvedValue({ case_key: 'k', flags: [], rule: null, resumed_doc_ids: [], proposed_files: 0 });
	vi.mocked(api.previewRule).mockReset().mockResolvedValue(answers(4));
	vi.mocked(api.createRule).mockReset().mockResolvedValue({ rule_id: 'r1', resolved_flags: 4, rebuilt_doc_ids: ['d1', 'd2', 'd3'], proposed_files: 0 } as unknown as api.RuleCreated);
});
afterEach(cleanup);

function open(flag = conflictFlag(), onChanged = vi.fn(), over: Partial<api.CaseDetail> = {}) {
	render(CaseView, { detail: detail([flag], over), me: 'asha@manastuspace.com', onChanged });
	return onChanged;
}

describe('Make a rule from this decision', () => {
	it('offers no rule before a decision is applied', () => {
		open();
		expect(heading()).toBeNull();
	});

	it('after a conflict is ignored, offers an ignore_pattern prefilled from the flag, with the count before saving', async () => {
		const onChanged = open();
		await choose('ignore');
		await apply();
		await waitFor(() => expect(heading()).toBeTruthy());

		const card = screen.getByRole('article', { name: /Rule from the decision about test_plan_id/ });
		expect(within(card).getByText(/Ignore every conflict \(sources disagree\) whose subject contains “test_plan_id”/)).toBeTruthy();
		expect((within(card).getByLabelText(/Subject contains/) as HTMLInputElement).value).toBe('test_plan_id');
		expect((within(card).getByLabelText('Why') as HTMLInputElement).value).toBe('Accepted on Pressure_T07.dat');
		expect(await within(card).findByText('4 open flags would be answered, among 14 matching files.')).toBeTruthy();
		expect(vi.mocked(api.previewRule)).toHaveBeenLastCalledWith({
			rule_type: 'ignore_pattern',
			scope: SCOPE,
			body: { subject_contains: 'test_plan_id', reason: 'Accepted on Pressure_T07.dat', flag_type: 'CONFLICT', relation: 'sources_disagree' }
		});
		expect(vi.mocked(api.createRule)).not.toHaveBeenCalled();

		await fireEvent.click(within(card).getByRole('button', { name: 'Save rule and answer 4 open flags' }));
		await waitFor(() => expect(api.createRule).toHaveBeenCalledOnce());
		expect(vi.mocked(api.createRule).mock.calls[0][0]).toEqual({
			rule_type: 'ignore_pattern',
			scope: SCOPE,
			body: { subject_contains: 'test_plan_id', reason: 'Accepted on Pressure_T07.dat', flag_type: 'CONFLICT', relation: 'sources_disagree' },
			precedence: 0
		});
		expect(await within(card).findByText('Rule saved. It answered 4 open flags; 3 files are being rebuilt or resumed.')).toBeTruthy();
		expect(onChanged).toHaveBeenCalledTimes(2);
	});

	it('also offers it after "accept both" on a note, with the relation of that flag', async () => {
		open(conflictFlag({}, 'note'));
		await choose('accept_both');
		await apply();
		await screen.findByText(/Ignore every conflict \(note\)/);
		expect(await screen.findByText('4 open flags would be answered, among 14 matching files.')).toBeTruthy();
		expect(vi.mocked(api.previewRule).mock.calls.at(-1)![0].body).toMatchObject({ flag_type: 'CONFLICT', relation: 'note' });
	});

	it('follows the fields: a cleared subject widens the rule, and the count is asked again', async () => {
		open();
		await choose('ignore');
		await apply();
		await screen.findByText('4 open flags would be answered, among 14 matching files.');
		vi.mocked(api.previewRule).mockResolvedValue(answers(21));
		await fireEvent.input(screen.getByLabelText(/Subject contains/), { target: { value: '' } });
		expect(await screen.findByText('21 open flags would be answered, among 14 matching files.')).toBeTruthy();
		expect(screen.getByText(/whatever its subject/)).toBeTruthy();
		expect(vi.mocked(api.previewRule).mock.calls.at(-1)![0].body).not.toHaveProperty('subject_contains');
	});

	it('scopes to a file name pattern in the folder when asked', async () => {
		open();
		await choose('ignore');
		await apply();
		await screen.findByText('4 open flags would be answered, among 14 matching files.');
		const pattern = screen.getByLabelText('File name pattern') as HTMLInputElement;
		expect(pattern.disabled).toBe(true);
		await fireEvent.click(screen.getByLabelText(/files in this folder named/));
		expect(screen.getByText('Type a file name pattern such as T*.dat.')).toBeTruthy();
		expect((screen.getByRole('button', { name: 'Save rule' }) as HTMLButtonElement).disabled).toBe(true);
		await fireEvent.input(pattern, { target: { value: 'T*.dat' } });
		await waitFor(() => expect(vi.mocked(api.previewRule).mock.calls.at(-1)![0].scope).toEqual({ ...SCOPE, scope_filename_glob: 'T*.dat' }));
	});

	it('will not save without a reason, or when the server will not take the rule', async () => {
		open();
		await choose('ignore');
		await apply();
		await screen.findByText('4 open flags would be answered, among 14 matching files.');
		await fireEvent.input(screen.getByLabelText('Why'), { target: { value: ' ' } });
		expect(screen.getByText('Fill in "Why".')).toBeTruthy();
		expect((screen.getByRole('button', { name: /Save rule/ }) as HTMLButtonElement).disabled).toBe(true);

		vi.mocked(api.previewRule).mockResolvedValue(answers(0, { problem: 'reason: String should have at least 1 character' }));
		await fireEvent.input(screen.getByLabelText('Why'), { target: { value: 'ok' } });
		expect(await screen.findByText('The server will not accept this rule: reason: String should have at least 1 character')).toBeTruthy();
		expect((screen.getByRole('button', { name: /Save rule/ }) as HTMLButtonElement).disabled).toBe(true);
	});

	it('shows a refused save in words and keeps the form', async () => {
		vi.mocked(api.createRule).mockRejectedValue(new api.ApiError(422, 'subject: Field required'));
		open();
		await choose('ignore');
		await apply();
		await fireEvent.click(await screen.findByRole('button', { name: 'Save rule and answer 4 open flags' }));
		expect((await screen.findByRole('alert')).textContent).toBe('subject: Field required');
		expect(screen.getByLabelText('Why')).toBeTruthy();
	});

	it('after a source is chosen, offers a source_choice for the subject and the side chosen', async () => {
		open();
		await choose('choose_source');
		await fireEvent.click(screen.getByRole('radio', { name: 'Source B' }));
		await apply();
		await screen.findByText(/When “test_plan_id” disagrees, prefer the side labelled “content”/);
		expect((screen.getByLabelText('Subject') as HTMLInputElement).value).toBe('test_plan_id');
		expect((screen.getByLabelText('Prefer the side labelled') as HTMLInputElement).value).toBe('content');
		await waitFor(() =>
			expect(vi.mocked(api.previewRule)).toHaveBeenLastCalledWith({ rule_type: 'source_choice', scope: SCOPE, body: { subject: 'test_plan_id', prefer: 'content' } })
		);
		await fireEvent.click(await screen.findByRole('button', { name: 'Save rule and answer 4 open flags' }));
		await waitFor(() => expect(api.createRule).toHaveBeenCalledOnce());
		expect(vi.mocked(api.createRule).mock.calls[0][0]).toMatchObject({ rule_type: 'source_choice', body: { subject: 'test_plan_id', prefer: 'content' } });
	});

	it('after the unit of a table number is set, offers a column_unit with the column of the flag', async () => {
		open(factUnitFlag());
		await choose('set_fact_unit');
		await fireEvent.input(screen.getByLabelText('Unit'), { target: { value: 'psi' } });
		await apply();
		await screen.findByText('Read numbers under “Pressure (A)” as psi.');
		await waitFor(() =>
			expect(vi.mocked(api.previewRule)).toHaveBeenLastCalledWith({ rule_type: 'column_unit', scope: SCOPE, body: { column: 'Pressure (A)', unit: 'psi' } })
		);
		expect(await screen.findByText('4 open flags would be answered, among 14 matching files.')).toBeTruthy();
	});

	it('offers to keep a column as text when the decision was "no unit needed"', async () => {
		open(factUnitFlag());
		await choose('set_fact_unit');
		await fireEvent.click(screen.getByLabelText('No unit needed'));
		await apply();
		await screen.findByText('Keep numbers under “Pressure (A)” as text.');
		await waitFor(() => expect(vi.mocked(api.previewRule).mock.calls.at(-1)![0].body).toEqual({ column: 'Pressure (A)', unit: null }));
	});

	it('after JSON keys are mapped, offers a schema_mapping with that mapping and nothing to edit', async () => {
		open(jsonSchemaFlag());
		await choose('map_json_keys');
		await fireEvent.input(screen.getByLabelText('Key'), { target: { value: 'summary' } });
		await fireEvent.input(screen.getByLabelText('Section'), { target: { value: 'Summary' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Add mapping' }));
		await apply();
		await screen.findByText('Map the JSON keys: summary to Summary.');
		const card = screen.getByRole('article', { name: /Rule from the decision/ });
		expect(within(card).queryAllByRole('textbox').filter((box) => !(box as HTMLInputElement).disabled)).toHaveLength(0);
		await waitFor(() =>
			expect(vi.mocked(api.previewRule)).toHaveBeenLastCalledWith({ rule_type: 'schema_mapping', scope: SCOPE, body: { key_to_section: { summary: 'Summary' } } })
		);
	});

	it('leaves the telemetry unit flow as it was: no offer after a channel unit is applied', async () => {
		vi.mocked(api.dryRun).mockResolvedValue({ channels: [], preview: {}, new_flags: [], affected_documents: 1, messages: [] } as unknown as api.DryRunResponse);
		open(unitFlag());
		await choose('set_unit');
		await fireEvent.click(screen.getByRole('button', { name: 'Preview conversion' }));
		await waitFor(() => expect(api.dryRun).toHaveBeenCalled());
		await apply();
		await waitFor(() => expect(api.resolveCase).toHaveBeenCalledOnce());
		expect(heading()).toBeNull();
		expect(vi.mocked(api.previewRule)).not.toHaveBeenCalled();
		expect(screen.getByText(/Also propose to/)).toBeTruthy();
	});

	it('closes the offer with "No thanks"', async () => {
		open(conflictFlag({}, 'note'));
		await choose('accept_both');
		await apply();
		await waitFor(() => expect(heading()).toBeTruthy());
		await fireEvent.click(screen.getByRole('button', { name: 'No thanks' }));
		expect(heading()).toBeNull();
	});

	it('says so when the file has no folder to scope a rule to', async () => {
		open(conflictFlag(), vi.fn(), { locations: [{ ...detail().locations[0], folder_id: null }] });
		await choose('ignore');
		await apply();
		expect(await screen.findByText('This file has no folder to scope a rule to.')).toBeTruthy();
		expect(vi.mocked(api.previewRule)).not.toHaveBeenCalled();
	});

	it('does not offer a rule when the decision itself fails', async () => {
		vi.mocked(api.resolveCase).mockRejectedValue(new api.ApiError(422, 'not allowed'));
		open();
		await choose('ignore');
		await apply();
		expect((await screen.findByRole('alert')).textContent).toBe('not allowed');
		expect(heading()).toBeNull();
	});
});
