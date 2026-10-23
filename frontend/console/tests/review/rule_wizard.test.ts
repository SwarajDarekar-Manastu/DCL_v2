import { describe, expect, it } from 'vitest';
import type { FolderChoice } from '../../src/lib/api_endpoint';
import {
	channelMapBody,
	columnsFrom,
	draftFor,
	saysText,
	scopeFor,
	slug,
	stepProblem,
	whereText,
	type Column
} from '../../src/lib/components/review/rule_wizard';

const folder: FolderChoice = {
	folder_id: 'F1',
	root_name: 'APU Injector',
	path: 'APU Injector/Injector 14/Pressure_Data_Files',
	files: 12,
	waiting: 12
};
const column = (raw: string, unitId: string, name = slug(raw)): Column => ({ key: 1, raw, unitId, name });

describe('rule wizard logic', () => {
	it('names a column the way the server does', () => {
		expect(slug('PT-101 Chamber (bar)')).toBe('pt_101_chamber_bar');
		expect(slug('  ')).toBe('channel');
		expect(slug('y0')).toBe('y0');
	});

	it('scopes to the folder and, when asked, to a file pattern and a type', () => {
		expect(scopeFor(folder, { glob: '', extension: '' })).toEqual({
			scope_root: 'APU Injector',
			scope_folder_id: 'F1',
			scope_filename_glob: null,
			scope_extension: null
		});
		expect(scopeFor(folder, { glob: ' T*.dat ', extension: '.dat' })).toMatchObject({ scope_filename_glob: 'T*.dat', scope_extension: '.dat' });
		expect(scopeFor(null, { glob: '', extension: '' }).scope_folder_id).toBeNull();
	});

	it('starts a row for every column the files wait on', () => {
		const rows = columnsFrom([
			{ channel: 'y0', files: 12 },
			{ channel: 'y1', files: 12 }
		]);
		expect(rows.map((r) => [r.raw, r.unitId, r.name])).toEqual([
			['y0', '', 'y0'],
			['y1', '', 'y1']
		]);
	});

	it('builds the channel map body from the columns that have a unit, with the ambient only for gauge', () => {
		expect(channelMapBody([column('y0', '')], 'SEA_LEVEL')).toBeNull();
		expect(channelMapBody([column('y0', 'degc'), column('y1', '')], 'SEA_LEVEL')).toEqual({
			channels: { y0: { canonical_name: 'y0', physical_quantity: 'temperature', unit: 'degC', gauge_or_abs: 'n/a' } }
		});
		expect(channelMapBody([column('y0', 'bar_g', 'pt_101_chamber_bar_g')], 'VACUUM_CHAMBER')).toEqual({
			channels: { y0: { canonical_name: 'pt_101_chamber_bar_g', physical_quantity: 'pressure', unit: 'bar', gauge_or_abs: 'gauge' } },
			ambient_condition: 'VACUUM_CHAMBER'
		});
	});

	it('builds a saveable rule only with a folder and a decided column', () => {
		const rows = [column('y0', 'bar_a')];
		expect(draftFor(null, { glob: '', extension: '' }, rows, 'SEA_LEVEL')).toBeNull();
		expect(draftFor(folder, { glob: '', extension: '' }, [column('y0', '')], 'SEA_LEVEL')).toBeNull();
		expect(draftFor(folder, { glob: 'T*.dat', extension: '' }, rows, 'SEA_LEVEL')).toMatchObject({
			rule_type: 'channel_proposal',
			scope: { scope_folder_id: 'F1', scope_filename_glob: 'T*.dat' },
			precedence: 0
		});
	});

	it('says what is missing before a step can be left', () => {
		expect(stepProblem('files', null, [])).toBe('Pick a folder first.');
		expect(stepProblem('files', folder, [])).toBeNull();
		expect(stepProblem('columns', folder, [column('y0', '')])).toBe('Give at least one column a unit.');
		expect(stepProblem('columns', folder, [column('y0', 'bar_a', 'p'), column('y1', 'bar_a', 'p')])).toMatch(/same name/);
		expect(stepProblem('columns', folder, [column('y0', 'bar_a'), column('y0', 'degc', 'other')])).toMatch(/listed twice/);
		expect(stepProblem('columns', folder, [column('y0', 'bar_a'), column('y1', 'degc')])).toBeNull();
	});

	it('describes the rule in plain words', () => {
		expect(whereText(folder, { glob: 'T*.dat', extension: '' })).toBe('APU Injector/Injector 14/Pressure_Data_Files, only files named T*.dat');
		expect(saysText([column('y0', 'bar_g', 'pt_101'), column('y1', '')])).toEqual(['y0 is bar (gauge), called pt_101']);
	});
});
