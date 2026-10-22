// Signed-in state for the whole Console. Roles come from the server (GET /auth/me), not from the token.

import { ApiError, configureApi, getMe, type ConsoleUser } from '$lib/api_endpoint';
import { getConfig, type AuthMode, type ConsoleConfig } from '$lib/config';
import { createLocalAuth, type LocalAuthClient } from './local';
import { createDevAuth, createMsalAuth, type AuthClient } from './msal';

export type SessionStatus = 'loading' | 'signed_out' | 'signed_in' | 'error';

const describe = (error: unknown) => (error instanceof ApiError ? error.detail : String(error));

class Session {
	status = $state<SessionStatus>('loading');
	user = $state<ConsoleUser | null>(null);
	error = $state('');
	/** Shown on the sign-in form, e.g. after a session expired */
	notice = $state('');
	mode = $state<AuthMode>('local');
	auth: AuthClient | null = null;

	/** Microsoft sign-in (msal mode): redirects. */
	async signIn() {
		await this.auth?.login();
	}

	/** Local sign-in: email and password; throws ApiError for the form to show. */
	async signInWithPassword(email: string, password: string) {
		const local = this.auth as LocalAuthClient;
		await local.signIn(email, password);
		this.notice = '';
		try {
			this.user = await getMe();
			this.status = 'signed_in';
		} catch (error) {
			local.clear();
			throw error;
		}
	}

	async signOut() {
		await this.auth?.logout();
		if (this.mode === 'local') this.end('');
	}

	/** Back to the sign-in form (local mode), keeping the page the user was on. */
	end(notice: string) {
		this.user = null;
		this.notice = notice;
		this.status = 'signed_out';
	}
}

export const session = new Session();

function clientFor(config: ConsoleConfig): AuthClient {
	if (config.auth.mode === 'local') return createLocalAuth();
	if (config.auth.mode === 'dev') return createDevAuth(config.auth.devToken);
	return createMsalAuth(config.auth);
}

export async function startSession(configOverride?: ConsoleConfig, auth?: AuthClient): Promise<void> {
	session.status = 'loading';
	session.error = '';
	try {
		const config = configOverride ?? getConfig();
		session.mode = config.auth.mode;
		session.auth = auth ?? clientFor(config);
		const client = session.auth;
		const onUnauthorized =
			config.auth.mode === 'local'
				? () => {
						(client as LocalAuthClient).clear();
						if (session.status === 'signed_in') session.end('Your session has ended. Sign in again.');
					}
				: undefined;
		configureApi({ baseUrl: config.apiBaseUrl, wsUrl: config.wsUrl, getToken: () => client.getToken(), onUnauthorized });
		const accountName = await client.init();
		if (!accountName) {
			session.status = 'signed_out';
			return;
		}
		session.user = await getMe(); // roles always come from the server
		session.status = 'signed_in';
	} catch (error) {
		if (session.mode === 'local' && error instanceof ApiError && error.status === 401) {
			session.end('Your session has ended. Sign in again.');
			return;
		}
		session.status = 'error';
		session.error = describe(error);
	}
}
