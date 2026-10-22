import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import SectionMenu from '../../src/lib/components/settings/SectionMenu.svelte';
import { findSection, SETTINGS_SECTIONS } from '../../src/lib/components/settings/sections';
import { load as loadSection } from '../../src/routes/settings/[section]/+page';
import { load as loadIndex } from '../../src/routes/settings/+page';

describe('settings sections', () => {
	it('follows the sections of file 08 §3.2 in order', () => {
		expect(SETTINGS_SECTIONS.map((s) => s.title)).toEqual([
			'Sources',
			'Gate',
			'Routes',
			'Models',
			'Translation & language',
			'Chunking & index',
			'Flags & review',
			'Answer engine',
			'Prompts'
		]);
		expect(new Set(SETTINGS_SECTIONS.map((s) => s.id)).size).toBe(SETTINGS_SECTIONS.length);
	});

	it('names the scope keys under Sources', () => {
		expect(findSection('sources')?.keys).toContain('processing.scope');
	});

	it('marks the current section in the menu', () => {
		render(SectionMenu, { current: 'gate' });
		expect(screen.getByRole('link', { name: 'Gate' }).getAttribute('aria-current')).toBe('page');
		expect(screen.getAllByRole('link')).toHaveLength(10); // nine sections and Users
	});

	it('marks Users when it is the current page', () => {
		render(SectionMenu, { current: 'users' });
		expect(screen.getByRole('link', { name: 'Users' }).getAttribute('aria-current')).toBe('page');
	});

	it('redirects /settings to the first section and 404s unknown sections', () => {
		expect(() => loadIndex()).toThrow(expect.objectContaining({ status: 307, location: '/settings/sources' }));
		expect(loadSection({ params: { section: 'routes' } }).section.title).toBe('Routes');
		expect(() => loadSection({ params: { section: 'secrets' } })).toThrow(expect.objectContaining({ status: 404 }));
	});
});
