import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import NavBar from '../src/lib/components/shell/NavBar.svelte';

const user = (roles: string[]) => ({ oid: 'o', name: 'Asha Rao', email: 'a@x', roles: roles as never });

describe('NavBar', () => {
	it('hides areas the user cannot use', () => {
		render(NavBar, { user: user(['viewer']), currentPath: '/ops', onSignOut: () => {} });
		const links = screen.getAllByRole('link').map((a) => a.textContent?.trim());
		expect(links).toEqual(['DCL Console', 'Benchmark', 'Entities', 'Ops']);
		expect(screen.getByRole('link', { name: 'Ops' }).getAttribute('aria-current')).toBe('page');
	});

	it('shows review counts for reviewers and signs out', async () => {
		const onSignOut = vi.fn();
		render(NavBar, {
			user: user(['viewer', 'reviewer', 'admin']),
			currentPath: '/review',
			reviewCounts: { hard: 12, soft: 41 },
			liveStatus: 'open',
			onSignOut
		});
		expect(screen.getByRole('link', { name: /Review/ }).textContent).toContain('●12 HARD / 41 SOFT');
		expect(screen.getByRole('link', { name: 'Settings' })).toBeTruthy();
		expect(screen.getByLabelText('live updates open')).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
		expect(onSignOut).toHaveBeenCalledOnce();
	});
});
