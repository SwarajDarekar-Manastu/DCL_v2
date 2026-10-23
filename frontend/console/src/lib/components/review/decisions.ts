// What was decided on a file, and how a unit decision is edited (the Audit page, DECISIONS 2026-10-24).
// Data: the case detail the review page already loads; nothing here talks to the server.

import type { CaseDetail, FlagView, Resolution } from '$lib/api_endpoint';
import { UNIT_GROUPS, type Ambient, type UnitChoice } from './channel_map';

type SetUnit = Extract<Resolution, { action: 'set_unit' }>;

const ALL: UnitChoice[] = UNIT_GROUPS.flatMap((g) => g.choices);
const DECIDED = new Set(['RESOLVED', 'REJECTED_FILE', 'AUTO_RESOLVED']);
const OPEN = new Set(['OPEN', 'IN_PROGRESS', 'REOPENED']);

/** A rule applied this unit and no person has checked it (the old flow, before rules only proposed). */
export interface AppliedBy {
	ruleBy: string;
	ruleAt: string;
	ruleActive: boolean;
}

export interface UnitDecision {
	flag: FlagView;
	channel: string;
	resolution: SetUnit;
	/** the entry of the unit list the stored unit matches, '' when it is not in the list */
	choiceId: string;
	label: string;
	name: string;
	decidedBy: string | null;
	decidedAt: string | null;
	proposedByRule: string | null;
	/** set when no person decided this unit: a rule applied it */
	appliedBy: AppliedBy | null;
}

export interface Edit {
	choiceId: string;
	name: string;
}

const isUnit = (f: FlagView): boolean =>
	f.flag_type === 'UNIT_AMBIGUITY' && f.status === 'RESOLVED' && !!f.anchor.channel && f.resolution?.action === 'set_unit';

const columnOrder = (f: FlagView): number => (f.evidence?.kind === 'unit_telemetry' ? (f.evidence.column_index ?? Number.MAX_SAFE_INTEGER) : Number.MAX_SAFE_INTEGER);

export function choiceOfResolution(r: SetUnit): UnitChoice | null {
	return ALL.find((c) => c.unit === r.unit && c.gauge_or_abs === r.gauge_or_abs) ?? null;
}

/** The unit in words: the list's label when it is in the list, else what is stored. */
export function unitLabel(r: SetUnit): string {
	return choiceOfResolution(r)?.label ?? `${r.unit}${r.gauge_or_abs === 'gauge' || r.gauge_or_abs === 'absolute' ? ` (${r.gauge_or_abs})` : ''}`;
}

/** The decided telemetry unit flags of the case, in the file's column order. A unit a rule applied without a
 * person (flag closed by the pipeline) is listed too, marked, so a person can confirm or correct it. */
export function unitDecisions(detail: Pick<CaseDetail, 'flags'> & Partial<Pick<CaseDetail, 'applied_units'>>): UnitDecision[] {
	const applied = new Map((detail.applied_units ?? []).map((u) => [u.flag_id, u]));
	const rows: UnitDecision[] = [];
	for (const flag of detail.flags) {
		const auto = flag.status === 'AUTO_RESOLVED' ? applied.get(flag.flag_id) : undefined;
		if (!isUnit(flag) && !auto) continue;
		const resolution: SetUnit = auto
			? {
					action: 'set_unit',
					channel: auto.channel,
					unit: auto.unit,
					quantity: auto.quantity,
					gauge_or_abs: auto.gauge_or_abs as SetUnit['gauge_or_abs'],
					ambient_condition: (auto.ambient_condition as SetUnit['ambient_condition']) ?? null,
					ambient_pressure_bar_abs: null,
					expression: null,
					canonical_name: auto.canonical_name
				}
			: (flag.resolution as SetUnit);
		rows.push({
			flag,
			channel: flag.anchor.channel!,
			resolution,
			choiceId: choiceOfResolution(resolution)?.id ?? '',
			label: unitLabel(resolution),
			name: resolution.canonical_name ?? flag.anchor.channel!,
			decidedBy: auto ? null : (flag.resolved_by ?? null),
			decidedAt: auto ? null : (flag.resolved_at ?? null),
			proposedByRule: flag.proposed_by_rule_id ?? null,
			appliedBy: auto ? { ruleBy: auto.rule_created_by, ruleAt: auto.rule_created_at, ruleActive: auto.rule_active } : null
		});
	}
	return rows.sort((a, b) => columnOrder(a.flag) - columnOrder(b.flag) || a.channel.localeCompare(b.channel, undefined, { numeric: true }));
}

