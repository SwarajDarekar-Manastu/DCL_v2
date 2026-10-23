import { describe, expect, it } from 'vitest';
import type { RuleView } from '../../src/lib/api_endpoint';
import { rulesYaml, toYaml } from '../../src/lib/components/review/rules_export';
import expected from './rules_export.expected.yaml?raw';

const rule = (o: Partial<RuleView>): RuleView =>
	({
		rule_id: 'r',
		rule_type: 'unit_mapping',
		scope: { scope_root: null, scope_folder_id: null, scope_filename_glob: null, scope_extension: null },
		precedence: 0,
		body: {},
		origin: 'operator',
		active: true,
		created_by: 'asha@manastuspace.com',
		created_at: '2026-10-22T09:00:00Z',
		supersedes_rule_id: null,
		flags_resolved: 0,
		runs_mapped: 0,
		...o
	}) as RuleView;

// The same file is read by backend/tests/unit/api/test_rules_export_contract.py through S1's load_yaml.
export const RULES: RuleView[] = [
	rule({
		rule_type: 'unit_mapping',
		precedence: 10,
		scope: { scope_root: 'APU Injector', scope_folder_id: null, scope_filename_glob: '*.dat', scope_extension: null },
		body: { channel: 'AIN0', unit: 'bar', quantity: 'pressure', gauge_or_abs: 'gauge' }
	}),
	rule({
		rule_type: 'channel_map',
		scope: { scope_root: null, scope_folder_id: '01RDWVU4ZUFFI75KMFFJEJNIOEECPJM6RB', scope_filename_glob: null, scope_extension: null },
		body: {
			channels: { 'y0 (N2)': { canonical_name: 'p_feed_n2_supply_bar_g', physical_quantity: 'pressure', unit: 'bar', gauge_or_abs: 'gauge' } },
			ambient_pressure_bar_abs: 1.013
		},
		created_by: 'ravi@manastuspace.com'
	}),
	rule({ rule_type: 'ignore_pattern', body: { reason: 'Kalibrierung: "alt" – ignore' } }),
	rule({ rule_type: 'unit_mapping', origin: 'cfg', body: { channel: 'x', unit: 'K', quantity: 'temperature', gauge_or_abs: 'n/a' } }),
	rule({ rule_type: 'ignore_pattern', active: false, body: { reason: 'superseded' } })
];

describe('rules export', () => {
	it('writes the active operator rules in the RulesFile format S1 loads', () => {
		const text = rulesYaml(RULES, '2026-10-23T09:00:00Z');
		const [header, ...body] = text.split('\n');
		expect(header).toBe('# DCL operator rules exported from the Console at 2026-10-23T09:00:00Z; load with backend/review/rules.py load_yaml');
		expect(body.join('\n')).toBe(expected);
	});

	it('handles nested lists and empty values', () => {
		expect(toYaml({ a: [1, { b: 'x' }, []], c: {}, d: null })).toBe('a:\n  - 1\n  - b: "x"\n  - []\nc: {}\nd: null\n');
	});
});
