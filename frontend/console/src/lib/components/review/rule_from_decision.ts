// "Make a rule from this decision": after a person resolves a flag, the rule that would give the same answer to
// the same kind of flag elsewhere in the folder, prefilled from the decision and the flag's evidence. The server
// side is backend/review/rule_answers.py (`answer`): each kind below answers only what it is built for, so the
// offer is made only for the decisions that kind can repeat. Words and bodies only; no network.

import type { FlagView, Resolution, RuleType } from '$lib/api_endpoint';

export type OfferType = Extract<RuleType, 'ignore_pattern' | 'column_unit' | 'source_choice' | 'schema_mapping'>;

/** One thing the reviewer can still change before saving. */
export interface OfferField {
	/** the key in the rule's body */
	key: string;
	label: string;
	value: string;
	required: boolean;
	/** what an empty optional field becomes in the body: left out, or an explicit null */
	empty: 'omit' | 'null';
	placeholder?: string;
}

type ConflictEvidence = Extract<NonNullable<FlagView['evidence']>, { kind: 'conflict' }>;
type Relation = ConflictEvidence['relation'];

interface OfferBase {
	flagId: string;
	/** the flag's own words: what the decision was about */
	about: string;
	fields: OfferField[];
}

/** A rule the reviewer can save. `fixed` is the part of the body they do not edit. */
export type RuleOffer =
	| (OfferBase & { ruleType: 'ignore_pattern'; fixed: { flag_type: 'CONFLICT'; relation: Relation } })
	| (OfferBase & { ruleType: 'column_unit' | 'source_choice'; fixed: Record<string, never> })
	| (OfferBase & { ruleType: 'schema_mapping'; fixed: { key_to_section: Record<string, string> } });
export type DecidedFlag = Pick<FlagView, 'flag_id' | 'flag_type' | 'severity' | 'anchor' | 'evidence'>;

const RELATION_WORDS: Record<Relation, string> = {
	sources_disagree: 'sources disagree',
	check_failed: 'check failed',
	note: 'note'
};

/** A short part of a subject that still names it: up to `max` characters, cut at a space. */
export function shortSubject(subject: string, max = 40): string {
	const text = subject.trim().replace(/\s+/g, ' ');
	if (text.length <= max) return text;
	const cut = text.slice(0, max);
	const space = cut.lastIndexOf(' ');
	return (space > 0 ? cut.slice(0, space) : cut).trim();
}

/** The label at the end of a prose number's context ("… Test 01: C_F" gives "C_F"), as the server reads it. */
const contextLabel = (context: string): string => (context.includes(':') ? context.slice(context.lastIndexOf(':') + 1).trim() : '');

/** The column or label a number in a table or prose belongs to: the anchor's column, else the label in its context. */
export function columnOf(flag: Pick<DecidedFlag, 'anchor' | 'evidence'>): string {
	const evidence = flag.evidence;
	const channel = evidence && 'channel' in evidence ? evidence.channel : '';
	const context = evidence?.kind === 'unit_fact' ? contextLabel(evidence.context) : '';
	return (flag.anchor.column || flag.anchor.channel || channel || context || '').trim();
}

const field = (key: string, label: string, value: string, required: boolean, extra: Partial<OfferField> = {}): OfferField => ({
	key,
	label,
	value,
	required,
	empty: 'omit',
	...extra
});

