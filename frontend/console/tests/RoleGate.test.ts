import { render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { describe, expect, it } from 'vitest';
import RoleGate from '../src/lib/components/shell/RoleGate.svelte';

const children = createRawSnippet(() => ({ render: () => '<p>secret settings</p>' }));

describe('RoleGate', () => {
	it('renders the page for a sufficient role', () => {
		render(RoleGate, { roles: ['viewer', 'reviewer', 'admin'], role: 'admin', children });
		expect(screen.getByText('secret settings')).toBeTruthy();
	});

	it('explains the missing role instead of rendering the page', () => {
		render(RoleGate, { roles: ['viewer', 'reviewer'], role: 'admin', children });
		expect(screen.queryByText('secret settings')).toBeNull();
		expect(screen.getByRole('alert').textContent).toContain('admin');
	});
});
