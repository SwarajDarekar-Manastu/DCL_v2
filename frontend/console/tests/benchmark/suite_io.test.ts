import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import SuiteClone from '../../src/lib/components/benchmark/SuiteClone.svelte';
import SuiteImport from '../../src/lib/components/benchmark/SuiteImport.svelte';
import { cloneId, clonePlan, parseSuiteFile } from '../../src/lib/components/benchmark/suite_io';
import { benchCase } from './fixtures';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return { ...real, importSuite: vi.fn(), exportSuite: vi.fn() };
});

const asCreate = (o: Partial<api.BenchmarkCase> = {}): api.BenchmarkCaseCreate => {
	const c = benchCase(o);
	return { case_id: c.case_id, suite: c.suite, status: c.status, category: c.category, question: c.question, spec: c.spec, difficulty: c.difficulty, notes: c.notes };
};
const SUITE: api.SuiteExport = {
	suite: 'telemetry',
	exported_at: '2026-10-23T08:00:00Z',
	cases: [
		asCreate({ case_id: 'tp07-t04-peak' }),
		asCreate({ case_id: 'tp07-t01-throughput-valve-open' }),
		asCreate({ case_id: 'tp07-old', status: 'retired' }),
		asCreate({ case_id: 'x'.repeat(75) })
	]
};

beforeEach(() => {
	vi.mocked(api.importSuite).mockReset();
	vi.mocked(api.exportSuite).mockReset().mockResolvedValue(SUITE);
});

describe('suite files', () => {
	it('accepts an exported suite and refuses files it cannot import', () => {
		expect(parseSuiteFile(JSON.stringify(SUITE))).toEqual({ ok: true, value: SUITE });
		expect(parseSuiteFile('{oops')).toEqual({ ok: false, error: 'not a JSON file' });
		expect(parseSuiteFile('{"cases": []}')).toEqual({ ok: false, error: 'no suite name ("suite")' });
		expect(parseSuiteFile(JSON.stringify({ suite: 'a', cases: [{ case_id: 'c', suite: 'b' }] }))).toEqual({ ok: false, error: 'case c is not a case of suite a' });
	});

	it('clones under new ids, never copying hold-out or retired cases', () => {
		const plan = clonePlan(SUITE, 'Telemetry Tuning');
		expect(plan.cases.map((c) => [c.case_id, c.suite])).toEqual([['telemetry-tuning.tp07-t04-peak', 'Telemetry Tuning']]);
		expect(plan.skipped).toEqual({ retired: ['tp07-old'], holdOut: ['tp07-t01-throughput-valve-open'], idTooLong: ['x'.repeat(75)] });
		expect(cloneId('a b/c', 'k')).toBe('a-b-c.k');
	});
});

describe('import and clone components', () => {
	it('imports a chosen file and reports the counts', async () => {
		vi.mocked(api.importSuite).mockResolvedValue({ created: 3, versioned: 1, unchanged: 0 });
		const onDone = vi.fn();
		render(SuiteImport, { onDone });
		const file = new File([JSON.stringify(SUITE)], 'telemetry.json', { type: 'application/json' });
		await fireEvent.change(screen.getByLabelText('Suite file'), { target: { files: [file] } });
		expect((await screen.findByRole('group', { name: 'Import suite' }).then(async (g) => { await waitFor(() => expect(g.textContent).toContain('4 cases for suite telemetry')); return g; })).textContent).toContain('exported 2026-10-23');
		await fireEvent.click(screen.getByRole('button', { name: 'Import' }));
		await waitFor(() => expect(api.importSuite).toHaveBeenCalledWith('telemetry', SUITE.cases));
		expect(onDone).toHaveBeenCalledWith('Suite telemetry imported: 3 created, 1 new versions, 0 unchanged.');
	});

	it('clones into a new, unused suite name', async () => {
		vi.mocked(api.importSuite).mockResolvedValue({ created: 1, versioned: 0, unchanged: 0 });
		const onDone = vi.fn();
		render(SuiteClone, { suite: 'telemetry', existing: ['telemetry', 'code'], onDone, onCancel: vi.fn() });
		const name = screen.getByLabelText(/New suite name/);
		await fireEvent.input(name, { target: { value: 'code' } });
		expect(screen.getByText(/A suite named code exists/)).toBeTruthy();
		await fireEvent.input(name, { target: { value: 'telemetry-tuning' } });
		expect(await screen.findByText(/Hold-out cases are never copied/)).toBeTruthy();
		await fireEvent.submit(screen.getByRole('form', { name: 'Clone suite telemetry' }));
		await waitFor(() => expect(api.importSuite).toHaveBeenCalledTimes(1));
		const [suite, cases] = vi.mocked(api.importSuite).mock.calls[0];
		expect([suite, cases.map((c) => c.case_id)]).toEqual(['telemetry-tuning', ['telemetry-tuning.tp07-t04-peak']]);
		expect(onDone).toHaveBeenCalledWith('Suite telemetry cloned as telemetry-tuning: 1 cases.');
	});
});
