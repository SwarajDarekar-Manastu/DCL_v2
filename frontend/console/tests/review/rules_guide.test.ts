import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import RuleForm from '../../src/lib/components/review/RuleForm.svelte';
import RulesGuide from '../../src/lib/components/review/RulesGuide.svelte';
import { exampleBody, GUIDE_STEPS, RULE_TYPE_HELP } from '../../src/lib/components/review/rules_guide';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => ({ ...(await importOriginal<object>()), previewRule: vi.fn() }));

afterEach(cleanup);

describe('rules guide content', () => {
	it('has unique steps, each with text and what the reader gets', () => {
		expect(new Set(GUIDE_STEPS.map((s) => s.id)).size).toBe(GUIDE_STEPS.length);
		for (const step of GUIDE_STEPS) {
			expect(step.title.length).toBeGreaterThan(10);
			expect(step.summary.length).toBeGreaterThan(20);
			expect(step.points.length).toBeGreaterThan(0);
			expect(step.get.length).toBeGreaterThan(10);
		}
	});

	it('shows real screenshots, with a caption, on the steps that create and apply a rule', () => {
		const withImages = GUIDE_STEPS.filter((s) => s.images.length);
		expect(withImages.map((s) => s.id)).toEqual(['idea', 'folder', 'columns', 'save', 'apply', 'after', 'audit', 'from-case']);
		for (const step of withImages) {
			for (const image of step.images) {
				expect(image.src).toMatch(/\.png/);
				expect(image.alt.length).toBeGreaterThan(10);
				expect(image.caption.length).toBeGreaterThan(10);
			}
		}
		expect(GUIDE_STEPS.find((s) => s.id === 'from-case')?.images).toHaveLength(2);
	});

	it('teaches the page first: pick files, say what the columns are, save, then a person applies', () => {
		expect(GUIDE_STEPS.map((s) => s.id).slice(0, 5)).toEqual(['idea', 'folder', 'columns', 'save', 'apply']);
		expect(GUIDE_STEPS[3].get).toMatch(/None is approved/);
		expect(GUIDE_STEPS.find((s) => s.id === 'audit')?.title).toMatch(/Audit/);
	});

	it('has an example body that is a JSON object for every rule type', () => {
		for (const type of Object.keys(RULE_TYPE_HELP) as (keyof typeof RULE_TYPE_HELP)[]) {
			const parsed = JSON.parse(exampleBody(type));
			expect(parsed && typeof parsed === 'object' && !Array.isArray(parsed)).toBe(true);
			expect(RULE_TYPE_HELP[type].what.length).toBeGreaterThan(15);
		}
	});

	it('says what each kind does when saved: units propose, answering kinds resolve, document kinds apply', () => {
		const effects = Object.fromEntries(Object.entries(RULE_TYPE_HELP).map(([type, help]) => [type, help.effect]));
		expect(effects).toEqual({
			channel_proposal: 'proposes',
			unit_mapping: 'proposes',
			channel_map: 'decision',
			ignore_pattern: 'resolves',
			schema_mapping: 'resolves',
			column_unit: 'resolves',
			source_choice: 'resolves',
			origin_override: 'applies',
			supersession: 'applies'
		});
	});

	it('gives a plain text of at most two sentences for every kind, and says what a reviewer gets from the acting ones', () => {
		for (const [type, help] of Object.entries(RULE_TYPE_HELP)) {
			const sentences = help.what.split(/(?<=\.)\s+/);
			expect(sentences.length, type).toBeLessThanOrEqual(2);
			expect(help.what.split(/\s+/).length, type).toBeLessThanOrEqual(40);
			if (help.effect === 'resolves') expect(help.what, type).toMatch(/answers the open flags it matches/i);
		}
		expect(RULE_TYPE_HELP.origin_override.what).toMatch(/next rebuild, which saving starts/);
		expect(RULE_TYPE_HELP.supersession.what).toMatch(/Saving rebuilds those files/);
	});

	it('fills examples that carry what each acting kind needs', () => {
		expect(RULE_TYPE_HELP.ignore_pattern.example).toEqual({ reason: 'Known rig offset, accepted in this folder', flag_type: 'CONFLICT', relation: 'check_failed', subject_contains: 'limit' });
		expect(RULE_TYPE_HELP.column_unit.example).toEqual({ column: 'Pressure*', unit: 'psi' });
		expect(RULE_TYPE_HELP.source_choice.example).toEqual({ subject: 'test_plan_id', prefer: 'content' });
		expect(RULE_TYPE_HELP.schema_mapping.example).toEqual({ key_to_section: { summary: 'Summary', results: 'Test results' } });
	});

	it('no longer says that only unit proposals change anything, or marks any kind "stored only"', () => {
		const advanced = GUIDE_STEPS.find((s) => s.id === 'advanced')!;
		const text = [advanced.summary, ...advanced.points, advanced.get].join(' ');
		expect(text).not.toMatch(/stored only|Only a unit proposal changes anything|No file changes because of them/);
		expect(text).toMatch(/Every other kind acts when you save it/);
		for (const kind of ['ignore_pattern', 'column_unit', 'source_choice', 'schema_mapping', 'origin_override', 'supersession']) expect(text).toContain(kind);
	});

	it('teaches "Make a rule from this decision" before the order of precedence', () => {
		const ids = GUIDE_STEPS.map((s) => s.id);
		expect(ids.indexOf('from-decision')).toBeGreaterThan(ids.indexOf('from-case'));
		expect(ids.indexOf('from-decision')).toBeLessThan(ids.indexOf('priority'));
		expect(GUIDE_STEPS.find((s) => s.id === 'from-decision')!.points.join(' ')).toMatch(/N open flags would be answered/);
	});
});