/** Decided flags that are not telemetry units: each can be reopened so the file is decided again. */
export function otherDecisions(detail: Pick<CaseDetail, 'flags'> & Partial<Pick<CaseDetail, 'applied_units'>>): FlagView[] {
	const shown = new Set(unitDecisions(detail).map((u) => u.flag.flag_id));
	return detail.flags.filter((f) => DECIDED.has(f.status) && !shown.has(f.flag_id));
}

export const waitingFlags = (detail: Pick<CaseDetail, 'flags'>): FlagView[] => detail.flags.filter((f) => OPEN.has(f.status));

/** Words for a decision that is not a unit, as a person would say it. */
export function decisionText(flag: FlagView): string {
	const r = flag.resolution as (Resolution & Record<string, unknown>) | null;
	if (flag.status === 'REJECTED_FILE') return r?.action === 'mark_junk' ? 'Marked as junk' : 'Skipped';
	if (flag.status === 'AUTO_RESOLVED') return 'Closed by the pipeline: a rule answered it';
	if (!r) return 'Decided';
	switch (r.action) {
		case 'accept_both':
			return 'Accepted as it is';
		case 'ignore':
			return 'Ignored';
		case 'choose_source':
			return `Source ${String(r.choice)} chosen`;
		case 'mark_superseded':
			return 'Marked a document as superseded';
		case 'set_value':
			return r.illegible ? 'Marked illegible' : `Value typed: ${String(r.value ?? '')}`;
		case 'choose_table':
			return `Table version ${String(r.choice)} chosen`;
		case 'map_columns':
			return 'Columns mapped';
		case 'map_json_keys':
			return 'JSON keys mapped';
		case 'set_fact_unit':
			return r.unit ? `Unit set to ${String(r.unit)}` : 'Kept as text';
		case 'approve_download':
			return 'Download approved';
		case 'approve_internal':
			return 'Approved for internal indexing';
		case 'exclude':
			return 'Excluded';
		case 'redact':
			return 'Redacted';
		default:
			return String(r.action).replace(/_/g, ' ');
	}
}

export const startEdit = (d: UnitDecision): Edit => ({ choiceId: d.choiceId, name: d.name });

/** The edit changes something: another unit (when a unit was chosen) or another name. */
export function isChanged(d: UnitDecision, e: Edit | undefined): boolean {
	if (!e) return false;
	const unitChanged = e.choiceId !== '' && e.choiceId !== d.choiceId;
	const nameChanged = e.name.trim() !== '' && e.name.trim() !== d.name;
	return unitChanged || nameChanged;
}

export function editedResolution(d: UnitDecision, e: Edit, ambient: Ambient): SetUnit {
	const choice = e.choiceId ? ALL.find((c) => c.id === e.choiceId) : null;
	const base = d.resolution;
	const gauge = (choice?.gauge_or_abs ?? base.gauge_or_abs) === 'gauge';
	return {
		...base,
		unit: choice?.unit ?? base.unit,
		quantity: choice?.quantity ?? base.quantity,
		gauge_or_abs: choice?.gauge_or_abs ?? base.gauge_or_abs,
		ambient_condition: gauge ? ambient : null,
		canonical_name: e.name.trim() || base.canonical_name || null
	};
}

/** The column is a gauge reading once the edit is applied, so it needs an ambient reference. */
export function isGaugeAfter(d: UnitDecision, e: Edit | undefined): boolean {
	const choice = e?.choiceId ? ALL.find((c) => c.id === e.choiceId) : null;
	return (choice?.gauge_or_abs ?? d.resolution.gauge_or_abs) === 'gauge';
}

export const MIN_REASON = 3;

/** The decisions a save sends: the changed ones, or, when only confirming what a rule applied, those. */
export function toSave(decisions: UnitDecision[], edits: Record<string, Edit>): UnitDecision[] {
	const changed = decisions.filter((d) => isChanged(d, edits[d.flag.flag_id]));
	return changed.length ? changed : decisions.filter((d) => d.appliedBy);
}

/** What stops the edit from being saved, in words, or null. */
export function editProblem(decisions: UnitDecision[], edits: Record<string, Edit>, reason: string): string | null {
	const changed = decisions.filter((d) => isChanged(d, edits[d.flag.flag_id]));
	if (!changed.length && !decisions.some((d) => d.appliedBy)) return 'Change a unit or a name first.';
	const names = decisions.map((d) => (edits[d.flag.flag_id]?.name.trim() || d.name).toLowerCase());
	if (new Set(names).size !== names.length) return 'Two columns have the same name; each needs its own.';
	if (reason.trim().length < MIN_REASON) return 'Write why you are changing it.';
	return null;
}
