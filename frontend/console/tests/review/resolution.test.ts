import { describe, expect, it } from 'vitest';
import type { Resolution } from '../../src/lib/api_endpoint';
import { allowedActions, canBecomeRule, caseRuleScope, missing, needsPreview, startDraft } from '../../src/lib/components/review/resolution';
import { detail, unitFlag } from './fixtures';
import { reactive } from './state.svelte';

const where = detail().locations[0];

describe('resolution drafts', () => {
	it('offers exactly the actions the server allows, ignoring unknown ones', () => {
		expect(allowedActions({ allowed_actions: ['set_unit', 'set_fact_unit'] })).toEqual(['set_unit', 'set_fact_unit']);
		expect(allowedActions({ allowed_actions: ['skip', 'future_action'] })).toEqual(['skip']);
	});

	it('starts from a copy of the suggestion when it proposes the chosen action', () => {
		const flag = unitFlag();
		const draft = startDraft('set_unit', flag);
		expect(draft).toEqual(flag.suggested_resolution!.resolution);
		expect(draft).not.toBe(flag.suggested_resolution!.resolution);
		// a person chooses: a unit, or "no unit needed" (null); an empty unit is not a decision
		expect(startDraft('set_fact_unit', flag)).toEqual({ action: 'set_fact_unit', unit: '' });
		expect(missing({ action: 'set_fact_unit', unit: '' })).toBe('a unit, or choose "No unit needed"');
		expect(missing({ action: 'set_fact_unit', unit: null })).toBeNull();
		expect(missing({ action: 'set_fact_unit', unit: 'bar' })).toBeNull();
	});

	it('starts a blank unit draft on the flagged channel', () => {
		expect(startDraft('set_unit', unitFlag({ suggested_resolution: null }))).toMatchObject({
			action: 'set_unit',
			channel: 'AIN0',
			unit: '',
			gauge_or_abs: 'unknown'
		});
	});

	it.each([
		[{ action: 'set_unit', channel: 'AIN0', unit: '', quantity: 'pressure', gauge_or_abs: 'gauge', expression: null }, 'a unit or a conversion expression'],
		[{ action: 'set_unit', channel: 'AIN0', unit: 'psi', quantity: 'pressure', gauge_or_abs: 'gauge', ambient_condition: null }, 'the ambient reference for a gauge unit'],
		[{ action: 'set_unit', channel: 'AIN0', unit: '', quantity: 'pressure', gauge_or_abs: 'absolute', expression: 'val * 0.0689476' }, null],
		[{ action: 'map_columns', columns: [{ index: 0, canonical_name: 't', is_time: true }, { index: 0, canonical_name: 'p' }] }, 'distinct column indexes'],
		[{ action: 'map_columns', columns: [{ index: 0, canonical_name: '' }] }, 'a canonical name for every column'],
		[{ action: 'set_value', value: '', illegible: false }, 'a value, or mark it illegible'],
		[{ action: 'set_value', value: null, illegible: true }, null],
		[{ action: 'mark_superseded', superseded_doc_id: 'nope' }, 'the superseded document id'],
		[{ action: 'skip' }, null]
	])('reports what is missing: %j', (draft, gap) => {
		expect(missing(draft as Resolution)).toBe(gap);
	});

	it('previews only the actions that change numbers', () => {
		expect(['set_unit', 'map_columns', 'skip', 'choose_source'].filter((a) => needsPreview(a as never))).toEqual(['set_unit', 'map_columns']);
	});
});

describe('startDraft with reactive data', () => {
	it('copies a suggestion that is a Svelte state proxy (pages hold the case in $state)', () => {
		const flag = unitFlag();
		const draft = startDraft('set_unit', reactive(flag));
		expect(draft).toEqual(flag.suggested_resolution!.resolution);
	});

	it('offers to propose only a unit decision, the one kind of rule a route fills in from', () => {
		expect(['set_unit', 'map_columns', 'skip', 'choose_source'].filter((a) => canBecomeRule(a as never))).toEqual(['set_unit']);
	});

	it('scopes a whole case to its file, its folder or the files of the folder that match', () => {
		const where = { root_name: 'APU', folder_id: 'F1', file_name: 'a.dat', extension: '.dat' };
		expect(caseRuleScope('file', where)).toBeNull();
		expect(caseRuleScope('folder', where)).toEqual({ scope_root: 'APU', scope_folder_id: 'F1' });
		expect(caseRuleScope('folder_pattern', where, ' T*.dat ')).toEqual({ scope_root: 'APU', scope_folder_id: 'F1', scope_filename_glob: 'T*.dat' });
		expect(() => caseRuleScope('folder_pattern', where, '')).toThrow('enter a filename pattern');
		expect(() => caseRuleScope('folder', { ...where, folder_id: null })).toThrow('folder id');
	});
});
