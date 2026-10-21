// Resolution drafts for the case view (file 06 §6): which actions a flag offers, how a draft starts,
// when it is complete, and the rule a scoped resolution becomes.

import type { FlagType, FlagView, Resolution, ResolutionAction, RuleDraft, RuleScope, RuleType } from '$lib/api_endpoint';

/**
 * TEMPORARY mirror of backend/review/api_models.py ALLOWED_ACTIONS (S1, 9fda653), because it is not in
 * the OpenAPI schema. Replace with FlagView.allowed_actions once S1 adds it (requested 2026-10-21).
 */
export const ALLOWED_ACTIONS: Record<FlagType, ResolutionAction[]> = {
	UNIT_AMBIGUITY: ['set_unit', 'set_fact_unit'],
	SCHEMA_UNKNOWN: ['map_columns', 'map_json_keys', 'mark_junk'],
	LOW_CONFIDENCE_EXTRACTION: ['set_value', 'choose_table'],
	PARSE_FAILURE: ['use_replacement', 'skip', 'mark_junk'],
	UNSUPPORTED_FORMAT: ['skip', 'mark_junk', 'watch'],
	CONFLICT: ['choose_source', 'mark_superseded', 'accept_both', 'ignore'],
	SENSITIVE_CONTENT: ['redact', 'approve_internal', 'exclude'],
	HELD_LARGE_FILE: ['approve_download', 'skip'],
	CLOUD_RESTRICTED: ['ignore']
};
export const ADMIN_ONLY_ACTIONS: ResolutionAction[] = ['approve_internal'];

export const ACTION_LABEL: Record<ResolutionAction, string> = {
	set_unit: 'Set channel unit',
	set_fact_unit: 'Set unit of the number',
	map_columns: 'Map columns',
	map_json_keys: 'Map JSON keys',
	set_value: 'Type the value',
	choose_table: 'Choose table version',
	choose_source: 'Pick the authoritative source',
	mark_superseded: 'Mark a document superseded',
	accept_both: 'Accept both',
	ignore: 'Ignore',
	use_replacement: 'Use an uploaded readable copy',
	redact: 'Redact',
	approve_internal: 'Approve for internal indexing',
	approve_download: 'Approve download',
	watch: 'Notify when an adapter exists',
	skip: 'Skip file',
	mark_junk: 'Mark junk',
	exclude: 'Exclude permanently'
};

export function allowedActions(flag: Pick<FlagView, 'flag_type'>, isAdmin: boolean): ResolutionAction[] {
	return ALLOWED_ACTIONS[flag.flag_type].filter((action) => isAdmin || !ADMIN_ONLY_ACTIONS.includes(action));
}

/** Pressure units offered for UNIT_AMBIGUITY on telemetry (file 06 §6), as unit + gauge/abs. */
export const PRESSURE_CHOICES = [
	{ label: 'psig', unit: 'psi', gauge_or_abs: 'gauge' },
	{ label: 'psia', unit: 'psi', gauge_or_abs: 'absolute' },
	{ label: 'bar(g)', unit: 'bar', gauge_or_abs: 'gauge' },
	{ label: 'bar(a)', unit: 'bar', gauge_or_abs: 'absolute' },
	{ label: 'kPa (gauge)', unit: 'kPa', gauge_or_abs: 'gauge' },
	{ label: 'kPa (abs)', unit: 'kPa', gauge_or_abs: 'absolute' },
	{ label: 'kgf/cm²', unit: 'kgf/cm**2', gauge_or_abs: 'gauge' },
	{ label: 'mV raw', unit: 'mV', gauge_or_abs: 'n/a' }
] as const;

type Suggestion = Record<string, unknown> | null | undefined;

const str = (v: unknown) => (typeof v === 'string' ? v : '');

