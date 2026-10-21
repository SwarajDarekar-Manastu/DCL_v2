import { describe, expect, it } from 'vitest';
import type { Resolution } from '../../src/lib/api_endpoint';
import { allowedActions, missing, needsPreview, ruleFor, startDraft } from '../../src/lib/components/review/resolution';
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
		expect(startDraft('set_fact_unit', flag)).toEqual({ action: 'set_fact_unit', unit: null });
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

	it('turns a folder-scoped unit decision into one unit_mapping rule', () => {
		const resolution = startDraft('set_unit', unitFlag());
		expect(ruleFor(resolution, 'file', where)).toBeNull();
		expect(ruleFor(resolution, 'folder', where)).toEqual({
			rule_type: 'unit_mapping',
			scope: { scope_root: 'APU Heater', scope_folder_id: 'FOLDER-TP30' },
			body: {
				channel: 'AIN0',
				unit: 'psi',
				quantity: 'pressure',
				gauge_or_abs: 'gauge',
				ambient_condition: 'SEA_LEVEL',
				ambient_pressure_bar_abs: 1.01325,
				expression: null
			},
			precedence: 0
		});
		expect(ruleFor(resolution, 'folder_pattern', where, ' T*.dat ')?.scope.scope_filename_glob).toBe('T*.dat');
		expect(() => ruleFor(resolution, 'folder_pattern', where, '')).toThrow('enter a filename pattern');
		expect(() => ruleFor(resolution, 'folder', { ...where, folder_id: null })).toThrow('folder id');
		expect(ruleFor({ action: 'skip' }, 'folder', where)).toBeNull();
	});
});

describe('startDraft with reactive data', () => {
	it('copies a suggestion that is a Svelte state proxy (pages hold the case in $state)', () => {
		const flag = unitFlag();
		const draft = startDraft('set_unit', reactive(flag));
		expect(draft).toEqual(flag.suggested_resolution!.resolution);
	});
});
