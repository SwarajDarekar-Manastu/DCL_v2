import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import ChannelMapView from '../../src/lib/components/review/ChannelMapView.svelte';
import { channelRows, choiceFor, displayRange, isChannelMapCase, setUnit, sourceTable, sparkPath, unitSymbol } from '../../src/lib/components/review/channel_map';
import { detail, unitFlag } from './fixtures';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return { ...real, dryRun: vi.fn(), resolveCase: vi.fn(), previewRule: vi.fn() };
});

// Shaped on the real halted LabJack run Test_01_02Bar_i_0 (Injector 14 flow test): columns and header from the
// file, min/max per channel from its evidence; sample values inside those ranges.
const COLUMNS = ['Time', 'v0', 'v1', 'v2', 'v3', 'v4', 'v5', 'v6', 'v7', 'y0', 'y1', 'y2', 'y3', 'y4', 'y5', 'y6', 'y7'];
const RANGES: [number, number][] = [[1.858, 2.161], [1.945, 2.236], [0.866, 5.289], [-30.063, -29.866], [-25.334, -25.093], [-0.11, 45.147], [-7.89, 0.597], [-11.012, 5.324]];
const ROWS = Array.from({ length: 20 }, (_, i) => [i * 0.5, ...Array(8).fill(0.01 * i), ...RANGES.map(([lo, hi]) => +(lo + ((hi - lo) * i) / 19).toFixed(4))]);
const evidence = (k: number) => ({
	kind: 'unit_telemetry' as const,
	channel: `y${k}`,
	raw_unit: null,
	quantity_guess: null,
	header_lines: ['13-01-2026', '17:22:50', '', '', '', COLUMNS.join('\t')],
	scaling_equation: null,
	scaling_source: null,
	note: 'the file states no unit',
	stats: { n: 42500, min: RANGES[k][0], max: RANGES[k][1], mean: null, p50: null, p99: null, std: null },
	sparkline_uri: null,
	candidate_units: [],
	sibling_units: [],
	sanity: null,
	columns: COLUMNS,
	column_index: 9 + k,
	sample_rows: ROWS,
	time_column: 'Time',
	series: [[0, RANGES[k][0]], [10, null], [20, (RANGES[k][0] + RANGES[k][1]) / 2], [30, RANGES[k][1]]] as [number, number | null][]
});
const flags = [7, 0, 3, 1, 2, 4, 5, 6].map((k) =>
	unitFlag({
		flag_id: `flag-y${k}`,
		anchor: { channel: `y${k}` },
		evidence: evidence(k),
		suggested_resolution:
			k === 0
				? {
						resolution: { action: 'set_unit', channel: 'y0', unit: 'bar', quantity: 'pressure', gauge_or_abs: 'gauge', ambient_condition: null, ambient_pressure_bar_abs: null, expression: null },
						confidence: 0.71,
						rationale: 'sibling CSV',
						proposed_by: 'heuristic'
					}
				: { resolution: null, confidence: 0, rationale: 'no suggestion', proposed_by: 'heuristic' }
	})
);
const LABJACK = detail(flags);

beforeEach(() => {
	vi.mocked(api.dryRun).mockReset();
	vi.mocked(api.resolveCase).mockReset();
	vi.mocked(api.previewRule).mockReset();
});

