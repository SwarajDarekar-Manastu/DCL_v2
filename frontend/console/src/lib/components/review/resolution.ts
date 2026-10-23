// Resolution drafts for the case view (file 06 §6): which actions a flag offers, how a draft starts,
// when it is complete, and the rule a scoped resolution becomes.

import type { CaseLocation, FlagView, Resolution, ResolutionAction, RuleScope } from '$lib/api_endpoint';

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

/** Actions the server allows but the console cannot carry out yet: never offered. */
export const NOT_BUILT: readonly ResolutionAction[] = ['use_replacement', 'redact'];

type ConflictEvidence = Extract<NonNullable<FlagView['evidence']>, { kind: 'conflict' }>;

function conflictOf(flag: Partial<Pick<FlagView, 'evidence'>>): ConflictEvidence | null {
	return flag.evidence?.kind === 'conflict' ? flag.evidence : null;
}

/** The documents a "mark superseded" can name: the sides of a disagreement that are documents. */
export function supersedable(flag: Partial<Pick<FlagView, 'evidence'>>): { doc_id: string; label: string }[] {
	const conflict = conflictOf(flag);
	if (!conflict || conflict.relation !== 'sources_disagree') return [];
	return [conflict.a, conflict.b].flatMap((side) => (side?.doc_id ? [{ doc_id: side.doc_id, label: side.label }] : []));
}

/**
 * What this user may do with the flag: the server's list (S1 allowed_actions_for), minus what the console
 * cannot do yet, minus what does not fit the kind of conflict: a failed check or a note has no source to pick
 * and no document to supersede.
 */
export function allowedActions(flag: Pick<FlagView, 'allowed_actions'> & Partial<Pick<FlagView, 'evidence'>>): ResolutionAction[] {
	const conflict = conflictOf(flag);
	return flag.allowed_actions.filter((action): action is ResolutionAction => {
		if (!(action in ACTION_LABEL) || NOT_BUILT.includes(action as ResolutionAction)) return false;
		if (!conflict) return true;
		if (conflict.relation !== 'sources_disagree') return action === 'accept_both' || action === 'ignore';
		return action !== 'mark_superseded' || supersedable(flag).length > 0;
	});
}

/** The label of an action for this flag: on a failed check or a note "accept both" reads "Accept as it is". */
export function actionLabel(action: ResolutionAction, flag: Pick<FlagView, 'evidence'>): string {
	const conflict = conflictOf(flag);
	if (conflict && conflict.relation !== 'sources_disagree' && action === 'accept_both') return 'Accept as it is';
	return ACTION_LABEL[action];
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

/** Only a unit decision can be proposed to other files: that is the one kind of rule a route fills in from. */
export function canBecomeRule(action: ResolutionAction): boolean {
	return action === 'set_unit';
}

/** The scope a case's unit decisions are also proposed under: null is "no other file". */
export function caseRuleScope(choice: ScopeChoice, where: ScopeInfo, pattern = ''): RuleScope | null {
	if (choice === 'file') return null;
	if (!where.folder_id) throw new Error('folder scope needs the folder id of the case');
	const scope: RuleScope = { scope_root: where.root_name, scope_folder_id: where.folder_id };
	if (choice === 'folder_pattern') {
		if (!pattern.trim()) throw new Error('enter a filename pattern');
		scope.scope_filename_glob = pattern.trim();
	}
	return scope;
}
