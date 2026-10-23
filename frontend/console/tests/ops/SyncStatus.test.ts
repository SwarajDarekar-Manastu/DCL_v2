import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { RootStatus } from '../../src/lib/api_endpoint';
import SyncStatus from '../../src/lib/components/ops/SyncStatus.svelte';

const root = (o: Partial<RootStatus>): RootStatus => ({
	root_name: 'APU',
	status: 'active',
	auth_status: 'OK',
	cloud_allowed: true,
	default_source_origin: 'internal',
	last_full_crawl_at: null,
	last_delta_at: null,
	crawl_in_progress: false,
	kept_current_by: 'poll',
	subscription_expires_at: null,
	counts: { items: 41823, by_status: {}, held_by_scope: 0, pending_download: 0, download_failed: 0, landed: 3379, waiting_dispatch: 0 },
	recent_errors: [],
	...o
});

describe('SyncStatus', () => {
	it('shows each root with sign-in, polling, backlog and errors', () => {
		render(SyncStatus, {
			roots: [root({}), root({ root_name: 'APS - AIT', auth_status: 'REAUTH_REQUIRED', crawl_in_progress: true, counts: { ...root({}).counts, download_failed: 2, waiting_dispatch: 123 }, recent_errors: [{ path: 'x', error: 'y' }] })]
		});
		const rows = screen
			.getAllByRole('row')
			.slice(1)
			.map((r) => [...r.querySelectorAll('td')].map((td) => td.textContent?.trim()));
		expect(rows[0]).toEqual(['APU', 'OK', 'poll', 'never', '0', '0', '0', '0']);
		expect(rows[1]).toEqual(['APS - AIT · crawling', 'sign-in needed', 'poll', 'never', '0', '2', '123', '1']);
		expect(screen.getByRole('link', { name: 'Sources settings' }).getAttribute('href')).toBe('/settings/sources');
	});
});
