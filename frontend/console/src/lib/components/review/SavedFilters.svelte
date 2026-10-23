<script lang="ts">
	import type { CaseFilters } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import { deleteFilter, filtersOf, loadSaved, queryOf, saveFilter, type SavedFilter } from './saved_filters';

	interface Props {
		owner: string;
		filters: CaseFilters;
		onApply: (filters: CaseFilters) => void;
	}

	let { owner, filters, onApply }: Props = $props();
	let saved = $state<SavedFilter[]>([]);
	let naming = $state(false);
	let name = $state('');

	$effect(() => {
		saved = loadSaved(owner);
	});

	let current = $derived(saved.find((f) => f.query === queryOf(filters)) ?? null);

	function save(event: SubmitEvent) {
		event.preventDefault();
		if (!name.trim()) return;
		saved = saveFilter(owner, name, filters);
		naming = false;
		name = '';
	}
</script>

<div class="flex flex-wrap items-end gap-2" aria-label="Saved queue filters" role="group">
	<label class="grid min-w-0 flex-1 gap-1"
		><span class="field-label">Saved filters</span>
		<select
			class="field"
			value={current?.name ?? ''}
			onchange={(e) => {
				const pick = saved.find((f) => f.name === (e.currentTarget as HTMLSelectElement).value);
				if (pick) onApply(filtersOf(pick));
			}}
		>
			<option value="">{saved.length ? 'choose…' : 'none yet'}</option>
			{#each saved as f (f.name)}<option value={f.name}>{f.name}</option>{/each}
		</select>
	</label>
	{#if current}
		<Button variant="ghost" size="sm" onclick={() => (saved = deleteFilter(owner, current.name))}>Delete</Button>
	{:else if !naming}
		<Button variant="outline" size="sm" onclick={() => (naming = true)}>Save current</Button>
	{/if}
	{#if naming}
		<form class="flex w-full gap-2" aria-label="Name these filters" onsubmit={save}>
			<input class="field min-w-0 flex-1" aria-label="Filter name" placeholder="e.g. HARD units, Route C" bind:value={name} />
			<Button type="submit" size="sm" disabled={!name.trim()}>Save</Button>
			<Button variant="ghost" size="sm" onclick={() => ((naming = false), (name = ''))}>Cancel</Button>
		</form>
	{/if}
</div>
