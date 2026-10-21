// Resolution drafts for the case view (file 06 §6): which actions a flag offers, how a draft starts,
// when it is complete, and the rule a scoped resolution becomes.

import type { CaseLocation, FlagView, Resolution, ResolutionAction, RuleDraft, RuleScope, RuleType } from '$lib/api_endpoint';

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

/** The server computes what this user may do with the flag (S1 allowed_actions_for). */
export function allowedActions(flag: Pick<FlagView, 'allowed_actions'>): ResolutionAction[] {
	return flag.allowed_actions.filter((action): action is ResolutionAction => action in ACTION_LABEL);
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

/** A fresh draft for an action: the suggestion itself when it proposes this action, else blank fields. */
export function startDraft(action: ResolutionAction, flag: Pick<FlagView, 'anchor' | 'suggested_resolution'>): Resolution {
	const suggested = flag.suggested_resolution?.resolution;
	// A JSON copy: the case may be a Svelte state proxy, which structuredClone refuses.
	if (suggested && suggested.action === action) return JSON.parse(JSON.stringify(suggested)) as Resolution;
	switch (action) {
		case 'set_unit':
			return {
				action,
				channel: flag.anchor.channel || flag.anchor.column || '',
				unit: '',
				quantity: 'pressure',
				gauge_or_abs: 'unknown',
				ambient_condition: null,
				ambient_pressure_bar_abs: null,
				expression: null
			};
		case 'set_fact_unit':
			return { action, unit: null };
		case 'map_columns':
			return { action, columns: [{ index: 0, canonical_name: '', unit: null, quantity: null, is_time: true }] };
		case 'map_json_keys':
			return { action, key_to_section: {}, save_as_schema: null };
		case 'set_value':
			return { action, value: null, unit: null, illegible: false };
		case 'choose_table':
			return { action, choice: 'A', cells: null };
		case 'choose_source':
			return { action, choice: 'A' };
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

/** Where the case's file lives (first OneDrive location), for rule scopes. */
export type ScopeInfo = Pick<CaseLocation, 'root_name' | 'folder_id' | 'file_name' | 'extension'>;

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
	if (!where.folder_id) throw new Error('folder scope needs the folder id of the case');
	const scope: RuleScope = { scope_root: where.root_name, scope_folder_id: where.folder_id };
	if (choice === 'folder_pattern') {
		if (!pattern.trim()) throw new Error('enter a filename pattern');
		scope.scope_filename_glob = pattern.trim();
	}
	const { action: _action, ...body } = r;
	return { rule_type: ruleType, scope, body, precedence: 0 };
}
