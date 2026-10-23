// The logic of "Create a rule" on the Rules page: which files, what each column is, check and apply.
// The rule it builds is a channel_proposal: it fills in the units of the waiting files and never approves one
// (backend/review/proposals.py). A person applies it on each file.

import type { FolderChoice, OpenChannel, RuleDraft, RuleScope } from '$lib/api_endpoint';
import { UNIT_GROUPS, type Ambient, type UnitChoice } from './channel_map';

export type Step = 'files' | 'columns' | 'apply';

export const STEPS: { id: Step; title: string; hint: string }[] = [
	{ id: 'files', title: 'Which files', hint: 'Pick the folder the rule covers' },
	{ id: 'columns', title: 'What each column is', hint: 'Give every column a unit' },
	{ id: 'apply', title: 'Check and save', hint: 'See what it will do, then save' }
];

export const UNIT_CHOICES: UnitChoice[] = UNIT_GROUPS.flatMap((g) => g.choices);

export interface Narrowing {
	/** only files whose name matches, for example T*.dat */
	glob: string;
	/** only files with this extension, for example .dat */
	extension: string;
}

export interface Column {
	key: number;
	/** the column's name in the file, for example y0 */
	raw: string;
	unitId: string;
	/** what the rest of the system calls it */
	name: string;
}

/** The same rule the server applies to a name (backend/review/cases.py _slug). */
export const slug = (text: string): string =>
	text
		.toLowerCase()
		.replace(/[^0-9a-z]+/g, '_')
		.replace(/^_+|_+$/g, '') || 'channel';

const orNull = (value: string): string | null => (value.trim() ? value.trim() : null);

export function scopeFor(folder: FolderChoice | null, narrowing: Narrowing): RuleScope {
	return {
		scope_root: folder?.root_name ?? null,
		scope_folder_id: folder?.folder_id ?? null,
		scope_filename_glob: orNull(narrowing.glob),
		scope_extension: orNull(narrowing.extension)
	};
}

/** One row per column the matched files wait on, in name order, with a name the server would also choose. */
export function columnsFrom(open: OpenChannel[], first = 0): Column[] {
	return open.map((o, i) => ({ key: first + i, raw: o.channel, unitId: '', name: slug(o.channel) }));
}

export const choiceOf = (column: Column): UnitChoice | null => UNIT_CHOICES.find((c) => c.id === column.unitId) ?? null;

/** A column the rule will decide: it has a name in the file and a unit. */
export const decided = (column: Column): boolean => column.raw.trim() !== '' && choiceOf(column) !== null;

export function channelMapBody(columns: Column[], ambient: Ambient): Record<string, unknown> | null {
	const chosen = columns.filter(decided);
	if (!chosen.length) return null;
	const channels = Object.fromEntries(
		chosen.map((c) => {
			const choice = choiceOf(c)!;
			return [
				c.raw.trim(),
				{
					canonical_name: c.name.trim() || slug(c.raw),
					physical_quantity: choice.quantity,
					unit: choice.unit,
					gauge_or_abs: choice.gauge_or_abs
				}
			];
		})
	);
	const gauge = chosen.some((c) => choiceOf(c)?.gauge_or_abs === 'gauge');
	return { channels, ...(gauge ? { ambient_condition: ambient } : {}) };
}

export function draftFor(folder: FolderChoice | null, narrowing: Narrowing, columns: Column[], ambient: Ambient): RuleDraft | null {
	const body = channelMapBody(columns, ambient);
	return folder && body ? { rule_type: 'channel_proposal', scope: scopeFor(folder, narrowing), body, precedence: 0 } : null;
}

/** Why the reviewer cannot leave this step yet, or null. */
export function stepProblem(step: Step, folder: FolderChoice | null, columns: Column[]): string | null {
	if (step === 'files') return folder ? null : 'Pick a folder first.';
	const chosen = columns.filter(decided);
	if (!chosen.length) return 'Give at least one column a unit.';
	const names = chosen.map((c) => c.name.trim() || slug(c.raw));
	if (new Set(names).size !== names.length) return 'Two columns have the same name; each column needs its own.';
	if (new Set(chosen.map((c) => c.raw.trim())).size !== chosen.length) return 'A column is listed twice.';
	return null;
}

/** Where the rule applies, in words. */
export function whereText(folder: FolderChoice, narrowing: Narrowing): string {
	const parts = [folder.path];
	if (narrowing.glob.trim()) parts.push(`only files named ${narrowing.glob.trim()}`);
	if (narrowing.extension.trim()) parts.push(`only ${narrowing.extension.trim()} files`);
	return parts.join(', ');
}

/** What the rule says, one line per column. */
export function saysText(columns: Column[]): string[] {
	return columns.filter(decided).map((c) => `${c.raw.trim()} is ${choiceOf(c)!.label}, called ${c.name.trim() || slug(c.raw)}`);
}
