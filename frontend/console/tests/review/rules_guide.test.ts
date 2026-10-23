import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RuleForm from '../../src/lib/components/review/RuleForm.svelte';
import RulesGuide from '../../src/lib/components/review/RulesGuide.svelte';
import { exampleBody, GUIDE_STEPS, RULE_TYPE_HELP } from '../../src/lib/components/review/rules_guide';

afterEach(cleanup);

describe('rules guide content', () => {
	it('has unique steps, each with text and what the reader gets', () => {
		expect(new Set(GUIDE_STEPS.map((s) => s.id)).size).toBe(GUIDE_STEPS.length);
		for (const step of GUIDE_STEPS) {
			expect(step.title.length).toBeGreaterThan(10);
			expect(step.summary.length).toBeGreaterThan(20);
			expect(step.points.length).toBeGreaterThan(0);
			expect(step.get.length).toBeGreaterThan(10);
		}
	});

	it('shows real screenshots, with a caption, on the steps that create and apply a rule', () => {
		const withImages = GUIDE_STEPS.filter((s) => s.images.length);
		expect(withImages.map((s) => s.id)).toEqual(['idea', 'folder', 'columns', 'save', 'apply', 'after', 'audit', 'from-case']);
		for (const step of withImages) {
			for (const image of step.images) {
				expect(image.src).toMatch(/\.png/);
				expect(image.alt.length).toBeGreaterThan(10);
				expect(image.caption.length).toBeGreaterThan(10);
			}
		}
		expect(GUIDE_STEPS.find((s) => s.id === 'from-case')?.images).toHaveLength(2);
	});

	it('teaches the page first: pick files, say what the columns are, save, then a person applies', () => {
		expect(GUIDE_STEPS.map((s) => s.id).slice(0, 5)).toEqual(['idea', 'folder', 'columns', 'save', 'apply']);
		expect(GUIDE_STEPS[3].get).toMatch(/None is approved/);
		expect(GUIDE_STEPS.find((s) => s.id === 'audit')?.title).toMatch(/Audit/);
	});

	it('has an example body that is a JSON object for every rule type', () => {
		for (const type of Object.keys(RULE_TYPE_HELP) as (keyof typeof RULE_TYPE_HELP)[]) {
			const parsed = JSON.parse(exampleBody(type));
			expect(parsed && typeof parsed === 'object' && !Array.isArray(parsed)).toBe(true);
			expect(RULE_TYPE_HELP[type].what.length).toBeGreaterThan(15);
		}
	});
});

describe('RulesGuide', () => {
	const openGuide = async () => {
		render(RulesGuide);
		await fireEvent.click(screen.getByRole('button', { name: 'How rules work' }));
		return screen.findByRole('dialog');
	};

	it('opens a dialog on the first step and moves through the steps', async () => {
		const dialog = await openGuide();
		expect(dialog.textContent).toContain(`Step 1 of ${GUIDE_STEPS.length}`);
		expect(dialog.querySelector('h3')?.textContent).toBe(GUIDE_STEPS[0].title);
		expect(dialog.querySelector('img')?.getAttribute('alt')).toBe(GUIDE_STEPS[0].images[0].alt);
		await fireEvent.click(screen.getByRole('button', { name: /^Next/ }));
		expect(dialog.querySelector('h3')?.textContent).toBe(GUIDE_STEPS[1].title);
		await fireEvent.click(screen.getByRole('button', { name: /Back/ }));
		expect(dialog.querySelector('h3')?.textContent).toBe(GUIDE_STEPS[0].title);
	});

	it('jumps to a step from the list and closes on the last one', async () => {
		const dialog = await openGuide();
		await fireEvent.click(screen.getByRole('button', { name: new RegExp(GUIDE_STEPS.at(-1)!.title.replace(/[()]/g, '.')) }));
		expect(dialog.querySelector('h3')?.textContent).toBe(GUIDE_STEPS.at(-1)!.title);
		expect(dialog.querySelector('img')).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: 'Got it' }));
		await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
	});
});

describe('RuleForm', () => {
	it('explains the chosen type and fills an example that follows the type until it is edited', async () => {
		const onSubmit = vi.fn();
		render(RuleForm, { busy: false, onSubmit });
		const body = screen.getByRole('textbox', { name: /Body/ }) as HTMLTextAreaElement;
		expect(screen.getByText(RULE_TYPE_HELP.channel_proposal.what)).toBeTruthy();
		expect(body.value).toBe(exampleBody('channel_proposal'));

		const type = screen.getByRole('combobox', { name: 'Rule type' }) as HTMLSelectElement;
		await fireEvent.change(type, { target: { value: 'ignore_pattern' } });
		expect(screen.getByText(RULE_TYPE_HELP.ignore_pattern.what)).toBeTruthy();
		expect(body.value).toBe(exampleBody('ignore_pattern'));

		await fireEvent.input(body, { target: { value: '{"reason": "my own words"}' } });
		await fireEvent.change(type, { target: { value: 'origin_override' } });
		expect(body.value).toBe('{"reason": "my own words"}');
	});

	it('never offers a file approval as something to write by hand, and warns for kinds nothing reads', async () => {
		render(RuleForm, { busy: false, onSubmit: vi.fn() });
		const type = screen.getByRole('combobox', { name: 'Rule type' }) as HTMLSelectElement;
		const options = [...type.options].map((o) => o.value);
		expect(options).toEqual(['channel_proposal', 'schema_mapping', 'supersession', 'ignore_pattern', 'origin_override']);
		expect(screen.queryByText(/Nothing in the pipeline reads this kind/)).toBeNull();
		await fireEvent.change(type, { target: { value: 'supersession' } });
		expect(screen.getByText(/Nothing in the pipeline reads this kind/)).toBeTruthy();
	});
});
