import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import CaseView from '../../src/lib/components/review/CaseView.svelte';
import { entryState, segments, spans } from '../../src/lib/components/review/page_check';
import { CASE_KEY, detail, unitFlag } from './fixtures';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return {
		...real,
		resolveCase: vi.fn(),
		presignAsset: vi.fn(async () => ({ url: 'https://minio.example/page.png', expires_in_s: 900 }))
	};
});

const cell = (text: string, span_of: number[] | null = null, struck: string[] = []) => ({ text, struck, span_of, corrected: false });

// A made-up page as the API returns it: a heading and a label/value table with two unsure entries
const READING: api.PageReading = {
	page_no: 11,
	image_uri: 's3://dcl-assets/pages/x/0011.png',
	reader_confidence: 0.9,
	prompt_version: 'transcribe_page.v3',
	blocks: [
		{
			key: 'c909a46153e32d77',
			parts: [
				{ kind: 'heading', text: 'Bench Heater Trial', struck: [], rows: null, corrected: [] },
				{
					kind: 'table',
					text: null,
					struck: [],
					corrected: [],
					rows: [
						[cell('Trial Name'), cell('Trial 7.1 (warm-up run'), cell('', [0, 1])],
						[cell('Sample Name'), cell('Sample B-12 (lot 4'), cell('', [1, 1])],
						[cell('Rig'), cell('old note 42.0 Ω', null, ['old note']), cell('', [2, 1])]
					]
				}
			]
		}
	],
	entries: [
		{
			key: '990f59414aba02c459e88cc095c57f31',
			label: 'Trial Name',
			value: 'Trial 7.1 (warm-up run',
			unit: null,
			alternatives: ['Trial 7.1 (warm-up rnu', 'Trial 7.1 (warm-up run)'],
			confidence: 0.9,
			illegible: false,
			flag_id: 'f1',
			located: { block_key: 'c909a46153e32d77', table: 0, cell: [0, 1] }
		},
		{
			key: 'bd38e744b6017b861d9e6754d0d40e7e',
			label: 'Sample Name',
			value: 'Sample B-12 (lot 4',
			unit: null,
			alternatives: [],
			confidence: 0.85,
			illegible: false,
			flag_id: 'f2',
			located: { block_key: 'c909a46153e32d77', table: 0, cell: [1, 1] }
		}
	]
};

const entryFlag = (flag_id: string) =>
	unitFlag({ flag_id, flag_type: 'LOW_CONFIDENCE_EXTRACTION', severity: 'SOFT', anchor: { page: 11 }, subject: 'value', allowed_actions: ['set_value'], evidence: null, suggested_resolution: null });

const show = () =>
	render(CaseView, {
		detail: detail([entryFlag('f1'), entryFlag('f2')], { document_status: 'ACTIVE_WITH_SOFT_FLAGS', page_reading: READING }),
		me: 'asha@manastuspace.com',
		onChanged: () => {}
	});