describe('channel map logic', () => {
	it('takes the open telemetry unit flags in file column order', () => {
		expect(isChannelMapCase(LABJACK)).toBe(true);
		expect(isChannelMapCase(detail([unitFlag()]))).toBe(false);
		expect(channelRows(LABJACK).map((r) => r.channel)).toEqual(['y0', 'y1', 'y2', 'y3', 'y4', 'y5', 'y6', 'y7']);
	});

	it('preselects the suggestion and builds set_unit with the shared ambient for gauge units', () => {
		const [y0, y1] = channelRows(LABJACK);
		const choice = choiceFor(y0)!;
		expect([choice.label, choiceFor(y1)]).toEqual(['bar (gauge)', null]);
		expect(setUnit(y0, choice, 'SEA_LEVEL')).toMatchObject({ channel: 'y0', unit: 'bar', gauge_or_abs: 'gauge', ambient_condition: 'SEA_LEVEL', quantity: 'pressure' });
	});

	it('reads the file table, and falls back to the header line without sample rows', () => {
		const ev = evidence(0);
		expect(sourceTable(ev)).toEqual({ columns: COLUMNS, rows: ROWS });
		expect(sourceTable({ ...ev, columns: [], sample_rows: [] })).toEqual({ columns: COLUMNS, rows: [] });
	});

	it('shows units as symbols, temperatures in °C', () => {
		expect(displayRange(-0.11019, 45.147, 'kilogram * meter ** 2 / ampere / second ** 3')).toBe('-0.11019 … 45.147 V');
		expect(displayRange(1.858, 2.161, 'bar')).toBe('1.858 … 2.161 bar');
		expect(displayRange(293.15, 373.15, 'kelvin')).toBe('20 … 100 °C');
		expect([unitSymbol('gram / second'), unitSymbol('newton'), unitSymbol('meter ** 2 * kilogram / second ** 2')]).toEqual(['g/s', 'N', 'meter²·kilogram/second²']);
	});

	it('draws the series and breaks the line at gaps', () => {
		expect(sparkPath([[0, 1], [10, null], [20, 2], [30, 3]], 30, 10)).toBe('M0.0,9.0M20.0,5.0L30.0,1.0');
		expect(sparkPath([[0, 1]])).toBe('');
	});
});

