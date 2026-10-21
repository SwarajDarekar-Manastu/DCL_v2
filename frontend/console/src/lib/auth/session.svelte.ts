// Signed-in state for the whole Console. Roles come from the server (GET /auth/me), not from the token.

import { ApiError, configureApi, getMe, type ConsoleUser } from '$lib/api_endpoint';
import { getConfig, type ConsoleConfig } from '$lib/config';
import { createDevAuth, createMsalAuth, type AuthClient } from './msal';
import type { ConsoleRole } from './roles';

export type SessionStatus = 'loading' | 'signed_out' | 'signed_in' | 'error';

class Session {
	status = $state<SessionStatus>('loading');
	user = $state<ConsoleUser | null>(null);
	error = $state('');
	auth: AuthClient | null = null;

	async signIn() {
		await this.auth?.login();
	}

	async signOut() {
		await this.auth?.logout();
	}
}

export const session = new Session();

export async function startSession(configOverride?: ConsoleConfig, auth?: AuthClient): Promise<void> {
	session.status = 'loading';
	session.error = '';
	try {
		const config = configOverride ?? getConfig();
		session.auth = auth ?? (config.auth.mode === 'dev' ? createDevAuth() : createMsalAuth(config.auth));
		const client = session.auth;
		configureApi({ baseUrl: config.apiBaseUrl, wsUrl: config.wsUrl, getToken: () => client.getToken() });
		const accountName = await client.init();
		if (!accountName) {
			session.status = 'signed_out';
			return;
		}
		session.user =
			config.auth.mode === 'dev'
				? { oid: 'dev', name: accountName, email: 'dev@localhost', roles: config.auth.devRoles as ConsoleRole[] }
				: await getMe();
		session.status = 'signed_in';
	} catch (error) {
		session.status = 'error';
		session.error = error instanceof ApiError ? error.detail : String(error);
	}
}
