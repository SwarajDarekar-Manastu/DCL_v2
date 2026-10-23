import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import Sidebar from '../src/lib/components/shell/Sidebar.svelte';

const user = (roles: string[]) => ({ oid: 'o', name: 'Asha Rao', email: 'a@x', roles: roles as never });

describe('Sidebar', () => {
	it('hides areas the user cannot use', () => {
		render(Sidebar, { user: user(['viewer']), currentPath: '/ops', onSignOut: () => {} });
		const links = screen.getAllByRole('link').map((a) => a.textContent?.trim());
		expect(links).toEqual(['DCL Console', 'Benchmark', 'Ops']);
		expect(screen.getByRole('link', { name: 'Ops' }).getAttribute('aria-current')).toBe('page');
		expect(screen.getByText('Viewer')).toBeTruthy();
	});

	it('marks the section of a nested page, not its siblings', () => {
		render(Sidebar, { user: user(['viewer', 'reviewer']), currentPath: '/review/rules', onSignOut: () => {} });
		expect(screen.getByRole('link', { name: /Review/ }).getAttribute('aria-current')).toBe('page');
		expect(screen.getByRole('link', { name: 'Benchmark' }).getAttribute('aria-current')).toBeNull();
	});

	it('shows review counts for reviewers and signs out', async () => {
		const onSignOut = vi.fn();
		render(Sidebar, {
			user: user(['viewer', 'reviewer', 'admin']),
			currentPath: '/review',
			reviewCounts: { hard: 12, soft: 41 },
			liveStatus: 'open',
			onSignOut
		});
		expect(screen.getByRole('link', { name: /Review/ }).textContent?.replace(/\s+/g, ' ')).toContain('12 HARD / 41 SOFT');
		expect(screen.getByRole('link', { name: 'Settings' })).toBeTruthy();
		expect(screen.getByLabelText('live updates open').textContent).toContain('Live updates');
		expect(screen.getByText('Admin')).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
		expect(onSignOut).toHaveBeenCalledOnce();
	});
});
