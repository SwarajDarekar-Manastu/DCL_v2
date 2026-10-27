import { fireEvent, render, screen } from '@testing-library/svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import QueueList from '../../src/lib/components/review/QueueList.svelte';
import { summary } from './fixtures';

const now = new Date('2026-10-21T12:00:00Z');
const items = [
	summary({ case_key: 'a:1', title: 'Pressure_T07.dat', files_unblocked: 116, oldest_created_at: '2026-10-14T08:00:00Z' }),
	summary({ case_key: 'b:1', title: 'T01.npy', flag_counts: { SCHEMA_UNKNOWN: 1 }, files_unblocked: 3, has_suggestion: false }),
	summary({ case_key: 'c:4', title: 'report.pdf', max_severity: 'SOFT', flag_counts: { CONFLICT: 2 }, files_unblocked: null })
];

beforeAll(() => {
	// jsdom lacks scrollIntoView; browsers have it.
	Element.prototype.scrollIntoView = vi.fn();
});

describe('QueueList', () => {
	it('shows impact, severity, counts and aging', () => {
		const { container } = render(QueueList, { items, selectedKey: null, onOpen: () => {}, now });
		const rows = screen.getAllByRole('listitem');
		expect(rows[0].textContent).toContain('unblocks 116');
		expect(rows[0].textContent).toContain('1 unit to set');
		expect(rows[2].textContent).toContain('2 disagreements to settle');
		expect(rows[2].textContent).not.toContain('unblocks');
		expect([...container.querySelectorAll('li.aging')].map((li) => li.id)).toEqual(['case-row-0']);
	});

	it('moves with j / k and opens with Enter, ignoring keys typed in filters', async () => {
		const onOpen = vi.fn();
		render(QueueList, { items, selectedKey: null, onOpen, now });
		await fireEvent.keyDown(window, { key: 'j' });
		await fireEvent.keyDown(window, { key: 'j' });
		await fireEvent.keyDown(window, { key: 'j' });
		await fireEvent.keyDown(window, { key: 'k' });
		await fireEvent.keyDown(window, { key: 'Enter' });
		expect(onOpen).toHaveBeenCalledWith('b:1');

		const input = document.createElement('input');
		document.body.appendChild(input);
		await fireEvent.keyDown(input, { key: 'Enter' });
		expect(onOpen).toHaveBeenCalledTimes(1);
	});

	it('opens a case on click and links it by case key', async () => {
		const onOpen = vi.fn();
		render(QueueList, { items, selectedKey: 'c:4', onOpen, now });
		const link = screen.getByRole('link', { name: /report\.pdf/ });
		expect(link.getAttribute('href')).toBe('/review?case=c%3A4');
		expect(link.closest('li')?.getAttribute('aria-current')).toBe('true');
		await fireEvent.click(link);
		expect(onOpen).toHaveBeenCalledWith('c:4');
	});
});