/** A fresh draft for an action, prefilled from the flag's suggestion and anchor where they fit. */
export function startDraft(action: ResolutionAction, flag: Pick<FlagView, 'anchor' | 'suggested_resolution'>): Resolution {
	const s: Suggestion = flag.suggested_resolution;
	const fromSuggestion = s && s.action === action ? s : {};
	switch (action) {
		case 'set_unit':
			return {
				action,
				channel: str(fromSuggestion.channel) || flag.anchor.channel || flag.anchor.column || '',
				unit: str(fromSuggestion.unit),
				quantity: str(fromSuggestion.quantity) || 'pressure',
				gauge_or_abs: (str(fromSuggestion.gauge_or_abs) || 'unknown') as 'unknown',
				ambient_condition: null,
				ambient_pressure_bar_abs: null,
				expression: null
			};
		case 'set_fact_unit':
			return { action, unit: str(fromSuggestion.unit) || null };
		case 'map_columns': {
			const columns = Array.isArray(fromSuggestion.columns) ? fromSuggestion.columns : [];
			return { action, columns: columns.length ? (columns as never) : [{ index: 0, canonical_name: '', unit: null, quantity: null, is_time: true }] };
		}
		case 'map_json_keys':
			return { action, key_to_section: (fromSuggestion.key_to_section as Record<string, string>) ?? {}, save_as_schema: null };
		case 'set_value':
			return { action, value: str(fromSuggestion.value) || null, unit: str(fromSuggestion.unit) || null, illegible: false };
		case 'choose_table':
			return { action, choice: 'A', cells: null };
		case 'choose_source':
			return { action, choice: (str(fromSuggestion.choice) || 'A') as 'A' };
		case 'mark_superseded':
			return { action, superseded_doc_id: '' };
		case 'use_replacement':
			return { action, replacement_blob_sha256: '' };
		case 'redact':
			return { action, regions: [] };
		default:
			return { action } as Resolution;
	}
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** What is still missing before the draft can be sent, or null when it is complete. */
export function missing(r: Resolution): string | null {
	switch (r.action) {
		case 'set_unit':
			if (!r.channel) return 'channel';
			if (!r.unit && !r.expression) return 'a unit or a conversion expression';
			if (!r.quantity) return 'quantity';
			if (r.gauge_or_abs === 'gauge' && !r.ambient_condition) return 'the ambient reference for a gauge unit';
			return null;
		case 'map_columns':
			if (!r.columns.length) return 'at least one column';
			if (r.columns.some((c) => !c.canonical_name.trim())) return 'a canonical name for every column';
			if (new Set(r.columns.map((c) => c.index)).size !== r.columns.length) return 'distinct column indexes';
			if (r.columns.filter((c) => c.is_time).length > 1) return 'at most one time column';
			return null;
		case 'map_json_keys':
			return Object.keys(r.key_to_section).length ? null : 'at least one key';
		case 'set_value':
			return r.illegible || (r.value ?? '').trim() ? null : 'a value, or mark it illegible';
		case 'choose_table':
			return r.choice === 'edited' && !r.cells?.length ? 'the edited cells' : null;
		case 'mark_superseded':
			return UUID.test(r.superseded_doc_id) ? null : 'the superseded document id';
		case 'use_replacement':
			return /^[0-9a-f]{64}$/.test(r.replacement_blob_sha256) ? null : 'an uploaded replacement';
		case 'redact':
			return r.regions.length ? null : 'at least one region';
		default:
			return null;
	}
}

/** Actions whose effect on numbers must be previewed (dry-run) before they can be applied. */
export function needsPreview(action: ResolutionAction): boolean {
	return action === 'set_unit' || action === 'map_columns';
}

export type ScopeChoice = 'file' | 'folder' | 'folder_pattern';

/** Where a case lives, for rule scopes (S1 to add these to CaseDetail; until then folder scopes are unavailable). */
export interface ScopeInfo {
	scope_root?: string | null;
	scope_folder_id?: string | null;
	file_name?: string | null;
	extension?: string | null;
}

const RULE_TYPE: Partial<Record<ResolutionAction, RuleType>> = {
	set_unit: 'unit_mapping',
	map_columns: 'schema_mapping'
};

export function canBecomeRule(action: ResolutionAction): boolean {
	return action in RULE_TYPE;
}

/** The operator rule a scoped resolution creates; null for "this file only". */
export function ruleFor(r: Resolution, choice: ScopeChoice, where: ScopeInfo, pattern = ''): RuleDraft | null {
	const ruleType = RULE_TYPE[r.action];
	if (!ruleType || choice === 'file') return null;
	if (!where.scope_folder_id) throw new Error('folder scope needs the folder id of the case');
	const scope: RuleScope = { scope_root: where.scope_root ?? null, scope_folder_id: where.scope_folder_id };
	if (choice === 'folder_pattern') {
		if (!pattern.trim()) throw new Error('enter a filename pattern');
		scope.scope_filename_glob = pattern.trim();
	}
	const { action: _action, ...body } = r;
	return { rule_type: ruleType, scope, body, precedence: 0 };
}
