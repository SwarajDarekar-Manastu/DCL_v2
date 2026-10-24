import { describe, expect, it } from 'vitest';
import {
	columnOf,
	initialValues,
	offerBody,
	offerFor,
	offerProblem,
	offerSentence,
	offersFor,
	shortSubject
} from '../../src/lib/components/review/rule_from_decision';
import { conflictFlag, factUnitFlag, jsonSchemaFlag, unitFlag } from './fixtures';

const FILE = 'Plan_30_Summary.pdf';

describe('shortSubject', () => {
	it('keeps a short subject whole and cuts a long one at a space', () => {
		expect(shortSubject('test_plan_id')).toBe('test_plan_id');
		expect(shortSubject('  max   chamber pressure  ')).toBe('max chamber pressure');
		expect(shortSubject('Maximum chamber pressure of the second burn exceeds the stated limit of the plan', 40)).toBe('Maximum chamber pressure of the second');
		expect(shortSubject('a'.repeat(60), 40)).toHaveLength(40);
	});
});

describe('a conflict that was ignored or accepted', () => {
	it('offers an ignore_pattern for the same flag type and relation, with a short subject and a reason', () => {
		const flag = conflictFlag({}, 'check_failed');
		for (const action of ['ignore', 'accept_both'] as const) {
			const offer = offerFor(flag, { action }, FILE)!;
			expect(offer.ruleType).toBe('ignore_pattern');
			expect(offer.fixed).toEqual({ flag_type: 'CONFLICT', relation: 'check_failed' });
			expect(offerBody(offer, initialValues(offer))).toEqual({
				subject_contains: 'test_plan_id',
				reason: `Accepted on ${FILE}`,
				flag_type: 'CONFLICT',
				relation: 'check_failed'
			});
		}
	});

	it('uses a short part of a long subject, and leaves the subject out when the reviewer clears it', () => {
		const flag = conflictFlag();
		if (flag.evidence?.kind === 'conflict') flag.evidence.subject = 'Maximum chamber pressure of the second burn exceeds the stated limit of the plan';
		const offer = offerFor(flag, { action: 'ignore' }, FILE)!;
		expect(initialValues(offer).subject_contains).toBe('Maximum chamber pressure of the second');
		expect(offerBody(offer, { ...initialValues(offer), subject_contains: '  ' })).not.toHaveProperty('subject_contains');
		expect(offerSentence(offer, { ...initialValues(offer), subject_contains: '' })).toBe('Ignore every conflict (sources disagree) whatever its subject.');
	});

	it('needs a reason', () => {
		const offer = offerFor(conflictFlag(), { action: 'ignore' }, FILE)!;
		expect(offerProblem(offer, initialValues(offer))).toBeNull();
		expect(offerProblem(offer, { ...initialValues(offer), reason: ' ' })).toBe('Fill in "Why".');
	});

	it('says the rule in one sentence', () => {
		const offer = offerFor(conflictFlag({}, 'note'), { action: 'accept_both' }, FILE)!;
		expect(offerSentence(offer, initialValues(offer))).toBe('Ignore every conflict (note) whose subject contains “test_plan_id”.');
	});
});

describe('a source that was chosen', () => {
	it('offers a source_choice for the subject and the label of the side chosen', () => {
		const flag = conflictFlag();
		const a = offerFor(flag, { action: 'choose_source', choice: 'A' }, FILE)!;
		expect(offerBody(a, initialValues(a))).toEqual({ subject: 'test_plan_id', prefer: 'folder' });
		const b = offerFor(flag, { action: 'choose_source', choice: 'B' }, FILE)!;
		expect(b.ruleType).toBe('source_choice');
		expect(offerBody(b, initialValues(b))).toEqual({ subject: 'test_plan_id', prefer: 'content' });
		expect(offerSentence(b, initialValues(b))).toBe('When “test_plan_id” disagrees, prefer the side labelled “content”.');
	});

	it('offers nothing for a failed check or a note, which have no second side, or when the side has no label', () => {
		expect(offerFor(conflictFlag({}, 'check_failed'), { action: 'choose_source', choice: 'A' }, FILE)).toBeNull();
		expect(offerFor(conflictFlag({}, 'note'), { action: 'choose_source', choice: 'B' }, FILE)).toBeNull();
		expect(offerFor(conflictFlag(), { action: 'choose_source', choice: 'B' }, FILE)).not.toBeNull();
		const flag = conflictFlag({}, 'sources_disagree');
		if (flag.evidence?.kind === 'conflict') flag.evidence.b = { label: '', value: 'x', provenance: 'y' };
		expect(offerFor(flag, { action: 'choose_source', choice: 'B' }, FILE)).toBeNull();
	});
});

