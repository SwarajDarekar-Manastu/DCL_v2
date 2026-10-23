// Settings › Sources helpers (file 08 §3.2 Sources) over S1's /sync routes.

import type { SignInState } from '$lib/api_endpoint';

export const SIGN_IN_POLL_MS = 3000;

/** The device-code sign-in is still running (the page keeps polling). */
export const signInActive = (state: SignInState | null) => state?.state === 'starting' || state?.state === 'pending';

/** "3 h ago", "2 d ago", "just now"; "never" for no time. */
export function ago(at: string | null | undefined, now: number = Date.now()): string {
	if (!at) return 'never';
	const s = Math.max(0, Math.round((now - Date.parse(at)) / 1000));
	if (s < 60) return 'just now';
	if (s < 3600) return `${Math.round(s / 60)} min ago`;
	if (s < 86400) return `${Math.round(s / 3600)} h ago`;
	return `${Math.round(s / 86400)} d ago`;
}

export const ROUTES = ['A1', 'A2', 'B', 'C', 'D', 'E', 'F', 'G'] as const;