describe('the page check', () => {
	beforeEach(() => {
		sessionStorage.clear();
		vi.mocked(api.resolveCase).mockReset().mockResolvedValue({ case_key: CASE_KEY, flags: [], rule: null, resumed_doc_ids: [], proposed_files: 0 });
	});

	it('shows the page as read, with tables as grids and the unsure entries highlighted', () => {
		show();
		const page = screen.getByRole('region', { name: 'Page check' });
		expect(within(page).getByRole('heading', { name: 'Page 11 as read' })).toBeTruthy();
		expect(within(page).getByRole('status').textContent?.trim()).toBe('2 entries to check · 0 of 2 done');
		expect(within(page).getByRole('cell', { name: 'Unsure entry: Trial Name' })).toBeTruthy();
		expect(within(page).getByRole('cell', { name: 'Trial Name' })).toBeTruthy();
		expect(page.querySelector('s')?.textContent).toBe('old note'); // crossed out on the page
		expect(screen.queryByRole('combobox', { name: 'Resolution' })).toBeNull(); // no card per entry
	});

	it('starts on the first entry; Enter confirms it and moves to the next', async () => {
		show();
		const first = screen.getByRole('textbox', { name: 'Trial Name' }) as HTMLInputElement;
		await waitFor(() => expect(document.activeElement).toBe(first));
		expect(first.value).toBe('Trial 7.1 (warm-up run');
		await fireEvent.keyDown(first, { key: 'Enter' });
		expect(screen.getByRole('status').textContent?.trim()).toBe('2 entries to check · 1 of 2 done');
		expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Sample Name' }));
	});

	it('a chip fills the field and marks the entry corrected', async () => {
		show();
		await fireEvent.click(screen.getByRole('button', { name: 'Trial 7.1 (warm-up run)' }));
		expect((screen.getByRole('textbox', { name: 'Trial Name' }) as HTMLInputElement).value).toBe('Trial 7.1 (warm-up run)');
		expect(screen.getByText(/✎ corrected/)).toBeTruthy();
	});

	it('Apply waits for every entry, then sends each answer', async () => {
		show();
		const apply = () => screen.getByRole('button', { name: 'Apply page 11' }) as HTMLButtonElement;
		await fireEvent.click(screen.getByRole('button', { name: 'Trial 7.1 (warm-up run)' }));
		expect(apply().disabled).toBe(true);
		expect(screen.getByText('Answer every highlighted entry: 1 left.')).toBeTruthy();
		const second = screen.getByRole('textbox', { name: 'Sample Name' });
		await fireEvent.keyDown(second, { key: 'Enter' });
		expect(apply().disabled).toBe(false);
		await waitFor(() => expect(document.activeElement).toBe(apply())); // the last answer moves on to Apply
		await fireEvent.click(apply());
		await waitFor(() =>
			expect(api.resolveCase).toHaveBeenCalledWith(CASE_KEY, {
				resolutions: [
					{ flag_id: 'f1', resolution: { action: 'set_value', value: 'Trial 7.1 (warm-up run)', unit: null, illegible: false } },
					{ flag_id: 'f2', resolution: { action: 'set_value', value: 'Sample B-12 (lot 4', unit: null, illegible: false } }
				],
				rule_scope: null
			})
		);
		expect(await screen.findByText('Saved 2 answers for page 11.')).toBeTruthy();
	});

	it('Escape takes the reader’s value back and the entry is to check again', async () => {
		show();
		const first = screen.getByRole('textbox', { name: 'Trial Name' }) as HTMLInputElement;
		await fireEvent.input(first, { target: { value: 'typo' } });
		await fireEvent.keyDown(first, { key: 'Enter' });
		await fireEvent.keyDown(first, { key: 'Escape' });
		expect(first.value).toBe('Trial 7.1 (warm-up run');
		expect(screen.getByRole('status').textContent?.trim()).toBe('2 entries to check · 0 of 2 done');
	});

	it('never renders model text as HTML', () => {
		const unsafe = structuredClone(READING);
		unsafe.blocks[0].parts[1].rows![2][1] = cell('<img src=x onerror=alert(1)>');
		render(CaseView, { detail: detail([entryFlag('f1'), entryFlag('f2')], { page_reading: unsafe }), me: 'a', onChanged: () => {} });
		const page = screen.getByRole('region', { name: 'Page check' });
		expect(within(page).getByText('<img src=x onerror=alert(1)>')).toBeTruthy();
		expect(page.querySelector('img[src="x"]')).toBeNull(); // shown as text, never made an element
	});
});

