import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import type { AuditItem } from '../../src/lib/api_endpoint';
import { auditFiltersFromUrl, auditUrl, changedKeys, entityHref } from '../../src/lib/components/review/audit';
import AuditTimeline from '../../src/lib/components/review/AuditTimeline.svelte';
import CaseHeader from '../../src/lib/components/review/CaseHeader.svelte';
import { CASE_KEY, detail } from './fixtures';

const item = (overrides: Partial<AuditItem>): AuditItem => ({
	event_id: 1,
	at: '2026-10-21T09:00:00Z',
	actor: 'asha@manastuspace.com',
	entity_type: 'case',
	entity_id: CASE_KEY,
	action: 'resolve',
	before: { status: 'OPEN', assignee: null },
	after: { status: 'RESOLVED', assignee: null },
	...overrides
});

describe('audit helpers', () => {
	it('round-trips filters with repeated entity ids', () => {
		const url = auditUrl({ entity_id: ['doc:1', 'flag-1'], actor: 'asha@x' });
		expect(url).toBe('/audit?entity_id=doc%3A1&entity_id=flag-1&actor=asha%40x');
		expect(auditFiltersFromUrl(new URL(url, 'http://x').searchParams)).toEqual({ entity_id: ['doc:1', 'flag-1'], actor: 'asha@x' });
		expect(auditUrl({})).toBe('/audit');
	});

	it('links entities the Console can open and names the changed keys', () => {
		expect(entityHref({ entity_type: 'case', entity_id: 'doc:4' })).toBe('/review?case=doc%3A4');
		expect(entityHref({ entity_type: 'rule', entity_id: 'r' })).toBe('/review/rules');
		expect(entityHref({ entity_type: 'config', entity_id: 'translation.mode' })).toBeNull();
		expect(changedKeys({ a: 1, b: { x: 1 } }, { a: 1, b: { x: 2 }, c: true })).toEqual(['b', 'c']);
		expect(changedKeys(null, null)).toEqual([]);
	});
});

describe('AuditTimeline', () => {
	it('shows who did what to which entity, with the change', () => {
		render(AuditTimeline, { items: [item({}), item({ event_id: 2, entity_type: 'config', entity_id: 'translation.mode', action: 'update' })] });
		const rows = screen.getAllByRole('listitem');
		expect(rows[0].textContent).toContain('asha@manastuspace.com');
		expect(screen.getByRole('link', { name: CASE_KEY }).getAttribute('href')).toBe(`/review?case=${encodeURIComponent(CASE_KEY)}`);
		expect(rows[0].textContent).toContain('Changed: status');
		expect(screen.getByText('translation.mode').tagName).toBe('CODE');
	});
});

describe('case history link', () => {
	it('links the case and its flags in one audit view', () => {
		render(CaseHeader, { detail: detail(), me: 'a', busy: false, onAssign: vi.fn(), onUndo: vi.fn() });
		expect(screen.getByRole('link', { name: 'History' }).getAttribute('href')).toBe(
			`/audit?entity_id=${encodeURIComponent(CASE_KEY)}&entity_id=flag-unit`
		);
	});
});
