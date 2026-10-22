import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../src/lib/api_endpoint';
import LoginForm from '../src/lib/components/shell/LoginForm.svelte';

async function fill(email: string, password: string) {
	await fireEvent.input(screen.getByLabelText('Email'), { target: { value: email } });
	await fireEvent.input(screen.getByLabelText('Password'), { target: { value: password } });
	await fireEvent.submit(screen.getByRole('form', { name: 'Sign in' }));
}

describe('LoginForm', () => {
	it('submits the trimmed email and the password', async () => {
		const onSubmit = vi.fn(async () => {});
		render(LoginForm, { onSubmit });
		await fill(' asha@manastuspace.com ', 'pw with spaces ');
		expect(onSubmit).toHaveBeenCalledWith('asha@manastuspace.com', 'pw with spaces ');
	});

	it('shows the API answer for a wrong password or too many attempts', async () => {
		const onSubmit = vi.fn(async () => {
			throw new ApiError(429, 'too many failed sign-ins; try again shortly');
		});
		render(LoginForm, { onSubmit, notice: 'Your session has ended. Sign in again.' });
		expect(screen.getByText('Your session has ended. Sign in again.')).toBeTruthy();
		await fill('asha@manastuspace.com', 'x');
		expect((await screen.findByRole('alert')).textContent).toContain('too many failed sign-ins');
	});
});
