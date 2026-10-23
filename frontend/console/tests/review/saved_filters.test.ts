import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SavedFilters from '../../src/lib/components/review/SavedFilters.svelte';
import { deleteFilter, filtersOf, loadSaved, saveFilter } from '../../src/lib/components/review/saved_filters';

function memoryStorage(): Storage {
	const data = new Map<string, string>();
	return {
		get length() {
			return data.size;
		},
		clear: () => data.clear(),
		getItem: (k) => data.get(k) ?? null,
		key: (i) => [...data.keys()][i] ?? null,
		removeItem: (k) => void data.delete(k),
		setItem: (k, v) => void data.set(k, v)
	};
}

describe('saved queue filters', () => {
	it('saves, replaces by name, sorts, restores and deletes per user', () => {
		const s = memoryStorage();
		saveFilter('Asha@ManastuSpace.com', 'Route C units', { severity: 'HARD', route: 'C', flag_type: 'UNIT_AMBIGUITY' }, s);
		saveFilter('asha@manastuspace.com', 'Aged', { older_than_days: 7, sort: 'age' }, s);
		saveFilter('asha@manastuspace.com', 'Route C units', { route: 'C' }, s);
		expect(loadSaved('asha@manastuspace.com', s)).toEqual([
			{ name: 'Aged', query: 'older_than_days=7&sort=age' },
			{ name: 'Route C units', query: 'route=C' }
		]);
		expect(filtersOf(loadSaved('asha@manastuspace.com', s)[0])).toEqual({ older_than_days: 7, sort: 'age' });
		expect(loadSaved('other@manastuspace.com', s)).toEqual([]);
		expect(deleteFilter('asha@manastuspace.com', 'Aged', s).map((f) => f.name)).toEqual(['Route C units']);
	});

	it('survives missing or broken storage', () => {
		expect(loadSaved('a', null)).toEqual([]);
		const s = memoryStorage();
		s.setItem('dcl-queue-filters:a', '{broken');
		expect(loadSaved('a', s)).toEqual([]);
		expect(saveFilter('a', 'x', { route: 'C' }, null)).toEqual([{ name: 'x', query: 'route=C' }]);
	});
});

describe('SavedFilters', () => {
	it('names the current filters, then applies a saved set', async () => {
		localStorage.clear();
		const onApply = vi.fn();
		const view = render(SavedFilters, { owner: 'asha@manastuspace.com', filters: { severity: 'HARD', route: 'C' }, onApply });
		await fireEvent.click(screen.getByRole('button', { name: 'Save current' }));
		await fireEvent.input(screen.getByLabelText('Filter name'), { target: { value: 'HARD C' } });
		await fireEvent.submit(screen.getByRole('form', { name: 'Name these filters' }));
		expect((screen.getByLabelText('Saved filters') as HTMLSelectElement).value).toBe('HARD C');
		await view.rerender({ owner: 'asha@manastuspace.com', filters: {}, onApply });
		await fireEvent.change(screen.getByLabelText('Saved filters'), { target: { value: 'HARD C' } });
		expect(onApply).toHaveBeenCalledWith({ severity: 'HARD', route: 'C' });
	});
});