// The case screen moves focus to its first answer once it has rendered; a person clicks after that.
const settled = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('correcting what the reader did not flag', () => {
	beforeEach(() => {
		sessionStorage.clear();
		vi.mocked(api.resolveCase).mockReset().mockResolvedValue({ case_key: CASE_KEY, flags: [], rule: null, resumed_doc_ids: [], proposed_files: 0 });
	});

	const answerBoth = async () => {
		await fireEvent.keyDown(screen.getByRole('textbox', { name: 'Trial Name' }), { key: 'Enter' });
		await fireEvent.keyDown(screen.getByRole('textbox', { name: 'Sample Name' }), { key: 'Enter' });
	};

	it('a cell is corrected on the page and sent with the answers', async () => {
		show();
		await settled();
		await fireEvent.click(screen.getByRole('cell', { name: /^Rig$/ }));
		const field = screen.getByRole('textbox', { name: 'Correct cell' }) as HTMLInputElement;
		expect(field.value).toBe('Rig');
		await fireEvent.input(field, { target: { value: 'Rig Bench' } });
		await fireEvent.keyDown(field, { key: 'Enter' });
		expect(screen.getByRole('cell', { name: 'Corrected: Rig Bench' })).toBeTruthy();
		expect(screen.getByRole('status').textContent).toContain('1 correction to save');
		await answerBoth();
		await fireEvent.click(screen.getByRole('button', { name: 'Apply page 11' }));
		await waitFor(() => expect(api.resolveCase).toHaveBeenCalledOnce());
		expect(vi.mocked(api.resolveCase).mock.calls[0][1].corrections).toEqual([
			{ action: 'set_cell', block_key: 'c909a46153e32d77', table: 0, row: 2, col: 0, old: 'Rig', value: 'Rig Bench' }
		]);
		expect(await screen.findByText('Saved 2 answers and 1 correction for page 11.')).toBeTruthy();
	});

	it('Escape leaves a cell as it was, and typing back what was read drops the correction', async () => {
		show();
		await settled();
		await fireEvent.click(screen.getByRole('cell', { name: /^Rig$/ }));
		let field = screen.getByRole('textbox', { name: 'Correct cell' });
		await fireEvent.input(field, { target: { value: 'x' } });
		await fireEvent.keyDown(field, { key: 'Escape' });
		expect(screen.queryByRole('textbox', { name: 'Correct cell' })).toBeNull();
		expect(screen.getByRole('status').textContent).not.toContain('correction');
		await fireEvent.click(screen.getByRole('cell', { name: /^Rig$/ }));
		field = screen.getByRole('textbox', { name: 'Correct cell' });
		await fireEvent.input(field, { target: { value: 'x' } });
		await fireEvent.keyDown(field, { key: 'Enter' });
		await fireEvent.click(screen.getByRole('cell', { name: 'Corrected: x' }));
		field = screen.getByRole('textbox', { name: 'Correct cell' });
		await fireEvent.input(field, { target: { value: 'Rig' } });
		await fireEvent.keyDown(field, { key: 'Enter' });
		expect(screen.getByRole('status').textContent).not.toContain('correction');
	});

	it('a heading or line is corrected the same way, and corrections alone can be applied', async () => {
		render(CaseView, {
			detail: detail([{ ...entryFlag('f1'), status: 'RESOLVED' }, { ...entryFlag('f2'), status: 'RESOLVED' }], { document_status: 'ACTIVE_WITH_SOFT_FLAGS', page_reading: READING }),
			me: 'a',
			onChanged: () => {}
		});
		await settled();
		await fireEvent.click(screen.getByRole('button', { name: 'Heading: Bench Heater Trial' }));
		const field = screen.getByRole('textbox', { name: 'Correct line' });
		await fireEvent.input(field, { target: { value: 'Bench Heater Trial 7.1' } });
		await fireEvent.keyDown(field, { key: 'Enter' });
		await fireEvent.click(screen.getByRole('button', { name: 'Apply page 11' }));
		await waitFor(() =>
			expect(api.resolveCase).toHaveBeenCalledWith(CASE_KEY, {
				resolutions: [],
				corrections: [{ action: 'set_text', block_key: 'c909a46153e32d77', old: 'Bench Heater Trial', text: 'Bench Heater Trial 7.1' }],
				rule_scope: null
			})
		);
	});
});

describe('page check helpers', () => {
	it('reads an entry state from its draft', () => {
		const entry = { value: 'a' };
		expect(entryState(entry, null)).toBe('to check');
		expect(entryState(entry, { action: 'set_value', value: 'a', illegible: false })).toBe('confirmed');
		expect(entryState(entry, { action: 'set_value', value: 'b', illegible: false })).toBe('corrected');
		expect(entryState(entry, { action: 'set_value', value: null, illegible: true })).toBe('unreadable');
	});

	it('gives an origin cell the span its covered positions point at', () => {
		const rows = [[cell('a'), cell('b'), cell('', [0, 1])], [cell('c'), cell('', [0, 1]), cell('', [0, 1])]];
		expect(spans(rows).get('0:1')).toEqual({ rowspan: 2, colspan: 2 });
		expect(spans(rows).get('0:0')).toEqual({ rowspan: 1, colspan: 1 });
	});

	it('splits text around what was crossed out', () => {
		expect(segments('old note 42.0 Ω', ['old note'])).toEqual([
			{ text: 'old note', struck: true },
			{ text: ' 42.0 Ω', struck: false }
		]);
	});
});
