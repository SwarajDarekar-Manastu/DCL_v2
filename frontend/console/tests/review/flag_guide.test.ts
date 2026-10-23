import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import FlagGuide from '../../src/lib/components/review/FlagGuide.svelte';
import { FLAG_GUIDE } from '../../src/lib/components/review/flag_guide';
import { groupLocations, shortFolder } from '../../src/lib/components/review/locations';
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
	it('covers all nine flag types with a decision and at least one choice', () => {
		expect(Object.keys(FLAG_GUIDE)).toHaveLength(9);
		for (const guide of Object.values(FLAG_GUIDE)) {
			expect(guide.what.length).toBeGreaterThan(20);
			expect(guide.decide.length).toBeGreaterThan(10);
			expect(guide.choices.length).toBeGreaterThan(0);
			expect(guide.unsure.length).toBeGreaterThan(10);
		}
	});

	it('keeps every guide short enough to read at a glance', () => {
		for (const guide of Object.values(FLAG_GUIDE)) {
			const words = [guide.what, guide.decide, ...guide.choices, guide.unsure].join(' ').split(/\s+/).length;
			expect(words).toBeLessThanOrEqual(75);
		}
	});

	it('opens a popover with what is wrong and what to decide', async () => {
		render(FlagGuide, { flagType: 'CONFLICT' });
		await fireEvent.click(
			screen.getByRole('button', {
				name: /what should i do with a CONFLICT flag/i
			})
		);
		expect(await screen.findByText(/Two sources disagree/)).toBeTruthy();
		expect(screen.getByText(/Say which source is right/)).toBeTruthy();
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

	it('tells copies apart by the last two folder names', () => {
		expect(shortFolder('APU/Test Campaign 1/Test Plan 18/APU - Firing/Tables/Observations_Test')).toBe('Tables / Observations_Test');
	});
});
