// EntitiesPage (file 08 §4.2) over S1's /entities: merge and split plans checked before they are sent; S1's own
// checks (same type, not into itself, new name not taken) still answer 422 with the reason.

import type { Entity } from '$lib/api_endpoint';

export const ENTITY_TYPES = [
	'component',
	'subsystem',
	'material',
	'propellant',
	'catalyst',
	'product',
	'vendor',
	'organization',
	'standard_clause',
	'failure_mode',
	'test_id',
	'part_number',
	'sensor_tag',
	'person_role',
	'tool_software',
	'equation'
] as const;

export interface MergePlan {
	target: Entity;
	sources: Entity[];
	aliases: number;
	mentions: number;
	problem: string | null;
}

/** Folding the other selected entities into the target: what moves, or why it cannot. */
export function mergePlan(selected: Entity[], targetId: string): MergePlan | null {
	const target = selected.find((e) => e.entity_id === targetId);
	if (!target) return null;
	const sources = selected.filter((e) => e.entity_id !== targetId);
	const otherType = sources.find((e) => e.type !== target.type);
	return {
		target,
		sources,
		aliases: sources.reduce((n, e) => n + e.aliases.length, 0),
		mentions: sources.reduce((n, e) => n + e.mentions, 0),
		problem: !sources.length
			? 'Select at least one more entity to fold into this one.'
			: otherType
				? `Only entities of one type merge: ${otherType.canonical_name} is a ${otherType.type}, ${target.canonical_name} a ${target.type}.`
				: null
	};
}

/** Why a split cannot be sent yet, or null. */
export function splitProblem(entity: Entity, aliasKeys: string[], name: string): string | null {
	if (!aliasKeys.length) return 'Pick the aliases that belong to the new entity.';
	if (aliasKeys.length === entity.aliases.length) return 'Keep at least one alias on the original entity.';
	if (!name.trim()) return 'Name the new entity.';
	if (name.trim().toLowerCase() === entity.canonical_name.toLowerCase()) return 'The new entity needs a different name.';
	return null;
}
