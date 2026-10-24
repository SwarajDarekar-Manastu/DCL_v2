import type { CaseDetail, CaseSummary, FlagView } from '../../src/lib/api_endpoint';

export const DOC = '0b6f1d3e-2a4c-4e8f-9c1a-5d7e3f2b1a90';
export const CASE_KEY = `${DOC}:1`;

export function summary(overrides: Partial<CaseSummary> = {}): CaseSummary {
	return {
		case_key: CASE_KEY,
		doc_id: DOC,
		location_id: null,
		page_or_sheet: '1',
		title: 'Pressure_T07.dat',
		path: 'APU Heater/Test Plan 30/Pressure_T07.dat',
		root_name: 'APU Heater',
		route: 'C',
		status: 'OPEN',
		max_severity: 'HARD',
		flag_counts: { UNIT_AMBIGUITY: 1 },
		assignee: null,
		oldest_created_at: '2026-10-19T08:00:00Z',
		has_suggestion: true,
		has_rule_proposal: false,
		files_unblocked: 116,
		preview_asset_id: null,
		...overrides
	};
}

export function unitFlag(overrides: Partial<FlagView> = {}): FlagView {
	return {
		flag_id: 'flag-unit',
		fingerprint: 'fp1',
		flag_type: 'UNIT_AMBIGUITY',
		severity: 'HARD',
		status: 'OPEN',
		route: 'C',
		anchor: { channel: 'AIN0' },
		allowed_actions: ['set_unit', 'set_fact_unit'],
		evidence: {
			kind: 'unit_telemetry',
			channel: 'AIN0',
			raw_unit: 'psi',
			note: '',
			columns: [],
			sample_rows: [],
			series: [],
			quantity_guess: 'pressure',
			header_lines: ['Date 2026-03-14', 'Channels: Time AIN0 AIN1', 'Units: s psi V'],
			stats: { min: 0.2, max: 182.6, mean: 171.4, p50: 174.0, p99: 181.9, std: 9.1 },
			sparkline_uri: null,
			sanity: { quantity: 'pressure', unit: 'bar', min: 0, max: 30 },
			candidate_units: [
				{ unit: 'psi', gauge_or_abs: 'gauge', score: 0.71, reason: 'sea-level folder, sibling .cfg says psig' },
				{ unit: 'psi', gauge_or_abs: 'absolute', score: 0.22, reason: 'header says psi' }
			],
			sibling_units: [{ file_name: 'T07.cfg', channel: 'AIN0', unit: 'psig', source: 'cfg' }]
		},
		suggested_resolution: {
			resolution: {
				action: 'set_unit',
				channel: 'AIN0',
				unit: 'psi',
				quantity: 'pressure',
				gauge_or_abs: 'gauge',
				ambient_condition: 'SEA_LEVEL',
				ambient_pressure_bar_abs: 1.01325,
				expression: null
			},
			confidence: 0.71,
			rationale: 'Sibling T07.cfg declares psig at sea level.',
			proposed_by: 'heuristic'
		},
		resolution: null,
		resolution_rule_id: null,
		proposed_by_rule_id: null,
		assigned_to: null,
		resolved_by: null,
		resolved_at: null,
		due_at: null,
		created_at: '2026-10-19T08:00:00Z',
		...overrides
	};
}

export function detail(flags: FlagView[] = [unitFlag()], overrides: Partial<CaseDetail> = {}): CaseDetail {
	return {
		summary: summary(),
		flags,
		document_status: 'HALTED',
		locations: [
			{
				root_name: 'APU Heater',
				path: 'APU Heater/Test Plan 30/Pressure_T07.dat',
				web_url: 'https://onedrive.example/folder',
				folder_id: 'FOLDER-TP30',
				file_name: 'Pressure_T07.dat',
				extension: '.dat'
			}
		],
		siblings: ['T07.cfg'],
		applied_units: [],
		...overrides
	};
}

/** A CONFLICT flag: two sources that disagree (the default), a failed check or a note. */
export function conflictFlag(overrides: Partial<FlagView> = {}, relation: 'sources_disagree' | 'check_failed' | 'note' = 'sources_disagree'): FlagView {
	return unitFlag({
		flag_id: 'flag-conflict',
		flag_type: 'CONFLICT',
		severity: 'SOFT',
		route: 'B',
		anchor: {},
		allowed_actions: ['choose_source', 'mark_superseded', 'accept_both', 'ignore'],
		evidence: {
			kind: 'conflict',
			relation,
			subject: 'test_plan_id',
			a: { label: 'folder', value: 'TP-30', provenance: 'folder name Test Plan 30' },
			b: relation === 'sources_disagree' ? { label: 'content', value: 'TP-31', provenance: 'page 1 header' } : null
		},
		suggested_resolution: null,
		...overrides
	});
}

/** A SOFT UNIT_AMBIGUITY on a number in a table or prose (not a telemetry channel). */
export function factUnitFlag(overrides: Partial<FlagView> = {}): FlagView {
	return unitFlag({
		flag_id: 'flag-fact',
		severity: 'SOFT',
		route: 'A1',
		anchor: { column: 'Pressure (A)', sheet: 'Results' },
		allowed_actions: ['set_fact_unit'],
		evidence: { kind: 'unit_fact', value_raw: '182.6', context: 'Peak chamber pressure, Test 01: Pressure (A)', candidate_units: [] },
		suggested_resolution: null,
		...overrides
	});
}

/** SCHEMA_UNKNOWN on a JSON file. */
export function jsonSchemaFlag(overrides: Partial<FlagView> = {}): FlagView {
	return unitFlag({
		flag_id: 'flag-json',
		flag_type: 'SCHEMA_UNKNOWN',
		severity: 'HARD',
		route: 'A2',
		anchor: {},
		allowed_actions: ['map_json_keys', 'skip'],
		evidence: { kind: 'json_schema', top_level_keys: ['summary', 'results'], missing_keys: [], flattened_sample: [], closest_schema: null },
		suggested_resolution: null,
		...overrides
	});
}
