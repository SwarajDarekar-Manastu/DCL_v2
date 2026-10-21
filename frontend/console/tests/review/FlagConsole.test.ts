import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import type { FlagView } from '../../src/lib/api_endpoint';
import FlagConsole from '../../src/lib/components/review/FlagConsole.svelte';
import { unitFlag } from './fixtures';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => ({
	...(await importOriginal<object>()),
	presignAsset: vi.fn(async (uri: string) => ({ url: `https://minio.example/${uri}`, expires_in_s: 900 }))
}));

const idle = { result: null, error: '', current: false, busy: false };

function show(flag: FlagView, onPreview = () => {}) {
	return render(FlagConsole, { flag, draft: null, preview: idle, onPreview });
}

describe('FlagConsole', () => {
	it('offers only the allowed actions', () => {
		show(unitFlag());
		const options = screen.getAllByRole('option').map((o) => o.textContent);
		expect(options).toEqual(['leave open', 'Set channel unit', 'Set unit of the number']);
	});

	it('shows telemetry evidence: header line with the channel, stats, sanity and candidates', () => {
		const { container } = show(unitFlag());
		expect(container.querySelector('.hit')?.textContent).toContain('Channels: Time AIN0 AIN1');
		expect(screen.getByText('182.6')).toBeTruthy();
		expect(screen.getByText(/Sanity bounds for pressure: 0 … 30 bar/)).toBeTruthy();
		expect(screen.getByText(/Sibling T07.cfg declares psig/)).toBeTruthy();
		expect(screen.getByText(/Pipeline halted/)).toBeTruthy();
	});

	it('prefills the unit draft from the suggestion and asks for a preview', async () => {
		const onPreview = vi.fn();
		show(unitFlag(), onPreview);
		await fireEvent.change(screen.getByRole('combobox', { name: 'Resolution' }), { target: { value: 'set_unit' } });
		expect((screen.getByLabelText('Channel') as HTMLInputElement).value).toBe('AIN0');
		expect((screen.getByLabelText('psig') as HTMLInputElement).checked).toBe(true);
		await fireEvent.click(screen.getByRole('button', { name: 'Preview conversion' }));
		expect(onPreview).toHaveBeenCalledOnce();
	});

	it('picks a candidate unit into the draft', async () => {
		show(unitFlag({ suggested_resolution: null }));
		await fireEvent.click(screen.getByRole('button', { name: 'psi (absolute)' }));
		expect((screen.getByLabelText('psia') as HTMLInputElement).checked).toBe(true);
	});

	it('renders conflict and parse-failure evidence', () => {
		show(
			unitFlag({
				flag_id: 'c',
				flag_type: 'CONFLICT',
				severity: 'SOFT',
				allowed_actions: ['choose_source', 'accept_both'],
				suggested_resolution: null,
				evidence: {
					kind: 'conflict',
					subject: 'AIN0 unit',
					a: { label: 'T07.cfg', value: 'psig', provenance: 'cfg file', date: '2026-03-01' },
					b: { label: 'header', value: 'psi', provenance: '.dat header' }
				}
			})
		);
		expect(screen.getByText('Source A: T07.cfg')).toBeTruthy();
		expect(screen.getByText('psig')).toBeTruthy();
		expect(screen.queryByText(/Pipeline halted/)).toBeNull();
	});

	it('shows how a closed flag was resolved instead of the console', () => {
		show(unitFlag({ status: 'RESOLVED', resolved_by: 'asha@manastuspace.com', resolved_at: '2026-10-20T10:00:00Z', resolution: { action: 'skip' } }));
		expect(screen.queryByRole('combobox')).toBeNull();
		expect(screen.getByText(/Resolved on 2026-10-20 by asha@manastuspace.com/)).toBeTruthy();
	});
});
