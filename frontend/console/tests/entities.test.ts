import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../src/lib/api_endpoint';
import EntitiesPanel from '../src/lib/components/entities/EntitiesPanel.svelte';
import { mergePlan, splitProblem } from '../src/lib/components/entities/entities';

vi.mock('../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../src/lib/api_endpoint')>();
	return { ...real, searchEntities: vi.fn(), mergeEntities: vi.fn(), splitEntity: vi.fn() };
});

const alias = (a: string) => ({ alias: a, alias_key: a.toLowerCase(), created_by: 'pipeline' });
const entity = (id: string, name: string, type: api.EntityType, aliases: string[], mentions = 3, documents = 2): api.Entity => ({
	entity_id: id,
	type,
	canonical_name: name,
	canonical_key: name.toLowerCase(),
	created_by: 'pipeline',
	aliases: aliases.map(alias),
	mentions,
	documents
});
const HTP = entity('e1', 'High-test peroxide', 'propellant', ['HTP', 'H2O2 98%'], 40, 12);
const PEROXIDE = entity('e2', 'Hydrogen peroxide', 'propellant', ['H2O2'], 9, 4);
const INCONEL = entity('e3', 'Inconel 718', 'material', ['IN718', 'Alloy 718', 'Inconel 625'], 7, 5);

beforeEach(() => {
	vi.mocked(api.searchEntities).mockReset().mockResolvedValue({ items: [HTP, PEROXIDE, INCONEL], total: 3 });
	vi.mocked(api.mergeEntities).mockReset();
	vi.mocked(api.splitEntity).mockReset();
});

describe('entity plans', () => {
	it('says what a merge moves and refuses mixed types', () => {
		expect(mergePlan([HTP, PEROXIDE], 'e1')).toMatchObject({ aliases: 1, mentions: 9, problem: null });
		expect(mergePlan([HTP, INCONEL], 'e1')?.problem).toBe('Only entities of one type merge: Inconel 718 is a material, High-test peroxide a propellant.');
		expect(mergePlan([HTP], 'e1')?.problem).toBe('Select at least one more entity to fold into this one.');
	});

	it('checks a split before sending it', () => {
		expect(splitProblem(INCONEL, [], 'x')).toBe('Pick the aliases that belong to the new entity.');
		expect(splitProblem(INCONEL, ['in718', 'alloy 718', 'inconel 625'], 'x')).toBe('Keep at least one alias on the original entity.');
		expect(splitProblem(INCONEL, ['inconel 625'], ' ')).toBe('Name the new entity.');
		expect(splitProblem(INCONEL, ['inconel 625'], 'Inconel 625')).toBeNull();
	});
});

describe('EntitiesPanel', () => {
	it('searches by name and type', async () => {
		render(EntitiesPanel);
		expect(await screen.findByText('High-test peroxide')).toBeTruthy();
		await fireEvent.input(screen.getByLabelText('Name or alias'), { target: { value: 'peroxide' } });
		await fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'propellant' } });
		await waitFor(() => expect(api.searchEntities).toHaveBeenLastCalledWith({ query: 'peroxide', type: 'propellant', limit: 50, offset: 0 }));
	});

	it('merges two selected entities into the one kept, after saying what moves', async () => {
		vi.mocked(api.mergeEntities).mockResolvedValue({ ...HTP, aliases: [...HTP.aliases, alias('H2O2'), alias('Hydrogen peroxide')], mentions: 49 });
		render(EntitiesPanel);
		await fireEvent.click(await screen.findByLabelText('Select High-test peroxide'));
		await fireEvent.click(screen.getByLabelText('Select Hydrogen peroxide'));
		const merge = screen.getByRole('region', { name: 'Merge' });
		expect(merge.textContent?.replace(/\s+/g, ' ')).toContain('Fold Hydrogen peroxide into High-test peroxide: 1 aliases and 9 mentions move.');
		await fireEvent.click(within(merge).getByRole('button', { name: 'Merge 2 entities' }));
		expect(api.mergeEntities).toHaveBeenCalledWith('e1', ['e2']);
		expect(await screen.findByText(/now 4 aliases, 49 mentions/)).toBeTruthy();
	});

	it('splits chosen aliases into a new entity', async () => {
		vi.mocked(api.splitEntity).mockResolvedValue(entity('e4', 'Inconel 625', 'material', ['Inconel 625'], 2, 1));
		render(EntitiesPanel);
		const row = (await screen.findByText('Inconel 718')).closest('tr') as HTMLElement;
		await fireEvent.click(within(row).getByRole('button', { name: 'Split' }));
		const form = screen.getByRole('form', { name: 'Split Inconel 718' });
		await fireEvent.click(within(form).getByLabelText('Inconel 625'));
		await fireEvent.input(within(form).getByLabelText('New entity name'), { target: { value: 'Inconel 625' } });
		await fireEvent.submit(form);
		await waitFor(() => expect(api.splitEntity).toHaveBeenCalledWith('e3', ['inconel 625'], 'Inconel 625'));
		expect(await screen.findByText('Split 1 alias off Inconel 718 into Inconel 625.')).toBeTruthy();
	});
});
