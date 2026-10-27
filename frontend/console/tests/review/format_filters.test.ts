import { describe, expect, it } from 'vitest';
import { ageText, caseHref, isAging, placeText, questionText, workingDaysBetween } from '../../src/lib/components/review/format';
import { filtersFromUrl, urlFor } from '../../src/lib/components/review/filters';

describe('format', () => {
	it('counts working days only', () => {
		// Fri 2026-10-16 → Wed 2026-10-21: Mon, Tue, Wed
		expect(workingDaysBetween(new Date('2026-10-16T09:00:00Z'), new Date('2026-10-21T09:00:00Z'))).toBe(3);
	});

	it('marks HARD cases older than three working days as aging, never SOFT ones', () => {
		const now = new Date('2026-10-21T12:00:00Z');
		expect(isAging({ max_severity: 'HARD', oldest_created_at: '2026-10-15T09:00:00Z' }, now)).toBe(true);
		expect(isAging({ max_severity: 'HARD', oldest_created_at: '2026-10-16T09:00:00Z' }, now)).toBe(false);
		expect(isAging({ max_severity: 'SOFT', oldest_created_at: '2026-09-01T09:00:00Z' }, now)).toBe(false);
	});

	it('formats ages, counts and links', () => {
		const now = new Date('2026-10-21T12:00:00Z');
		expect(ageText('2026-10-21T11:15:00Z', now)).toBe('45m');
		expect(ageText('2026-10-19T12:00:00Z', now)).toBe('2d');
		expect(questionText({ UNIT_AMBIGUITY: 116, CONFLICT: 0, SCHEMA_UNKNOWN: 1 })).toBe('116 units to set · file layout to map');
		expect(questionText({ LOW_CONFIDENCE_EXTRACTION: 1 })).toBe('1 reading to check');
		expect([placeText('9'), placeText('Steady State Values')]).toEqual(['page 9', 'Steady State Values']);
		expect(caseHref('doc:Sheet 1')).toBe('/review?case=doc%3ASheet%201');
	});
});

describe('queue filters in the URL', () => {
	it('round-trips filters and the open case', () => {
		const url = urlFor({ severity: 'HARD', has_suggestion: true, older_than_days: 3, sort: 'age', root_name: '' }, 'doc:4');
		expect(url).toBe('/review?severity=HARD&has_suggestion=true&older_than_days=3&sort=age&case=doc%3A4');
		const params = new URL(url, 'http://x').searchParams;
		expect(filtersFromUrl(params)).toEqual({ severity: 'HARD', has_suggestion: true, older_than_days: 3, sort: 'age' });
		expect(urlFor({}, null)).toBe('/review');
	});
});