describe('ChannelMapView', () => {
	it('explains the case, boxes the selected channel column and lists every channel', async () => {
		render(ChannelMapView, { detail: LABJACK, onChanged: vi.fn(), onDetails: vi.fn() });
		expect(screen.getByRole('status').textContent).toContain('This file has 8 columns with no unit. Pick the unit for each so processing can continue.');
		expect(screen.getByTitle(/A channel is one column/)).toBeTruthy();
		const source = screen.getByRole('table', { name: 'Source rows' });
		expect(source.querySelector('[data-boxed]')?.textContent).toBe('y0');
		const rows = within(screen.getByRole('table', { name: 'Channels' })).getAllByRole('row').slice(1);
		expect(rows.map((r) => r.querySelector('td')?.textContent)).toEqual(['y0', 'y1', 'y2', 'y3', 'y4', 'y5', 'y6', 'y7'].map((c) => `${c}HARD`.replace('HARD', ' HARD')));
		await fireEvent.click(rows[5]);
		expect(source.querySelector('[data-boxed]')?.textContent).toBe('y5');
		expect((screen.getByLabelText('Unit of y0') as HTMLSelectElement).value).toBe('bar_g');
		expect(screen.getByText('suggested · confidence 71%')).toBeTruthy();
		expect(screen.getAllByRole('img', { name: /Values of y\d over the run/ })).toHaveLength(8);
	});

	it('previews every chosen channel, then applies them all in one resolve', async () => {
		vi.mocked(api.dryRun).mockImplementation(async (body) => ({
			affected_documents: 1,
			channels: [{ canonical_name: body.resolution.resolution.action === 'set_unit' ? body.resolution.resolution.channel : '', unit_si: 'bar', stat_min: 2.86, stat_max: 3.17, stat_mean: null, stat_p99: null, sanity_min: 0, sanity_max: 1e7, within_sanity: true }],
			messages: [],
			new_flags: [],
			preview: null
		}) as unknown as api.DryRunResponse);
		vi.mocked(api.resolveCase).mockResolvedValue({ case_key: 'k', flags: [], rule: null, resumed_doc_ids: ['d'] } as unknown as api.ResolveResponse);
		const onChanged = vi.fn();
		render(ChannelMapView, { detail: LABJACK, onChanged, onDetails: vi.fn() });
		await fireEvent.change(screen.getByLabelText('Unit of y1'), { target: { value: 'bar_a' } });
		expect(screen.getByRole('button', { name: /Apply all and resume/ }).hasAttribute('disabled')).toBe(true);
		expect(screen.getByLabelText(/Gauge readings are relative to/)).toBeTruthy(); // y0 is gauge
		await fireEvent.click(screen.getByRole('button', { name: 'Preview all' }));
		await waitFor(() => expect(api.dryRun).toHaveBeenCalledTimes(2));
		expect(await screen.findAllByText('2.86 … 3.17 bar')).toHaveLength(2);
		await fireEvent.click(screen.getByRole('button', { name: /Apply all and resume/ }));
		await waitFor(() => expect(api.resolveCase).toHaveBeenCalledTimes(1));
		const [key, body] = vi.mocked(api.resolveCase).mock.calls[0];
		expect(key).toBe(LABJACK.summary.case_key);
		expect(body.resolutions.map((r) => [r.flag_id, r.resolution.action === 'set_unit' && r.resolution.unit, r.resolution.action === 'set_unit' && r.resolution.ambient_condition])).toEqual([
			['flag-y0', 'bar', 'SEA_LEVEL'],
			['flag-y1', 'bar', null]
		]);
		expect(await screen.findByText('Approved the units of 2 channels. This file is resuming.')).toBeTruthy();
		expect(onChanged).toHaveBeenCalled();
	});

	it('approves this file and also proposes its units to the folder, saying how many files it reaches', async () => {
		const dryRunResult = {
			affected_documents: 1,
			channels: [{ canonical_name: 'y0', unit_si: 'bar', stat_min: 1, stat_max: 2, stat_mean: null, stat_p99: null, sanity_min: 0, sanity_max: 1e7, within_sanity: true }],
			messages: [],
			new_flags: [],
			preview: null
		} as unknown as api.DryRunResponse;
		vi.mocked(api.dryRun).mockResolvedValue(dryRunResult);
		vi.mocked(api.previewRule).mockResolvedValue({ matched_documents: 12, waiting_documents: 12, finished_documents: 0, sample: [], effect: 'proposes', resolves_flags: 0, open_channels: [], problem: null });
		vi.mocked(api.resolveCase).mockResolvedValue({ case_key: 'k', flags: [], rule: null, resumed_doc_ids: ['d'] } as unknown as api.ResolveResponse);
		render(ChannelMapView, { detail: LABJACK, onChanged: vi.fn(), onDetails: vi.fn() });
		expect(screen.getByText(/Only this file is decided/)).toBeTruthy();
		await fireEvent.change(screen.getByLabelText('Unit of y1'), { target: { value: 'bar_a' } });
		await fireEvent.click(screen.getByRole('radio', { name: /the other files in this folder/ }));
		expect(await screen.findByText(/it reaches 12 files, 12 waiting/)).toBeTruthy();
		expect(vi.mocked(api.previewRule).mock.calls[0][0]).toEqual({
			rule_type: 'channel_proposal',
			scope: { scope_root: 'APU Heater', scope_folder_id: 'FOLDER-TP30' }
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Preview all' }));
		await waitFor(() => expect(api.dryRun).toHaveBeenCalled());
		await fireEvent.click(await screen.findByRole('button', { name: /Apply all and resume/ }));
		await waitFor(() => expect(api.resolveCase).toHaveBeenCalledOnce());
		expect(vi.mocked(api.resolveCase).mock.calls[0][1].rule_scope).toEqual({ scope_root: 'APU Heater', scope_folder_id: 'FOLDER-TP30' });
	});

	describe('when a rule proposes units', () => {
		const rationale = 'proposed by a rule that asha saved on 2026-10-23; check it against this file';
		const proposed = detail(
			[0, 1, 2].map((k) =>
				unitFlag({
					flag_id: `flag-y${k}`,
					anchor: { channel: `y${k}` },
					evidence: evidence(k),
					proposed_by_rule_id: 'rule-1',
					suggested_resolution:
						k < 2
							? {
									resolution: { action: 'set_unit', channel: `y${k}`, unit: 'bar', quantity: 'pressure', gauge_or_abs: 'absolute', ambient_condition: null, ambient_pressure_bar_abs: null, expression: null, canonical_name: `pt_10${k}` },
									confidence: 0.85,
									rationale,
									proposed_by: 'rule'
								}
							: { resolution: null, confidence: 0, rationale: 'no suggestion', proposed_by: 'heuristic' }
				})
			)
		);
		const converted = (within: boolean | ((c: string) => boolean) = true) =>
			vi.mocked(api.dryRun).mockImplementation(async (body) => {
				const channel = body.resolution.resolution.action === 'set_unit' ? body.resolution.resolution.channel : '';
				return {
					affected_documents: 1,
					channels: [{ canonical_name: channel, unit_si: 'bar', stat_min: 1.9, stat_max: 2.2, stat_mean: null, stat_p99: null, sanity_min: 0, sanity_max: 30, within_sanity: typeof within === 'function' ? within(channel) : within }],
					messages: [],
					new_flags: [],
					preview: null
				} as unknown as api.DryRunResponse;
			});

		it('shows who proposed it, checks the numbers at once and applies only the proposed columns', async () => {
			converted();
			vi.mocked(api.resolveCase).mockResolvedValue({ case_key: 'k', flags: [], rule: null, resumed_doc_ids: ['d'], proposed_files: 0 } as unknown as api.ResolveResponse);
			render(ChannelMapView, { detail: proposed, onChanged: vi.fn(), onDetails: vi.fn(), onReject: vi.fn() });
			expect(screen.getByRole('region', { name: 'Proposed by a rule' }).textContent).toContain('A rule proposes the units of 2 of 3 columns.');
			expect(screen.getByText(/Proposed by a rule that asha saved on 2026-10-23/)).toBeTruthy();
			expect(screen.getAllByText('proposed by a rule')).toHaveLength(2);
			await waitFor(() => expect(api.dryRun).toHaveBeenCalledTimes(2)); // the numbers are shown without a click
			const button = await screen.findByRole('button', { name: 'Apply proposed rule (2 of 3 columns)' });
			await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));

			await fireEvent.click(button);
			await waitFor(() => expect(api.resolveCase).toHaveBeenCalledOnce());
			const body = vi.mocked(api.resolveCase).mock.calls[0][1];
			expect(body.resolutions.map((r) => [r.flag_id, r.resolution.action === 'set_unit' && r.resolution.canonical_name])).toEqual([
				['flag-y0', 'pt_100'],
				['flag-y1', 'pt_101']
			]);
			expect(await screen.findByText(/Approved the units of 2 channels. This file is resuming./)).toBeTruthy();
		});

		it('will not apply numbers that look wrong once converted, and says which', async () => {
			converted((channel) => channel !== 'y1');
			render(ChannelMapView, { detail: proposed, onChanged: vi.fn(), onDetails: vi.fn(), onReject: vi.fn() });
			expect(await screen.findByText(/These look wrong once converted: y1/)).toBeTruthy();
			const button = screen.getByRole('button', { name: /Apply proposed rule/ }) as HTMLButtonElement;
			expect(button.disabled).toBe(true);
			expect(api.resolveCase).not.toHaveBeenCalled();
		});

		it('hands over to "Apply all and resume" once a proposed unit is changed, and can go back', async () => {
			converted();
			render(ChannelMapView, { detail: proposed, onChanged: vi.fn(), onDetails: vi.fn(), onReject: vi.fn() });
			await waitFor(() => expect(api.dryRun).toHaveBeenCalledTimes(2));
			await fireEvent.change(screen.getByLabelText('Unit of y0'), { target: { value: 'psia' } });
			expect(screen.queryByRole('button', { name: /Apply proposed rule/ })).toBeNull();
			expect(screen.getByText(/You changed a proposed unit/)).toBeTruthy();
			await fireEvent.click(screen.getByRole('button', { name: 'Back to the proposed units' }));
			expect((screen.getByLabelText('Unit of y0') as HTMLSelectElement).value).toBe('bar_a');
			expect(await screen.findByRole('button', { name: /Apply proposed rule/ })).toBeTruthy();
		});

		it('lets the reviewer skip the file instead', async () => {
			converted();
			const onReject = vi.fn();
			render(ChannelMapView, { detail: proposed, onChanged: vi.fn(), onDetails: vi.fn(), onReject });
			await fireEvent.click(screen.getByRole('button', { name: 'Skip file' }));
			expect(onReject).toHaveBeenCalledWith('skip');
		});

		it('keeps the file halted when no rule proposes anything: no banner, no proposed-rule button', () => {
			render(ChannelMapView, { detail: LABJACK, onChanged: vi.fn(), onDetails: vi.fn(), onReject: vi.fn() });
			expect(screen.queryByRole('region', { name: 'Proposed by a rule' })).toBeNull();
			expect(screen.queryByRole('button', { name: /Apply proposed rule/ })).toBeNull();
			expect(screen.getByRole('button', { name: 'Skip file' })).toBeTruthy();
		});
	});

	it('keeps the per-flag details reachable', async () => {
		const onDetails = vi.fn();
		render(ChannelMapView, { detail: LABJACK, onChanged: vi.fn(), onDetails });
		await fireEvent.click(screen.getByRole('button', { name: 'Show per-flag details' }));
		expect(onDetails).toHaveBeenCalled();
	});
});
