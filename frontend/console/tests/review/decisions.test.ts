import { describe, expect, it } from 'vitest';
import type { FlagView } from '../../src/lib/api_endpoint';
import {
	decisionText,
	editedResolution,
	editProblem,
	isChanged,
	isGaugeAfter,
	otherDecisions,
	startEdit,
	unitDecisions,
	waitingFlags
} from '../../src/lib/components/review/decisions';
import { unitFlag } from './fixtures';

const decided = (channel: string, unit: string, gauge: 'gauge' | 'absolute' | 'n/a', over: Partial<FlagView> = {}): FlagView =>
	unitFlag({
		flag_id: `flag-${channel}`,
		anchor: { channel },
		status: 'RESOLVED',
		resolution: { action: 'set_unit', channel, unit, quantity: 'pressure', gauge_or_abs: gauge, ambient_condition: gauge === 'gauge' ? 'SEA_LEVEL' : null, ambient_pressure_bar_abs: null, expression: null, canonical_name: `pt_${channel}` },
		resolved_by: 'asha@manastuspace.com',
		resolved_at: '2026-10-23T10:00:00Z',
		proposed_by_rule_id: 'rule-1',
		...over
	});
const conflict = (status: FlagView['status'], resolution: FlagView['resolution']): FlagView =>
	unitFlag({ flag_id: `c-${status}`, flag_type: 'CONFLICT', severity: 'SOFT', anchor: {}, evidence: null, status, resolution, resolved_by: 'ravi@manastuspace.com', resolved_at: '2026-10-22T09:00:00Z' });

const flags = [decided('y1', 'bar', 'gauge'), decided('y0', 'bar', 'absolute'), unitFlag({ flag_id: 'open', anchor: { channel: 'y2' } }), conflict('RESOLVED', { action: 'accept_both' }), conflict('REJECTED_FILE', { action: 'skip' })];

describe('decisions on a file', () => {
	it('lists the decided unit flags by column, with who, when and the rule that proposed them', () => {
		const rows = unitDecisions({ flags });
		expect(rows.map((r) => [r.channel, r.label, r.name, r.decidedBy, r.proposedByRule])).toEqual([
			['y0', 'bar (absolute)', 'pt_y0', 'asha@manastuspace.com', 'rule-1'],
			['y1', 'bar (gauge)', 'pt_y1', 'asha@manastuspace.com', 'rule-1']
		]);
	});

	it('keeps every other decision apart, in words, and the waiting flags apart again', () => {
		expect(otherDecisions({ flags }).map((f) => decisionText(f))).toEqual(['Accepted as it is', 'Whole file skipped']);
		expect(waitingFlags({ flags }).map((f) => f.flag_id)).toEqual(['open']);
		expect(decisionText(conflict('RESOLVED', { action: 'choose_source', choice: 'B' }))).toBe('Source B chosen');
		expect(decisionText(conflict('RESOLVED', { action: 'ignore' }))).toBe('Kept as it is');
		expect(decisionText({ ...conflict('AUTO_RESOLVED', null), resolved_by: 'rerun' })).toBe('Closed: a re-run no longer raised it');
		expect(decisionText({ ...conflict('AUTO_RESOLVED', { action: 'accept_both' }), resolved_by: 'rule-3' })).toBe('A rule answered it: Accepted as it is');
	});

	it('knows a change from an untouched edit and builds the new resolution from it', () => {
		const [y0, y1] = unitDecisions({ flags });
		expect(isChanged(y0, startEdit(y0))).toBe(false);
		expect(isChanged(y0, undefined)).toBe(false);
		const toDegc = { choiceId: 'degc', name: 'tc_1' };
		expect(isChanged(y0, toDegc)).toBe(true);
		expect(editedResolution(y0, toDegc, 'SEA_LEVEL')).toMatchObject({ unit: 'degC', quantity: 'temperature', gauge_or_abs: 'n/a', ambient_condition: null, canonical_name: 'tc_1', channel: 'y0' });
		const toGauge = { choiceId: 'psig', name: y1.name };
		expect(editedResolution(y0, toGauge, 'VACUUM_CHAMBER')).toMatchObject({ unit: 'psi', gauge_or_abs: 'gauge', ambient_condition: 'VACUUM_CHAMBER' });
		expect(isGaugeAfter(y0, toGauge)).toBe(true);
		expect(isGaugeAfter(y0, startEdit(y0))).toBe(false);
		expect(isChanged(y1, { choiceId: y1.choiceId, name: 'renamed' })).toBe(true); // a name alone is a change
	});

	it('says what stops a save: nothing changed, a duplicate name, no reason', () => {
		const rows = unitDecisions({ flags });
		const edits = Object.fromEntries(rows.map((r) => [r.flag.flag_id, startEdit(r)]));
		expect(editProblem(rows, edits, 'because')).toBe('Change a unit or a name first.');
		edits['flag-y0'] = { choiceId: 'degc', name: 'pt_y1' };
		expect(editProblem(rows, edits, 'because')).toMatch(/same name/);
		edits['flag-y0'] = { choiceId: 'degc', name: 'tc_1' };
		expect(editProblem(rows, edits, '  ')).toBe('Write why you are changing it.');
		expect(editProblem(rows, edits, 'the rig sheet says so')).toBeNull();
	});

	it('shows a stored unit that is not in the list as it is, and edits it only when another is chosen', () => {
		const [odd] = unitDecisions({ flags: [decided('y9', 'mbar', 'absolute', { resolution: { action: 'set_unit', channel: 'y9', unit: 'torr', quantity: 'pressure', gauge_or_abs: 'absolute', ambient_condition: null, ambient_pressure_bar_abs: null, expression: null } })] });
		expect([odd.choiceId, odd.label, odd.name]).toEqual(['', 'torr (absolute)', 'y9']);
		expect(isChanged(odd, startEdit(odd))).toBe(false);
		expect(editedResolution(odd, { choiceId: '', name: 'y9' }, 'SEA_LEVEL').unit).toBe('torr');
	});
});