/** The offer for one decided flag, or null when no rule kind can repeat this decision. */
export function offerFor(flag: DecidedFlag, resolution: Resolution, fileName: string): RuleOffer | null {
	const evidence = flag.evidence;
	if (flag.flag_type === 'CONFLICT' && evidence?.kind === 'conflict') {
		if (resolution.action === 'ignore' || resolution.action === 'accept_both') {
			return {
				flagId: flag.flag_id,
				ruleType: 'ignore_pattern',
				about: evidence.subject,
				fields: [
					field('subject_contains', 'Subject contains', shortSubject(evidence.subject), false, { placeholder: 'any subject' }),
					field('reason', 'Why', fileName ? `Accepted on ${fileName}` : 'Accepted by a reviewer', true)
				],
				fixed: { flag_type: 'CONFLICT', relation: evidence.relation }
			};
		}
		if (resolution.action === 'choose_source' && evidence.relation === 'sources_disagree') {
			const side = resolution.choice === 'A' ? evidence.a : evidence.b;
			if (!side?.label) return null;
			return {
				flagId: flag.flag_id,
				ruleType: 'source_choice',
				about: evidence.subject,
				fields: [field('subject', 'Subject', evidence.subject, true), field('prefer', 'Prefer the side labelled', side.label, true)],
				fixed: {}
			};
		}
		return null;
	}
	if (flag.flag_type === 'UNIT_AMBIGUITY' && flag.severity === 'SOFT' && evidence?.kind === 'unit_fact' && resolution.action === 'set_fact_unit') {
		const column = columnOf(flag);
		return {
			flagId: flag.flag_id,
			ruleType: 'column_unit',
			about: column || evidence.value_raw,
			fields: [
				field('column', 'Column or label', column, true, { placeholder: 'Pressure*' }),
				field('unit', 'Unit', resolution.unit ?? '', false, { empty: 'null', placeholder: 'empty keeps the number as text' })
			],
			fixed: {}
		};
	}
	if (flag.flag_type === 'SCHEMA_UNKNOWN' && evidence?.kind === 'json_schema' && resolution.action === 'map_json_keys') {
		if (!Object.keys(resolution.key_to_section).length) return null;
		return {
			flagId: flag.flag_id,
			ruleType: 'schema_mapping',
			about: evidence.closest_schema ?? 'this JSON shape',
			fields: [],
			fixed: { key_to_section: { ...resolution.key_to_section } }
		};
	}
	return null;
}

/** The offers for the decisions just applied, one per kind of answer (the same rule is not offered twice). */
export function offersFor(flags: DecidedFlag[], chosen: [string, Resolution][], fileName: string): RuleOffer[] {
	const byId = new Map(flags.map((f) => [f.flag_id, f]));
	const seen = new Set<string>();
	const offers: RuleOffer[] = [];
	for (const [flagId, resolution] of chosen) {
		const flag = byId.get(flagId);
		const offer = flag && offerFor(flag, resolution, fileName);
		if (!offer) continue;
		const key = JSON.stringify([offer.ruleType, offer.fixed, offer.fields.map((f) => f.value)]);
		if (seen.has(key)) continue;
		seen.add(key);
		offers.push(offer);
	}
	return offers;
}

export type OfferValues = Record<string, string>;

export const initialValues = (offer: RuleOffer): OfferValues => Object.fromEntries(offer.fields.map((f) => [f.key, f.value]));

/** The rule body for the values as they stand. */
export function offerBody(offer: RuleOffer, values: OfferValues): Record<string, unknown> {
	const body: Record<string, unknown> = {};
	for (const f of offer.fields) {
		const text = (values[f.key] ?? '').trim();
		if (text) body[f.key] = text;
		else if (f.empty === 'null') body[f.key] = null;
	}
	return { ...body, ...offer.fixed };
}

/** What stops the offer from being saved, or null. */
export function offerProblem(offer: RuleOffer, values: OfferValues): string | null {
	const gap = offer.fields.find((f) => f.required && !(values[f.key] ?? '').trim());
	return gap ? `Fill in "${gap.label}".` : null;
}

const quoted = (text: string) => `“${text.trim()}”`;

/** The rule in one sentence, for the values as they stand. */
export function offerSentence(offer: RuleOffer, values: OfferValues): string {
	const v = (key: string) => (values[key] ?? '').trim();
	switch (offer.ruleType) {
		case 'ignore_pattern': {
			const subject = v('subject_contains');
			return `Ignore every conflict (${RELATION_WORDS[offer.fixed.relation]}) ${subject ? `whose subject contains ${quoted(subject)}` : 'whatever its subject'}.`;
		}
		case 'column_unit':
			return v('unit') ? `Read numbers under ${quoted(v('column'))} as ${v('unit')}.` : `Keep numbers under ${quoted(v('column'))} as text.`;
		case 'source_choice':
			return `When ${quoted(v('subject'))} disagrees, prefer the side labelled ${quoted(v('prefer'))}.`;
		case 'schema_mapping':
			return `Map the JSON keys: ${Object.entries(offer.fixed.key_to_section)
				.map(([key, section]) => `${key} to ${section}`)
				.join(', ')}.`;
	}
}