describe('RulesGuide', () => {
	const openGuide = async () => {
		render(RulesGuide);
		await fireEvent.click(screen.getByRole('button', { name: 'How rules work' }));
		return screen.findByRole('dialog');
	};

	it('opens a dialog on the first step and moves through the steps', async () => {
		const dialog = await openGuide();
		expect(dialog.textContent).toContain(`Step 1 of ${GUIDE_STEPS.length}`);
		expect(dialog.querySelector('h3')?.textContent).toBe(GUIDE_STEPS[0].title);
		expect(dialog.querySelector('img')?.getAttribute('alt')).toBe(GUIDE_STEPS[0].images[0].alt);
		await fireEvent.click(screen.getByRole('button', { name: /^Next/ }));
		expect(dialog.querySelector('h3')?.textContent).toBe(GUIDE_STEPS[1].title);
		await fireEvent.click(screen.getByRole('button', { name: /Back/ }));
		expect(dialog.querySelector('h3')?.textContent).toBe(GUIDE_STEPS[0].title);
	});

	it('jumps to a step from the list and closes on the last one', async () => {
		const dialog = await openGuide();
		await fireEvent.click(screen.getByRole('button', { name: new RegExp(GUIDE_STEPS.at(-1)!.title.replace(/[()]/g, '.')) }));
		expect(dialog.querySelector('h3')?.textContent).toBe(GUIDE_STEPS.at(-1)!.title);
		expect(dialog.querySelector('img')).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: 'Got it' }));
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
	});
});

