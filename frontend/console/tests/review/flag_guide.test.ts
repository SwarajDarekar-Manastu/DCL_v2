import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import FlagGuide from '../../src/lib/components/review/FlagGuide.svelte';
import { FLAG_GUIDE, guideKeyFor, guideWords } from '../../src/lib/components/review/flag_guide';
import { ACTION_LABEL, NOT_BUILT } from '../../src/lib/components/review/resolution';
import { groupLocations } from '../../src/lib/components/review/locations';
import type { CaseLocation } from '../../src/lib/api_endpoint';

const loc = (path: string, web_url: string | null): CaseLocation =>
	({
		path,
		web_url,
		file_name: path.split('/').pop() ?? '',
		root_name: 'APU',
		folder_id: null,
		extension: 'tex'
	}) as CaseLocation;

describe('flag guide text', () => {
	it('covers the nine flag types and the two other readings of a conflict', () => {
		expect(Object.keys(FLAG_GUIDE).sort()).toEqual(
			[
				'CLOUD_RESTRICTED',
				'CONFLICT',
				'CONFLICT_CHECK',
				'CONFLICT_NOTE',
				'HELD_LARGE_FILE',
				'LOW_CONFIDENCE_EXTRACTION',
				'PARSE_FAILURE',
				'SCHEMA_UNKNOWN',
				'SENSITIVE_CONTENT',
				'UNIT_AMBIGUITY',
				'UNSUPPORTED_FORMAT'
			].sort()
		);
		for (const guide of Object.values(FLAG_GUIDE)) {
			expect(guide.what.length).toBeGreaterThan(20);
			expect(guide.decide.length).toBeGreaterThan(10);
			expect(guide.choices.length).toBeGreaterThan(0);
			expect(guide.unsure.length).toBeGreaterThan(10);
		}
	});

	it('keeps every guide short enough to read at a glance', () => {
		for (const guide of Object.values(FLAG_GUIDE)) expect(guideWords(guide)).toBeLessThanOrEqual(75);
	});

	it('only names actions the console has, and never one it cannot carry out yet', () => {
		for (const guide of Object.values(FLAG_GUIDE)) {
			for (const { action } of guide.choices) {
				if (action === null) continue;
				expect(action in ACTION_LABEL).toBe(true);
				expect(NOT_BUILT).not.toContain(action);
			}
		}
	});

	it('reads a conflict by what its evidence says it is', () => {
		const side = { label: 'x', value: 'y', provenance: 'p' };
		const conflict = (relation: 'sources_disagree' | 'check_failed' | 'note') => ({
			flag_type: 'CONFLICT' as const,
			evidence: { kind: 'conflict' as const, subject: 's', relation, a: side, b: relation === 'note' ? null : side }
		});
		expect(guideKeyFor(conflict('sources_disagree'))).toBe('CONFLICT');
		expect(guideKeyFor(conflict('check_failed'))).toBe('CONFLICT_CHECK');
		expect(guideKeyFor(conflict('note'))).toBe('CONFLICT_NOTE');
		expect(guideKeyFor({ flag_type: 'UNIT_AMBIGUITY', evidence: null })).toBe('UNIT_AMBIGUITY');
	});

	it('opens a popover with what is wrong and what to decide', async () => {
		render(FlagGuide, { topic: 'CONFLICT' });
		await fireEvent.click(
			screen.getByRole('button', {
				name: /what should i do with a CONFLICT flag/i
			})
		);
		expect(await screen.findByText(/Two sources state different values/)).toBeTruthy();
		expect(screen.getByText(/Say which one is right/)).toBeTruthy();
	});

	it('explains a note in its own words, not as two sources', async () => {
		render(FlagGuide, { topic: 'CONFLICT_NOTE' });
		await fireEvent.click(screen.getByRole('button', { name: /what should i do with a CONFLICT flag/i }));
		expect(await screen.findByText(/two test plans named in its folder path/)).toBeTruthy();
		expect(screen.queryByText(/Two sources/)).toBeNull();
	});
});

describe('OneDrive links', () => {
	it('shows one main link and groups the other distinct copies', () => {
		const groups = groupLocations([
			loc('APU/Plan 1/Tables/a.tex', 'https://x/1'),
			loc('APU/Plan 2/Tables/a.tex', 'https://x/2'),
			loc('APU/Plan 3/Tables/a.tex', 'https://x/3')
		]);
		expect(groups.primary?.url).toBe('https://x/1');
		expect(groups.others.map((l) => l.url)).toEqual(['https://x/2', 'https://x/3']);
	});

	it('drops repeated addresses and locations without one', () => {
		const groups = groupLocations([loc('APU/a/x.tex', 'https://x/1'), loc('APU/b/x.tex', 'https://x/1'), loc('APU/c/x.tex', null)]);
		expect(groups.primary?.url).toBe('https://x/1');
		expect(groups.others).toEqual([]);
	});

	it('has no links when no location has an address', () => {
		expect(groupLocations([loc('APU/a/x.tex', null)])).toEqual({
			primary: null,
			others: []
		});
	});

	it('tells copies apart by their whole folder, even when they differ only in a test plan high up', () => {
		const groups = groupLocations([
			loc('APU/Test Campaign 1/Test Plan 10/A/APU - Firing/Main_Files/3_Test_setup_BASE.tex', 'https://x/1'),
			loc('APU/Test Campaign 1/Test Plan 10/B/APU - Firing/Main_Files/3_Test_setup_BASE.tex', 'https://x/2'),
			loc('APU/Test Campaign 1/Test Plan 11/APU - Firing/Main_Files/3_Test_setup_BASE.tex', 'https://x/3'),
			loc('APU/Test Campaign 1/Test Plan 12/APU - Firing/Main_Files/3_Test_setup_BASE.tex', 'https://x/4')
		]);
		expect(groups.primary?.folder).toBe('Test Campaign 1/Test Plan 10/A/APU - Firing/Main_Files');
		expect(groups.others.map((l) => l.folder)).toEqual([
			'Test Campaign 1/Test Plan 10/B/APU - Firing/Main_Files',
			'Test Campaign 1/Test Plan 11/APU - Firing/Main_Files',
			'Test Campaign 1/Test Plan 12/APU - Firing/Main_Files'
		]);
		expect(new Set(groups.others.map((l) => l.folder)).size).toBe(3);
	});
});
