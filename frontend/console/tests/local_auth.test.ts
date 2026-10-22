import { describe, expect, it, vi } from 'vitest';
import { ApiError, type LoginResponse } from '../src/lib/api_endpoint';
import { createLocalAuth, TOKEN_KEY } from '../src/lib/auth/local';

const NOW = Date.parse('2026-10-22T10:00:00Z');

function memoryStorage(): Storage {
	const data = new Map<string, string>();
	return {
		get length() {
			return data.size;
		},
		clear: () => data.clear(),
		getItem: (k) => data.get(k) ?? null,
		key: (i) => [...data.keys()][i] ?? null,
		removeItem: (k) => void data.delete(k),
		setItem: (k, v) => void data.set(k, v)
	};
}

const response = (expires_at: string): LoginResponse => ({
	access_token: 'jwt-1',
	token_type: 'bearer',
	expires_at,
	user: { oid: 'u1', name: 'Asha', email: 'asha@manastuspace.com', roles: ['viewer'] }
});

describe('local sign-in client', () => {
	it('keeps the token in memory and sessionStorage, so a reload stays signed in', async () => {
		const storage = memoryStorage();
		const post = vi.fn(async () => response('2026-10-22T22:00:00Z'));
		const first = createLocalAuth(storage, () => NOW, post);
		expect(await first.init()).toBeNull();
		await first.signIn('asha@manastuspace.com', 'pw');
		expect(post).toHaveBeenCalledWith('asha@manastuspace.com', 'pw');
		expect(await first.getToken()).toBe('jwt-1');

		const reloaded = createLocalAuth(storage, () => NOW + 3600_000, post);
		expect(await reloaded.init()).toBe('local');
		expect(await reloaded.getToken()).toBe('jwt-1');
	});

	it('drops an expired token and asks to sign in again', async () => {
		const storage = memoryStorage();
		storage.setItem(TOKEN_KEY, JSON.stringify({ token: 'old', expiresAt: NOW - 1 }));
		const auth = createLocalAuth(storage, () => NOW);
		expect(await auth.init()).toBeNull();
		expect(storage.getItem(TOKEN_KEY)).toBeNull();
		await expect(auth.getToken()).rejects.toEqual(new ApiError(401, 'Your session has ended. Sign in again.'));
	});

	it('forgets the token on sign out', async () => {
		const storage = memoryStorage();
		const auth = createLocalAuth(storage, () => NOW, async () => response('2026-10-22T22:00:00Z'));
		await auth.signIn('a', 'b');
		await auth.logout();
		expect(storage.getItem(TOKEN_KEY)).toBeNull();
		await expect(auth.getToken()).rejects.toBeInstanceOf(ApiError);
	});

	it('ignores a malformed stored value', async () => {
		const storage = memoryStorage();
		storage.setItem(TOKEN_KEY, '{not json');
		expect(await createLocalAuth(storage, () => NOW).init()).toBeNull();
	});
});
