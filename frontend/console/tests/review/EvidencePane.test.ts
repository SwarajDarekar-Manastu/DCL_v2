import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { Evidence } from '../../src/lib/api_endpoint';
import EvidencePane from '../../src/lib/components/review/EvidencePane.svelte';
import { unitFlag } from './fixtures';

const unitEvidence = (note: string) => ({ ...unitFlag().evidence, note }) as Evidence;

describe('EvidencePane unit_telemetry note', () => {
	it('shows why the mapped channel cannot be used', () => {
		render(EvidencePane, { evidence: unitEvidence('mapped to AIN3 but the file has only AIN0–AIN2'), suggestion: null });
		expect(screen.getByRole('note').textContent).toBe('mapped to AIN3 but the file has only AIN0–AIN2');
	});

	it('shows nothing when the note is empty', () => {
		render(EvidencePane, { evidence: unitEvidence(''), suggestion: null });
		expect(screen.queryByRole('note')).toBeNull();
	});
});
