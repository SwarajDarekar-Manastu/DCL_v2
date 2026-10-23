import { describe, expect, it } from 'vitest';
import type { ConfigEntry } from '../../src/lib/api_endpoint';
import { fromDraft, keyMatches, kindOf, restoreAt, sameValue, sectionKeys, sectionTimeline, summary, toDraft } from '../../src/lib/components/settings/settings_form';

const entry = (key: string, value: unknown, version = 1): ConfigEntry => ({
	key,
	value: value as ConfigEntry['value'],
	version,
	updated_by: 'seed',
	updated_at: '2026-10-22T09:00:00Z',
	description: null
});

describe('section keys', () => {
	it('matches families, one-segment placeholders and exact keys', () => {
		expect(keyMatches('gate.*', 'gate.junk_names')).toBe(true);
		expect(keyMatches('gate.*', 'gateway')).toBe(false);
		expect(keyMatches('routes.<X>.enabled', 'routes.A1.enabled')).toBe(true);
		expect(keyMatches('routes.<X>.enabled', 'routes.A1.x.enabled')).toBe(false);
		expect(keyMatches('flags.strict_mode', 'flags.strict_mode')).toBe(true);
	});

	it('lists stored keys of the section and exact keys not set yet, sorted', () => {
		const entries = [entry('routes.C.enabled', true), entry('gate.junk_names', []), entry('routes.A1.enabled', false)];
		expect(sectionKeys(['routes.<X>.enabled', 'sanity_ranges', 'thresholds.*', 'prompt versions'], entries).map((r) => [r.key, r.entry?.version ?? 0])).toEqual([
			['routes.A1.enabled', 1],
			['routes.C.enabled', 1],
			['sanity_ranges', 0]
		]);
	});
});

describe('typed drafts', () => {
	it('round-trips each kind of value', () => {
		const values: unknown[] = [true, 4294967296, 'cron 0 2 * * *', ['.pyc', '.dll'], { '.xlsm': ['lib'] }, []];
		for (const value of values) {
			const kind = kindOf(value);
			const parsed = fromDraft(kind, toDraft(kind, value));
			expect(parsed).toEqual({ ok: true, value });
		}
		expect(values.map(kindOf)).toEqual(['boolean', 'number', 'text', 'lines', 'json', 'lines']);
	});

	it('trims list lines and drops empty ones', () => {
		expect(fromDraft('lines', ' .pyc \n\n.dll\n')).toEqual({ ok: true, value: ['.pyc', '.dll'] });
	});

	it('catches bad input before it is sent', () => {
		expect(fromDraft('number', '12a')).toEqual({ ok: false, error: 'not a number' });
		expect(fromDraft('number', ' ')).toEqual({ ok: false, error: 'not a number' });
		const bad = fromDraft('json', '{"a": }');
		expect(bad.ok).toBe(false);
	});

	it('compares values ignoring object key order', () => {
		expect(sameValue({ a: 1, b: [1, { c: 2, d: 3 }] }, { b: [1, { d: 3, c: 2 }], a: 1 })).toBe(true);
		expect(sameValue(['a', 'b'], ['b', 'a'])).toBe(false);
	});

	it('shortens long values for history rows', () => {
		expect(summary('x'.repeat(200), 10)).toBe('xxxxxxxxx…');
		expect(summary(['a'])).toBe('["a"]');
	});
});

describe('section restore', () => {
	const h = (key: string, rows: [number, string, unknown][]): ConfigEntry[] =>
		rows.map(([version, at, value]) => ({ ...entry(key, value, version), updated_at: at, updated_by: `u${version}` }));
	const histories = {
		'gate.junk_names': h('gate.junk_names', [
			[1, '2026-10-21T19:28:00Z', ['a']],
			[2, '2026-10-22T08:14:00Z', ['a', 'b']],
			[3, '2026-10-22T08:20:00Z', ['a']]
		]),
		'gate.max_download_bytes': h('gate.max_download_bytes', [
			[1, '2026-10-21T19:28:00Z', 100],
			[2, '2026-10-22T09:00:00Z', 200]
		]),
		'gate.shortcut_extensions': h('gate.shortcut_extensions', [[1, '2026-10-22T10:00:00Z', ['.url']]])
	};

	it('lists every write newest first', () => {
		expect(sectionTimeline(histories).map((p) => `${p.key}@${p.version}`)).toEqual([
			'gate.shortcut_extensions@1',
			'gate.max_download_bytes@2',
			'gate.junk_names@3',
			'gate.junk_names@2',
			'gate.junk_names@1',
			'gate.max_download_bytes@1'
		]);
	});

	it('restores each key to its version at that moment, skipping unchanged and newer keys', () => {
		expect(restoreAt(histories, '2026-10-22T08:14:00Z')).toEqual({
			versions: { 'gate.junk_names': 2, 'gate.max_download_bytes': 1 },
			newer: ['gate.shortcut_extensions']
		});
		// junk_names v1 has the same value as today's v3: nothing to write for it
		expect(restoreAt(histories, '2026-10-21T19:28:00Z').versions).toEqual({ 'gate.max_download_bytes': 1 });
	});
});
