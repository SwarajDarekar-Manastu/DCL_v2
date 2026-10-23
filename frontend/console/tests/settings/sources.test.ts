import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import RedispatchPanel from '../../src/lib/components/settings/RedispatchPanel.svelte';
import SourcesPanel from '../../src/lib/components/settings/SourcesPanel.svelte';
import { ago, signInActive } from '../../src/lib/components/settings/sources';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return {
		...real,
		listRoots: vi.fn(),
		signInState: vi.fn(),
		startSignIn: vi.fn(),
		previewSettings: vi.fn(),
		processEverything: vi.fn(),
		redispatchPreview: vi.fn(),
		redispatchRoute: vi.fn()
	};
});

const ROOT: api.RootStatus = {
	root_name: 'APS - AIT',
	status: 'active',
	auth_status: 'REAUTH_REQUIRED',
	cloud_allowed: true,
	default_source_origin: 'internal',
	last_full_crawl_at: '2026-10-21T19:00:00Z',
	last_delta_at: '2026-10-23T06:55:00Z',
	crawl_in_progress: false,
	kept_current_by: 'poll',
	subscription_expires_at: null,
	counts: { items: 110432, by_status: {}, held_by_scope: 4800, pending_download: 3, download_failed: 2, landed: 5120, waiting_dispatch: 123 },
	recent_errors: [{ path: 'APU/TP07/big.mp4', error: 'HELD_LARGE_FILE' }]
};

beforeEach(() => {
	vi.mocked(api.listRoots).mockReset().mockResolvedValue([ROOT]);
	vi.mocked(api.signInState).mockReset().mockResolvedValue({ state: 'idle' } as api.SignInState);
	for (const f of [api.startSignIn, api.previewSettings, api.processEverything, api.redispatchPreview, api.redispatchRoute]) vi.mocked(f).mockReset();
});
afterEach(() => vi.useRealTimers());

describe('sources helpers', () => {
	it('says how long ago and when sign-in is still running', () => {
		const now = Date.parse('2026-10-23T07:00:00Z');
		expect([ago(null, now), ago('2026-10-23T06:59:40Z', now), ago('2026-10-23T06:00:00Z', now), ago('2026-10-21T07:00:00Z', now)]).toEqual(['never', 'just now', '1 h ago', '2 d ago']);
		expect(['idle', 'starting', 'pending', 'signed_in', 'failed'].map((state) => signInActive({ state } as api.SignInState))).toEqual([false, true, true, false, false]);
	});
});

describe('SourcesPanel', () => {
	it('lists roots with sign-in state, counts and recent errors', async () => {
		render(SourcesPanel);
		const row = (await screen.findByText('APS - AIT')).closest('tr') as HTMLElement;
		expect(row.textContent).toContain('sign-in needed');
		expect(row.textContent).toContain('110,432');
		expect(row.textContent).toContain('123');
		expect(screen.getByText('1 recent error')).toBeTruthy();
	});

	it('shows the device code to the operator and keeps polling until signed in', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		vi.mocked(api.startSignIn).mockResolvedValue({ state: 'starting' } as api.SignInState);
		vi.mocked(api.signInState)
			.mockResolvedValueOnce({ state: 'idle' } as api.SignInState)
			.mockResolvedValueOnce({ state: 'pending', user_code: 'ABCD-1234', verification_uri: 'https://microsoft.com/devicelogin', expires_at: '2026-10-23T07:15:00Z' } as api.SignInState)
			.mockResolvedValue({ state: 'signed_in' } as api.SignInState);
		render(SourcesPanel);
		await fireEvent.click(await screen.findByRole('button', { name: 'Start device-code sign-in' }));
		await vi.advanceTimersByTimeAsync(3100);
		expect((await screen.findByLabelText('Sign-in code')).textContent).toBe('ABCD-1234');
		expect(screen.getByRole('link', { name: 'https://microsoft.com/devicelogin' })).toBeTruthy();
		await vi.advanceTimersByTimeAsync(3100);
		expect(await screen.findByText(/Signed in\./)).toBeTruthy();
	});

	it('previews process-everything before doing it', async () => {
		vi.mocked(api.previewSettings).mockResolvedValue({
			impacts: [{ key: 'processing.scope', summary: '3429 landed files will be processed', counts: {}, bytes: 0, by_extension: {}, estimated_cost_usd: null, cost_note: 'no llm_calls ledger or model prices yet; counts only' }]
		});
		vi.mocked(api.processEverything).mockResolvedValue({ applied: [{ key: 'processing.scope', version: 4, before: [], after: [] }], impacts: [], released_downloads: 0, held_downloads: 0, dispatch_started: true });
		render(SourcesPanel);
		await fireEvent.click(await screen.findByRole('button', { name: 'Preview' }));
		expect(api.previewSettings).toHaveBeenCalledWith({ changes: [{ key: 'processing.scope', value: [] }] });
		expect((await screen.findByRole('list', { name: 'Process everything impact' })).textContent).toContain('3429 landed files');
		expect(api.processEverything).not.toHaveBeenCalled();
		await fireEvent.click(screen.getByRole('button', { name: 'Process everything' }));
		expect(await screen.findByText(/now version 4/)).toBeTruthy();
	});
});

describe('RedispatchPanel', () => {
	it('counts first, then re-processes the route', async () => {
		vi.mocked(api.redispatchPreview).mockResolvedValue({ route: 'C', documents: 18, sample: ['Test 01_Data_Analysis', 'Setup'] });
		vi.mocked(api.redispatchRoute).mockResolvedValue({ route: 'C', redispatched: 18, started: true });
		render(RedispatchPanel);
		await fireEvent.change(screen.getByLabelText('Route'), { target: { value: 'C' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Count documents' }));
		expect(api.redispatchPreview).toHaveBeenCalledWith('C');
		const go = await screen.findByRole('button', { name: 'Re-process 18 documents' });
		expect(screen.getByRole('region', { name: 'Re-process documents' }).textContent).toContain('Test 01_Data_Analysis');
		await fireEvent.click(go);
		await waitFor(() => expect(api.redispatchRoute).toHaveBeenCalledWith('C'));
		expect(await screen.findByText('Route C: 18 documents sent for re-processing.')).toBeTruthy();
	});
});
