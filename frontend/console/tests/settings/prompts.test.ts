import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../src/lib/api_endpoint';
import PromptsPanel from '../../src/lib/components/settings/PromptsPanel.svelte';
import { groupPrompts, sideBySide } from '../../src/lib/components/settings/prompts';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return { ...real, listPrompts: vi.fn(), getPrompt: vi.fn(), diffPrompts: vi.fn(), runPrompt: vi.fn() };
});

const v = (area: string, name: string, number: number, extra: Partial<api.PromptVersion> = {}): api.PromptVersion => ({
	area,
	name,
	version: `${name}.v${number}`,
	number,
	latest: false,
	in_use: false,
	variables: ['language', 'question'],
	chars: 900,
	...extra
});
const LIST = [v('engine', 'chitchat', 1), v('engine', 'chitchat', 2, { latest: true, in_use: true }), v('benchmark', 'judge', 1, { latest: true, in_use: true, variables: ['answer'] })];
const UNIFIED = '--- chitchat.v1\n+++ chitchat.v2\n@@ -1,3 +1,3 @@\n You are the DCL assistant.\n-Answer briefly.\n+Answer briefly and in ${language}.\n+Never invent numbers.\n';

beforeEach(() => {
	vi.mocked(api.listPrompts).mockReset().mockResolvedValue(LIST);
	vi.mocked(api.getPrompt).mockReset().mockImplementation(async (area, version) => ({ ...LIST.find((p) => p.version === version)!, system: `system of ${version}`, user_template: 'Q: ${question}' }));
	vi.mocked(api.diffPrompts).mockReset().mockResolvedValue({ area: 'engine', a: 'chitchat.v1', b: 'chitchat.v2', unified: UNIFIED });
	vi.mocked(api.runPrompt).mockReset();
});

describe('prompt helpers', () => {
	it('groups versions per prompt, newest first', () => {
		expect(groupPrompts(LIST).map((g) => [g.area, g.name, g.versions.map((x) => x.number)])).toEqual([
			['benchmark', 'judge', [1]],
			['engine', 'chitchat', [2, 1]]
		]);
	});

	it('turns a unified diff into side-by-side rows', () => {
		expect(sideBySide(UNIFIED)).toEqual([
			{ left: 'You are the DCL assistant.', right: 'You are the DCL assistant.', kind: 'same' },
			{ left: 'Answer briefly.', right: 'Answer briefly and in ${language}.', kind: 'changed' },
			{ left: null, right: 'Never invent numbers.', kind: 'added' }
		]);
	});
});

describe('PromptsPanel', () => {
	it('marks the version in use, shows its text and compares it with an older one', async () => {
		render(PromptsPanel);
		const nav = await screen.findByRole('navigation', { name: 'Prompts' });
		const current = await within(nav).findByRole('button', { name: /chitchat\.v2/ });
		expect(current.textContent).toContain('in use');
		await fireEvent.click(current);
		expect(await screen.findByText('system of chitchat.v2')).toBeTruthy();
		await fireEvent.change(screen.getByLabelText('Compare with'), { target: { value: 'chitchat.v1' } });
		expect(api.diffPrompts).toHaveBeenCalledWith('engine', 'chitchat.v1', 'chitchat.v2');
		const table = await screen.findByRole('table', { name: 'Diff chitchat.v1 → chitchat.v2' });
		expect([...table.querySelectorAll('tbody tr')].map((r) => r.getAttribute('data-kind'))).toEqual(['same', 'changed', 'added']);
	});

	it('runs a version on sample variables and shows text, tokens and latency', async () => {
		vi.mocked(api.runPrompt).mockResolvedValue({ version: 'chitchat.v2', model: 'gemini-3.8-flash', text: 'Hallo!', latency_ms: 812, input_tokens: 120, output_tokens: 4 });
		render(PromptsPanel);
		await fireEvent.click(await screen.findByRole('button', { name: /chitchat\.v2/ }));
		await fireEvent.input(screen.getByLabelText('language'), { target: { value: 'de' } });
		await fireEvent.input(screen.getByLabelText('question'), { target: { value: 'hi' } });
		await fireEvent.submit(screen.getByRole('form', { name: 'Run on sample' }));
		await waitFor(() =>
			expect(api.runPrompt).toHaveBeenCalledWith('engine', 'chitchat.v2', { variables: { language: 'de', question: 'hi' }, tier: 'flash', image_base64: null })
		);
		const out = await screen.findByRole('region', { name: 'Run result' });
		expect(out.textContent).toContain('gemini-3.8-flash · 812 ms · tokens in 120 / out 4');
		expect(out.textContent).toContain('Hallo!');
	});
});
