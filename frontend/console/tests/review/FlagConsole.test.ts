import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';
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
		expect(options).toEqual(['leave open', 'Set channel unit', 'Set the unit, or no unit needed']);
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
					relation: 'sources_disagree',
					a: { label: 'T07.cfg', value: 'psig', provenance: 'cfg file', date: '2026-03-01' },
					b: { label: 'header', value: 'psi', provenance: '.dat header' }
				}
			})
		);
		expect(screen.getByText('Source A: T07.cfg')).toBeTruthy();
		expect(screen.getByText('psig')).toBeTruthy();
		expect(screen.queryByText(/Pipeline halted/)).toBeNull();
	});

	// allowed_actions as the server sends them (contract.py allowed_actions): a side only where it sets a document
	// field, "superseded" only when a side is a document, a failed check or a note only accepted or ignored.
	const conflict = (relation: 'sources_disagree' | 'check_failed' | 'note', docs = false) =>
		unitFlag({
			flag_id: 'c',
			flag_type: 'CONFLICT',
			severity: 'SOFT',
			allowed_actions:
				relation !== 'sources_disagree' ? ['accept_both', 'ignore'] : ['choose_source', ...(docs ? ['mark_superseded'] : []), 'accept_both', 'ignore'],
			suggested_resolution: null,
			evidence: {
				kind: 'conflict',
				subject: relation === 'sources_disagree' ? 'test_plan_id' : 'Main_Files',
				relation,
				a: { label: 'assembler', value: 'not included by any master', provenance: 'file 03 §1.3', doc_id: docs ? 'd1' : null },
				b: relation === 'note' ? null : { label: 'expected', value: 'a sharp edge', provenance: 'file 03 §C.6', doc_id: docs ? 'd2' : null }
			}
		});
	const choices = () => within(screen.getByRole('combobox')).getAllByRole('option').map((o) => o.textContent);

	it('shows a note as one finding with nothing to choose between', () => {
		show(conflict('note'));
		expect(screen.getByText(/What the system noticed/)).toBeTruthy();
		expect(screen.queryByText(/Source A|Source B|Expected/)).toBeNull();
		expect(choices()).toEqual(['leave open', 'Accept as it is', 'Ignore']);
	});

	it('shows a failed check as found against expected', () => {
		show(conflict('check_failed'));
		expect(screen.getByText('Found: assembler')).toBeTruthy();
		expect(screen.getByText('Expected')).toBeTruthy();
		expect(choices()).toEqual(['leave open', 'Accept as it is', 'Ignore']);
	});

	it('offers "mark superseded" only when the sides are documents', () => {
		show(conflict('sources_disagree'));
		expect(choices()).toEqual(['leave open', 'Pick the authoritative source', 'Accept both', 'Ignore']);
		cleanup();
		show(conflict('sources_disagree', true));
		expect(choices()).toContain('Mark a document superseded');
	});

	it('offers only the answers the server allows that the console can name', () => {
		show(unitFlag({ flag_type: 'PARSE_FAILURE', subject: 'file', allowed_actions: ['skip', 'mark_junk', 'future_action'], evidence: null, suggested_resolution: null }));
		expect(choices()).toEqual(['leave open', 'Skip whole file', 'Junk whole file']);
	});

	it('shows how a closed flag was resolved instead of the console', () => {
		show(unitFlag({ status: 'RESOLVED', resolved_by: 'asha@manastuspace.com', resolved_at: '2026-10-20T10:00:00Z', resolution: { action: 'skip' } }));
		expect(screen.queryByRole('combobox')).toBeNull();
		expect(screen.getByText(/Resolved on 2026-10-20 by asha@manastuspace.com/)).toBeTruthy();
	});
});