describe('RuleForm', () => {
	it('explains the chosen type and fills an example that follows the type until it is edited', async () => {
		const onSubmit = vi.fn();
		render(RuleForm, { busy: false, onSubmit });
		const body = screen.getByRole('textbox', { name: /Body/ }) as HTMLTextAreaElement;
		expect(screen.getByText(RULE_TYPE_HELP.channel_proposal.what)).toBeTruthy();
		expect(body.value).toBe(exampleBody('channel_proposal'));

		const type = screen.getByRole('combobox', { name: 'Rule type' }) as HTMLSelectElement;
		await fireEvent.change(type, { target: { value: 'ignore_pattern' } });
		expect(screen.getByText(RULE_TYPE_HELP.ignore_pattern.what)).toBeTruthy();
		expect(body.value).toBe(exampleBody('ignore_pattern'));

		await fireEvent.input(body, { target: { value: '{"reason": "my own words"}' } });
		await fireEvent.change(type, { target: { value: 'origin_override' } });
		expect(body.value).toBe('{"reason": "my own words"}');
	});

	it('offers every kind a person can write, the new ones included, and never a file approval', () => {
		render(RuleForm, { busy: false, onSubmit: vi.fn() });
		const type = screen.getByRole('combobox', { name: 'Rule type' }) as HTMLSelectElement;
		expect([...type.options].map((o) => o.value)).toEqual([
			'channel_proposal',
			'ignore_pattern',
			'column_unit',
			'source_choice',
			'schema_mapping',
			'origin_override',
			'supersession'
		]);
	});

	it('fills a valid example for the new kinds and says what saving does, never "nothing reads this kind"', async () => {
		render(RuleForm, { busy: false, onSubmit: vi.fn() });
		const body = screen.getByRole('textbox', { name: /Body/ }) as HTMLTextAreaElement;
		const type = screen.getByRole('combobox', { name: 'Rule type' }) as HTMLSelectElement;

		expect(screen.getByText(/Saving shows these units on the waiting files as a proposal/)).toBeTruthy();
		for (const kind of ['column_unit', 'source_choice', 'ignore_pattern', 'schema_mapping'] as const) {
			await fireEvent.change(type, { target: { value: kind } });
			expect(JSON.parse(body.value)).toEqual(RULE_TYPE_HELP[kind].example);
			expect(screen.getByText(RULE_TYPE_HELP[kind].what)).toBeTruthy();
			expect(screen.getByText('Saving answers the matching open flags the way you would and rebuilds those files.')).toBeTruthy();
		}
		for (const kind of ['supersession', 'origin_override'] as const) {
			await fireEvent.change(type, { target: { value: kind } });
			expect(screen.getByText('The matched documents change at their next rebuild, which saving starts.')).toBeTruthy();
		}
		expect(screen.queryByText(/Nothing in the pipeline reads this kind/)).toBeNull();
	});

	it('saves a column_unit rule with its scope', async () => {
		const onSubmit = vi.fn();
		render(RuleForm, { busy: false, onSubmit });
		await fireEvent.change(screen.getByRole('combobox', { name: 'Rule type' }), { target: { value: 'column_unit' } });
		await fireEvent.input(screen.getByPlaceholderText('Graph item id'), { target: { value: 'FOLDER-1' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save rule' }));
		expect(onSubmit).toHaveBeenCalledWith({
			rule_type: 'column_unit',
			scope: { scope_root: null, scope_folder_id: 'FOLDER-1', scope_filename_glob: null, scope_extension: null },
			body: { column: 'Pressure*', unit: 'psi' },
			precedence: 0
		});
	});

	it('previews how many open flags the rule would answer, and hides the answer once the form changes', async () => {
		vi.mocked(api.previewRule).mockReset().mockResolvedValue({
			matched_documents: 14,
			waiting_documents: 0,
			finished_documents: 14,
			sample: [],
			effect: 'resolves',
			resolves_flags: 9,
			open_channels: [],
			problem: null
		});
		render(RuleForm, { busy: false, onSubmit: vi.fn() });
		const type = screen.getByRole('combobox', { name: 'Rule type' });
		await fireEvent.change(type, { target: { value: 'source_choice' } });
		await fireEvent.input(screen.getByPlaceholderText('Graph item id'), { target: { value: 'FOLDER-1' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
		expect(await screen.findByText('9 open flags would be answered, among 14 matching files.')).toBeTruthy();
		expect(vi.mocked(api.previewRule)).toHaveBeenCalledWith({
			rule_type: 'source_choice',
			scope: { scope_root: null, scope_folder_id: 'FOLDER-1', scope_filename_glob: null, scope_extension: null },
			body: { subject: 'test_plan_id', prefer: 'content' }
		});

		await fireEvent.input(screen.getByPlaceholderText('T*.dat'), { target: { value: 'T*.dat' } });
		expect(screen.queryByText(/open flags would be answered/)).toBeNull();
	});

	it('shows the reason the server will not take a body, and a failed preview in words', async () => {
		vi.mocked(api.previewRule).mockReset().mockResolvedValueOnce({
			matched_documents: 0,
			waiting_documents: 0,
			finished_documents: 0,
			sample: [],
			effect: 'resolves',
			resolves_flags: 0,
			open_channels: [],
			problem: 'column: Field required'
		});
		render(RuleForm, { busy: false, onSubmit: vi.fn() });
		await fireEvent.change(screen.getByRole('combobox', { name: 'Rule type' }), { target: { value: 'column_unit' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
		expect(await screen.findByText('The server will not accept this rule: column: Field required')).toBeTruthy();

		vi.mocked(api.previewRule).mockRejectedValueOnce(new api.ApiError(422, 'bad scope'));
		await fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
		expect((await screen.findByRole('alert')).textContent).toBe('bad scope');
	});

	it('cannot preview or save a body that is not JSON', async () => {
		render(RuleForm, { busy: false, onSubmit: vi.fn() });
		await fireEvent.input(screen.getByRole('textbox', { name: /Body/ }), { target: { value: '{nope' } });
		expect((screen.getByRole('button', { name: 'Preview' }) as HTMLButtonElement).disabled).toBe(true);
		expect((screen.getByRole('button', { name: 'Save rule' }) as HTMLButtonElement).disabled).toBe(true);
	});
});