describe('the unit of a table or prose number', () => {
	it('offers a column_unit with the anchor column and the unit that was set', () => {
		const offer = offerFor(factUnitFlag(), { action: 'set_fact_unit', unit: 'psi' }, FILE)!;
		expect(offer.ruleType).toBe('column_unit');
		expect(offerBody(offer, initialValues(offer))).toEqual({ column: 'Pressure (A)', unit: 'psi' });
		expect(offerSentence(offer, initialValues(offer))).toBe('Read numbers under “Pressure (A)” as psi.');
	});

	it('keeps the numbers as text as an explicit null when no unit was set', () => {
		const offer = offerFor(factUnitFlag(), { action: 'set_fact_unit', unit: null }, FILE)!;
		expect(offerBody(offer, initialValues(offer))).toEqual({ column: 'Pressure (A)', unit: null });
		expect(offerSentence(offer, initialValues(offer))).toBe('Keep numbers under “Pressure (A)” as text.');
	});

	it('finds the column in the anchor, else in the label at the end of the prose context, as the server does', () => {
		expect(columnOf(factUnitFlag())).toBe('Pressure (A)');
		expect(columnOf(factUnitFlag({ anchor: {} }))).toBe('Pressure (A)');
		expect(columnOf(factUnitFlag({ anchor: { channel: 'C_F' } }))).toBe('C_F');
		expect(columnOf(factUnitFlag({ anchor: {}, evidence: { kind: 'unit_fact', value_raw: '5', context: 'no label here', candidate_units: [] } }))).toBe('');
	});

	it('still offers it with an empty column, and asks for one before saving', () => {
		const flag = factUnitFlag({ anchor: {}, evidence: { kind: 'unit_fact', value_raw: '5', context: 'no label here', candidate_units: [] } });
		const offer = offerFor(flag, { action: 'set_fact_unit', unit: 'psi' }, FILE)!;
		expect(offerProblem(offer, initialValues(offer))).toBe('Fill in "Column or label".');
	});

	it('is never offered for a telemetry channel or a HARD unit flag', () => {
		expect(offerFor(unitFlag(), { action: 'set_fact_unit', unit: 'psi' }, FILE)).toBeNull();
		expect(offerFor(factUnitFlag({ severity: 'HARD' }), { action: 'set_fact_unit', unit: 'psi' }, FILE)).toBeNull();
		const telemetry = unitFlag();
		expect(offerFor(telemetry, { action: 'set_unit', channel: 'AIN0', unit: 'psi', quantity: 'pressure', gauge_or_abs: 'gauge', ambient_condition: 'SEA_LEVEL', ambient_pressure_bar_abs: 1.01325, expression: null }, FILE)).toBeNull();
	});
});

describe('JSON keys that were mapped', () => {
	it('offers a schema_mapping with the key to section mapping of the decision, and nothing to edit', () => {
		const offer = offerFor(jsonSchemaFlag(), { action: 'map_json_keys', key_to_section: { summary: 'Summary', results: 'Test results' }, save_as_schema: null }, FILE)!;
		expect(offer.ruleType).toBe('schema_mapping');
		expect(offer.fields).toEqual([]);
		expect(offerBody(offer, {})).toEqual({ key_to_section: { summary: 'Summary', results: 'Test results' } });
		expect(offerSentence(offer, {})).toBe('Map the JSON keys: summary to Summary, results to Test results.');
	});

	it('offers nothing for an empty mapping or another kind of schema flag', () => {
		expect(offerFor(jsonSchemaFlag(), { action: 'map_json_keys', key_to_section: {}, save_as_schema: null }, FILE)).toBeNull();
		const array = jsonSchemaFlag({ evidence: { kind: 'array_schema', shape: [3, 2], columns: [], first_rows: [], pickle_classes: [], recommendation: '', siblings: [] } });
		expect(offerFor(array, { action: 'map_json_keys', key_to_section: { a: 'A' }, save_as_schema: null }, FILE)).toBeNull();
	});
});

describe('offersFor', () => {
	it('offers only for the decisions a rule can repeat, in the order they were chosen, once per answer', () => {
		const flags = [conflictFlag({ flag_id: 'c1' }), conflictFlag({ flag_id: 'c2' }), factUnitFlag(), unitFlag()];
		const offers = offersFor(
			flags,
			[
				['c1', { action: 'ignore' }],
				['c2', { action: 'ignore' }],
				['flag-fact', { action: 'set_fact_unit', unit: 'psi' }],
				['flag-unit', { action: 'set_fact_unit', unit: 'psi' }],
				['missing', { action: 'ignore' }]
			],
			FILE
		);
		expect(offers.map((o) => [o.flagId, o.ruleType])).toEqual([
			['c1', 'ignore_pattern'],
			['flag-fact', 'column_unit']
		]);
	});

	it('offers nothing when the decision is a skip, a junk mark or not repeatable', () => {
		expect(offersFor([conflictFlag()], [['flag-conflict', { action: 'mark_superseded', superseded_doc_id: '0b6f1d3e-2a4c-4e8f-9c1a-5d7e3f2b1a90' }]], FILE)).toEqual([]);
		expect(offersFor([conflictFlag()], [], FILE)).toEqual([]);
	});
});
