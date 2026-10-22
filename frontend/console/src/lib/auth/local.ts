// Local password sign-in (user decision 2026-10-22; Entra ID is future scope). The token lives in memory and
// in sessionStorage, so a reload keeps the session while closing the tab ends it. Roles come from /auth/me.

import { ApiError, login as postLogin } from '$lib/api_endpoint';
import type { AuthClient } from './msal';

export const TOKEN_KEY = 'dcl-session';

interface Stored {
	token: string;
	expiresAt: number; // epoch ms
}

export interface LocalAuthClient extends AuthClient {
	signIn(email: string, password: string): Promise<void>;
	clear(): void;
}

function read(storage: Storage | null): Stored | null {
	try {
		const parsed = JSON.parse(storage?.getItem(TOKEN_KEY) ?? 'null');
		return typeof parsed?.token === 'string' && typeof parsed?.expiresAt === 'number' ? parsed : null;
	} catch {
		return null;
	}
}

function safeStorage(): Storage | null {
	try {
		return globalThis.sessionStorage ?? null;
	} catch {
		return null;
	}
}

export function createLocalAuth(storage: Storage | null = safeStorage(), now: () => number = Date.now, signIn = postLogin): LocalAuthClient {
	let current: Stored | null = null;
	const valid = () => (current && current.expiresAt > now() ? current : null);
	const clear = () => {
		current = null;
		try {
			storage?.removeItem(TOKEN_KEY);
		} catch {
			// storage unavailable: memory is already cleared
		}
	};
	return {
		async init() {
			current = read(storage);
			if (!valid()) {
				clear();
				return null;
			}
			return 'local';
		},
		async signIn(email, password) {
			const response = await signIn(email, password);
			current = { token: response.access_token, expiresAt: Date.parse(response.expires_at) };
			try {
				storage?.setItem(TOKEN_KEY, JSON.stringify(current));
			} catch {
				// storage unavailable: the session lasts until the page is reloaded
			}
		},
		async login() {},
		async logout() {
			clear();
		},
		async getToken() {
			const session = valid();
			if (!session) {
				clear();
				throw new ApiError(401, 'Your session has ended. Sign in again.');
			}
			return session.token;
		},
		clear
	};
}
