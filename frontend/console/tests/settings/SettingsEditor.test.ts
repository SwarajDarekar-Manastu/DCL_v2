import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import SettingsEditor from '../../src/lib/components/settings/SettingsEditor.svelte';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return {
		...real,
		listSettings: vi.fn(),
		previewSettings: vi.fn(),
		applySettings: vi.fn(),
		settingHistory: vi.fn(),
		rollbackSettings: vi.fn()
	};
});

const entry = (key: string, value: unknown, version = 1, by = 'seed'): api.ConfigEntry => ({
	key,
	value: value as api.ConfigEntry['value'],
	version,
	updated_by: by,
	updated_at: '2026-10-22T09:00:00Z',
	description: null
});

const ENTRIES = [
	entry('gate.max_download_bytes', 4294967296),
	entry('gate.junk_names', ['.DS_Store', 'Thumbs.db'], 2),
	entry('routes.C.enabled', true),
	entry('processing.scope', ['E1'])
];
const PATTERNS = ['gate.*', 'flags.strict_mode'];
const appliedResult = (key: string, version: number): api.ConfigApplied => ({
	applied: [{ key, version, before: null, after: null }],
	impacts: [],
	released_downloads: 0,
	held_downloads: 0,
	dispatch_started: false
});

beforeEach(() => {
	for (const fn of [api.listSettings, api.previewSettings, api.applySettings, api.settingHistory, api.rollbackSettings]) vi.mocked(fn).mockReset();
	vi.mocked(api.listSettings).mockResolvedValue({ items: ENTRIES });
});

const field = (key: string) => screen.getByLabelText(`Value of ${key}`) as HTMLInputElement;

describe('SettingsEditor', () => {
	it("shows the section's keys with typed editors, including keys not set yet", async () => {
		render(SettingsEditor, { patterns: PATTERNS });
		await screen.findByText('gate.max_download_bytes');
		const keys = within(screen.getByRole('list', { name: 'Configuration keys' }))
			.getAllByRole('listitem')
			.map((li) => li.querySelector('code')?.textContent);
		expect(keys).toEqual(['flags.strict_mode', 'gate.junk_names', 'gate.max_download_bytes']);
		expect(field('gate.max_download_bytes').value).toBe('4294967296');
		expect(field('gate.junk_names').value).toBe('.DS_Store\nThumbs.db');
		expect(screen.getByText('not set')).toBeTruthy();
	});

	it('previews then applies one batch with the versions it saw and the reason', async () => {
		vi.mocked(api.previewSettings).mockResolvedValue({
			impacts: [{ key: 'gate.junk_names', summary: '3 indexed files would now be rejected', counts: { rejected: 3 }, bytes: 2_500_000, by_extension: { '.ini': 1, '.db': 2 }, estimated_cost_usd: null, cost_note: null }]
		});
		vi.mocked(api.applySettings).mockResolvedValue(appliedResult('gate.junk_names', 3));
		render(SettingsEditor, { patterns: PATTERNS });
		await screen.findByText('gate.max_download_bytes');
		await fireEvent.input(field('gate.junk_names'), { target: { value: '.DS_Store\nThumbs.db\ndesktop.ini' } });
		expect(screen.getByRole('button', { name: 'Apply' }).hasAttribute('disabled')).toBe(true); // preview first
		const changes = [{ key: 'gate.junk_names', value: ['.DS_Store', 'Thumbs.db', 'desktop.ini'], expected_version: 2 }];
		await fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
		expect(api.previewSettings).toHaveBeenCalledWith({ changes });
		expect(await screen.findByText(/3 indexed files would now be rejected/)).toBeTruthy();
		expect(screen.getByRole('list', { name: 'Impact' }).textContent).toContain('2.5 MB');
		expect(screen.getByRole('list', { name: 'Impact' }).textContent).toContain('.db 2, .ini 1');
		await fireEvent.input(screen.getByLabelText(/Reason/), { target: { value: 'skip desktop.ini' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
		await waitFor(() => expect(api.applySettings).toHaveBeenCalledWith({ changes, description: 'skip desktop.ini' }));
		expect(await screen.findByText('Saved gate.junk_names (v3).')).toBeTruthy();
		expect(api.listSettings).toHaveBeenCalledTimes(2);
	});

	it('refuses malformed input before sending and shows API errors on their key', async () => {
		render(SettingsEditor, { patterns: PATTERNS });
		await screen.findByText('gate.max_download_bytes');
		await fireEvent.input(field('gate.max_download_bytes'), { target: { value: 'lots' } });
		expect(screen.getByRole('alert').textContent).toBe('not a number');
		expect(screen.getByRole('button', { name: 'Preview' }).hasAttribute('disabled')).toBe(true);

		vi.mocked(api.previewSettings).mockRejectedValue(new api.ApiError(422, 'x', { 'gate.max_download_bytes': 'must be positive' }));
		await fireEvent.input(field('gate.max_download_bytes'), { target: { value: '-1' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
		const alerts = await screen.findAllByRole('alert');
		expect(alerts.map((a) => a.textContent)).toContain('must be positive');
	});

	it('reloads the current values when someone else changed them (409)', async () => {
		vi.mocked(api.previewSettings).mockResolvedValue({ impacts: [] });
		vi.mocked(api.applySettings).mockRejectedValue(new api.ApiError(409, 'gate.junk_names: expected version 2, current is 3'));
		render(SettingsEditor, { patterns: PATTERNS });
		await screen.findByText('gate.max_download_bytes');
		vi.mocked(api.listSettings).mockResolvedValue({ items: [ENTRIES[0], entry('gate.junk_names', ['x'], 3, 'other@manastuspace.com')] });
		await fireEvent.input(field('gate.junk_names'), { target: { value: 'mine' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
		await screen.findByText('No measurable effect on documents.');
		await fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
		expect((await screen.findByText(/Someone else changed this section/)).textContent).toContain('current is 3');
		expect(field('gate.junk_names').value).toBe('x');
	});

	it('restores an older version from the history', async () => {
		vi.mocked(api.settingHistory).mockResolvedValue({ items: [entry('gate.junk_names', ['a', 'b'], 2, 'admin'), entry('gate.junk_names', ['a'], 1)] });
		vi.mocked(api.rollbackSettings).mockResolvedValue(appliedResult('gate.junk_names', 3));
		render(SettingsEditor, { patterns: PATTERNS });
		await screen.findByText('gate.max_download_bytes');
		const row = screen.getByText('gate.junk_names').closest('li') as HTMLElement;
		await fireEvent.click(within(row).getByRole('button', { name: 'History' }));
		const history = await screen.findByRole('list', { name: 'History of gate.junk_names' });
		await waitFor(() => expect(within(history).getAllByRole('listitem')).toHaveLength(2));
		expect(within(history).getAllByRole('listitem')[0].textContent).toContain('current');
		await fireEvent.click(within(history).getByRole('button', { name: 'Restore' }));
		expect(api.rollbackSettings).toHaveBeenCalledWith({ versions: { 'gate.junk_names': 1 }, description: 'restore version 1' });
		expect(await screen.findByText('gate.junk_names restored to version 1 (now version 3).')).toBeTruthy();
	});
});
