import { describe, expect, it } from 'vitest';
import { breadcrumbs, documentTitle } from '../src/lib/components/shell/breadcrumbs';
import { applyTheme, readPreference, resolveTheme } from '../src/lib/theme.svelte';

describe('breadcrumbs', () => {
	it('links the section and names the page', () => {
		expect(breadcrumbs('/')).toEqual([{ label: 'Home' }]);
		expect(breadcrumbs('/review')).toEqual([{ label: 'Review' }]);
		expect(breadcrumbs('/review/rules')).toEqual([{ label: 'Review', href: '/review' }, { label: 'Rules' }]);
		expect(documentTitle('/settings/users')).toBe('Users · Settings · DCL Console');
		expect(breadcrumbs('/settings/gate')).toEqual([{ label: 'Settings', href: '/settings' }, { label: 'Gate' }]);
		expect(breadcrumbs('/benchmark/suites/core%20suite')).toEqual([
			{ label: 'Benchmark', href: '/benchmark' },
			{ label: 'Suites' },
			{ label: 'core suite' }
		]);
		expect(breadcrumbs('/benchmark/cases/new').at(-1)).toEqual({ label: 'New case' });
		expect(breadcrumbs('/benchmark/runs/0b6f1d3e-2a4c-4e8f-9c1a-5d7e3f2b1a90').at(-1)).toEqual({ label: '0b6f1d3e' });
		expect(breadcrumbs('/benchmark/retrieval').at(-1)).toEqual({ label: 'Retrieval lab' });
		expect(breadcrumbs('/docs/doc-7/viewer')).toEqual([{ label: 'Documents' }, { label: 'doc-7' }, { label: 'Viewer' }]);
	});

	it('builds the document title from the trail', () => {
		expect(documentTitle('/')).toBe('DCL Console');
		expect(documentTitle('/review/rules')).toBe('Rules · Review · DCL Console');
	});
});

describe('theme', () => {
	it('reads light, dark or system from storage and tolerates a broken store', () => {
		expect(readPreference({ getItem: () => 'dark' })).toBe('dark');
		expect(readPreference({ getItem: () => 'purple' })).toBe('system');
		expect(readPreference(null)).toBe('system');
		expect(
			readPreference({
				getItem: () => {
					throw new Error('denied');
				}
			})
		).toBe('system');
	});

	it('follows the system only when no manual choice is set', () => {
		expect(resolveTheme('system', true)).toBe('dark');
		expect(resolveTheme('system', false)).toBe('light');
		expect(resolveTheme('light', true)).toBe('light');
		expect(resolveTheme('dark', false)).toBe('dark');
	});

	it('toggles the dark class on the root element', () => {
		const root = document.createElement('html');
		applyTheme(root, 'dark');
		expect(root.classList.contains('dark')).toBe(true);
		applyTheme(root, 'light');
		expect(root.classList.contains('dark')).toBe(false);
	});
});
