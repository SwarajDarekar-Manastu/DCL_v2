import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import UsersAdmin from '../../src/lib/components/settings/UsersAdmin.svelte';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return { ...real, listAccounts: vi.fn(), createAccount: vi.fn(), updateAccount: vi.fn() };
});

const admin: api.LocalAccount = {
	user_id: 'u-admin',
	email: 'admin@manastuspace.com',
	display_name: 'Administrator',
	roles: ['viewer', 'reviewer', 'admin'],
	is_active: true,
	created_at: '2026-10-22T09:00:00Z',
	last_login_at: '2026-10-22T10:15:00Z'
};
const asha: api.LocalAccount = { ...admin, user_id: 'u-asha', email: 'asha@manastuspace.com', display_name: 'Asha', roles: ['viewer'], last_login_at: null };

beforeEach(() => {
	vi.mocked(api.listAccounts).mockReset().mockResolvedValue([admin, asha]);
	vi.mocked(api.createAccount).mockReset();
	vi.mocked(api.updateAccount).mockReset();
});

async function loadedRows() {
	await screen.findByText('asha@manastuspace.com');
	return screen.getAllByRole('row');
}

describe('UsersAdmin', () => {
	it('lists accounts with roles, status and last sign-in', async () => {
		render(UsersAdmin, { me: 'admin@manastuspace.com' });
		const rows = await loadedRows();
		expect(rows[1].textContent).toContain('admin@manastuspace.com (you)');
		expect(rows[1].textContent).toContain('2026-10-22 10:15');
		expect(rows[2].textContent).toContain('never');
		const ashaRoles = within(rows[2]).getAllByRole('checkbox') as HTMLInputElement[];
		expect(ashaRoles.map((c) => c.checked)).toEqual([true, false, false]);
	});

	it('adds a role with a PATCH of the full role list', async () => {
		vi.mocked(api.updateAccount).mockResolvedValue({ ...asha, roles: ['viewer', 'reviewer'] });
		render(UsersAdmin, { me: 'admin@manastuspace.com' });
		const rows = await loadedRows();
		await fireEvent.click(within(rows[2]).getAllByRole('checkbox')[1]);
		expect(api.updateAccount).toHaveBeenCalledWith('u-asha', { roles: ['viewer', 'reviewer'] });
		expect(await screen.findByText('Roles of asha@manastuspace.com saved.')).toBeTruthy();
	});

	it('shows the API refusal when the last admin would be removed', async () => {
		vi.mocked(api.updateAccount).mockRejectedValue(new api.ApiError(409, 'keep at least one active admin'));
		render(UsersAdmin, { me: 'admin@manastuspace.com' });
		const rows = await loadedRows();
		await fireEvent.click(within(rows[1]).getByRole('button', { name: 'Deactivate' }));
		expect(api.updateAccount).toHaveBeenCalledWith('u-admin', { is_active: false });
		expect((await screen.findByRole('alert')).textContent).toContain('keep at least one active admin');
	});

	it('creates an account from the form', async () => {
		vi.mocked(api.createAccount).mockResolvedValue({ ...asha, user_id: 'u-new', email: 'new@manastuspace.com' });
		render(UsersAdmin, { me: 'admin@manastuspace.com' });
		const form = await screen.findByRole('form', { name: 'New account' });
		await fireEvent.input(within(form).getByLabelText('Email'), { target: { value: ' new@manastuspace.com ' } });
		await fireEvent.input(within(form).getByLabelText('Name'), { target: { value: 'New Engineer' } });
		await fireEvent.input(within(form).getByLabelText(/Initial password/), { target: { value: 'a long password' } });
		await fireEvent.click(within(form).getByLabelText('reviewer'));
		await fireEvent.submit(form);
		await waitFor(() =>
			expect(api.createAccount).toHaveBeenCalledWith({
				email: 'new@manastuspace.com',
				display_name: 'New Engineer',
				roles: ['viewer', 'reviewer'],
				password: 'a long password'
			})
		);
	});

	it('resets a password from the row form', async () => {
		vi.mocked(api.updateAccount).mockResolvedValue(asha);
		render(UsersAdmin, { me: 'admin@manastuspace.com' });
		const rows = await loadedRows();
		await fireEvent.click(within(rows[2]).getByRole('button', { name: 'Reset password' }));
		const form = screen.getByRole('form', { name: 'Reset password of asha@manastuspace.com' });
		await fireEvent.input(within(form).getByLabelText(/New password/), { target: { value: 'another long one' } });
		await fireEvent.submit(form);
		await waitFor(() => expect(api.updateAccount).toHaveBeenCalledWith('u-asha', { password: 'another long one' }));
	});
});
