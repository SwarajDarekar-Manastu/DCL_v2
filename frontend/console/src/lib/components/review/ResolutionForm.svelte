<script lang="ts">
	import type { Resolution } from '$lib/api_endpoint';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import XIcon from '@lucide/svelte/icons/x';
	import { Button } from '$lib/components/ui/button';
	import { PRESSURE_CHOICES } from './resolution';

	interface Props {
		draft: Resolution;
		/** The documents of the disagreement, for "mark superseded". */
		documents?: { doc_id: string; label: string }[];
	}

	let { draft = $bindable(), documents = [] }: Props = $props();

	function pickPressure(label: string) {
		if (draft.action !== 'set_unit') return;
		const choice = PRESSURE_CHOICES.find((c) => c.label === label);
		if (!choice) return;
		draft.unit = choice.unit;
		draft.gauge_or_abs = choice.gauge_or_abs;
		draft.expression = null;
	}

	const chosenPressure = $derived(
		draft.action === 'set_unit'
			? (PRESSURE_CHOICES.find((c) => c.unit === draft.unit && c.gauge_or_abs === draft.gauge_or_abs)?.label ?? '')
			: ''
	);

	let newKey = $state('');
	let newSection = $state('');

	// Layout classes shared by the controls of this form.
	const FIELD = 'grid gap-1';
	const CHIP =
		'has-[:checked]:border-foreground has-[:checked]:bg-muted hover:bg-muted/60 flex h-7 cursor-pointer items-center gap-1.5 rounded-md border px-2 text-[13px] transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ring';
</script>

{#if draft.action === 'set_unit'}
	<fieldset class="m-0 grid gap-3 border-0 p-0">
		<legend class="mb-2 flex items-center gap-2 text-[13px] font-medium">
			Unit of channel <input class="field h-7 w-36 font-mono" aria-label="Channel" bind:value={draft.channel} />
		</legend>
		<label class={FIELD}><span class="field-label">Quantity</span> <input class="field" bind:value={draft.quantity} /></label>
		{#if draft.quantity === 'pressure'}
			<div class="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Pressure unit">
				{#each PRESSURE_CHOICES as c (c.label)}
					<label class={CHIP}
						><input
							type="radio"
							class="sr-only"
							name="pressure-{draft.channel}"
							checked={chosenPressure === c.label}
							onchange={() => pickPressure(c.label)}
						/>
						{c.label}</label
					>
				{/each}
			</div>
		{/if}
		<div class="grid grid-cols-2 gap-3">
			<label class={FIELD}
				><span class="field-label">Unit (pint)</span> <input class="field font-mono" bind:value={draft.unit} placeholder="e.g. psi, bar, kPa, degC" /></label
			>
			<label class={FIELD}
				><span class="field-label">Gauge or absolute</span>
				<select class="field" bind:value={draft.gauge_or_abs}>
					<option value="gauge">gauge</option>
					<option value="absolute">absolute</option>
					<option value="n/a">not a pressure</option>
					<option value="unknown">unknown</option>
				</select>
			</label>
		</div>
		{#if draft.gauge_or_abs === 'gauge'}
			<div class="grid grid-cols-2 gap-3">
				<label class={FIELD}
					><span class="field-label">Ambient reference</span>
					<select class="field" bind:value={draft.ambient_condition}>
						<option value={null}>choose…</option>
						<option value="SEA_LEVEL">sea level</option>
						<option value="VACUUM_CHAMBER">vacuum chamber</option>
						<option value="AMBIENT_RECORDED">recorded ambient channel</option>
						<option value="UNKNOWN">unknown</option>
					</select>
				</label>
				<label class={FIELD}
					><span class="field-label">Ambient pressure, bar(a)</span>
					<input class="field num font-mono" type="number" step="0.0001" bind:value={draft.ambient_pressure_bar_abs} placeholder="1.01325" /></label
				>
			</div>
		{/if}
		<label class={FIELD}
			><span class="field-label">Custom expression</span>
			<input
				class="field font-mono"
				bind:value={draft.expression}
				placeholder="val * 0.0689476 + 1.01325"
				onchange={(e) => {
					if (draft.action === 'set_unit' && !(e.currentTarget as HTMLInputElement).value) draft.expression = null;
				}}
			/></label
		>
	</fieldset>
{:else if draft.action === 'set_fact_unit'}
	<label class={FIELD}><span class="field-label">Unit</span> <input class="field font-mono" bind:value={draft.unit} placeholder="leave empty to keep as text" /></label>
{:else if draft.action === 'map_columns'}
	<div class="overflow-x-auto rounded-md border">
		<table class="w-full text-[13px]" aria-label="Column mapping">
			<thead>
				<tr class="bg-muted/60 text-muted-foreground text-left text-xs">
					<th class="px-2 py-1 font-medium">Col</th><th class="px-2 py-1 font-medium">Canonical name</th><th class="px-2 py-1 font-medium">Unit</th>
					<th class="px-2 py-1 font-medium">Quantity</th><th class="px-2 py-1 font-medium">Time</th><th><span class="sr-only">Remove</span></th>
				</tr>
			</thead>
			<tbody>
				{#each draft.columns as column, i (i)}
					<tr class="border-t">
						<td class="px-1.5 py-1"><input type="number" min="0" class="field h-7 w-16 font-mono" aria-label="Column index" bind:value={column.index} /></td>
						<td class="px-1.5 py-1"
							><input class="field h-7 min-w-36 font-mono" aria-label="Canonical name" bind:value={column.canonical_name} placeholder="pt_101_chamber" /></td
						>
						<td class="px-1.5 py-1"><input aria-label="Unit" class="field h-7 w-20 font-mono" bind:value={column.unit} /></td>
						<td class="px-1.5 py-1"><input aria-label="Quantity" class="field h-7 w-24" bind:value={column.quantity} /></td>
						<td class="px-2 py-1 text-center"><input type="checkbox" aria-label="Time column" bind:checked={column.is_time} /></td>
						<td class="px-1 py-1"
							><Button
								variant="ghost"
								size="icon-xs"
								aria-label="Remove column"
								onclick={() => draft.action === 'map_columns' && draft.columns.splice(i, 1)}><XIcon /></Button
							></td
						>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	<Button
		variant="outline"
		size="sm"
		class="justify-self-start"
		onclick={() =>
			draft.action === 'map_columns' &&
			draft.columns.push({ index: draft.columns.length, canonical_name: '', unit: null, quantity: null, is_time: false })}
		><PlusIcon /> Add column</Button
	>
{:else if draft.action === 'map_json_keys'}
	{#if Object.keys(draft.key_to_section).length}
		<ul class="m-0 grid list-none gap-0.5 rounded-md border p-2 text-[13px]">
			{#each Object.entries(draft.key_to_section) as [key, section] (key)}
				<li><code>{key}</code> <span class="text-muted-foreground">→</span> {section}</li>
			{/each}
		</ul>
	{/if}
	<div class="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
		<label class={FIELD}><span class="field-label">Key</span> <input class="field font-mono" bind:value={newKey} /></label>
		<label class={FIELD}><span class="field-label">Section</span> <input class="field" bind:value={newSection} /></label>
		<Button
			variant="outline"
			disabled={!newKey || !newSection}
			onclick={() => {
				if (draft.action !== 'map_json_keys') return;
				draft.key_to_section = { ...draft.key_to_section, [newKey]: newSection };
				newKey = '';
				newSection = '';
			}}>Add mapping</Button
		>
	</div>
	<label class={FIELD}><span class="field-label">Save as report schema</span> <input class="field" bind:value={draft.save_as_schema} placeholder="optional name" /></label>
{:else if draft.action === 'set_value'}
	<div class="grid grid-cols-2 gap-3">
		<label class={FIELD}><span class="field-label">Value</span> <input class="field font-mono" bind:value={draft.value} disabled={draft.illegible} /></label>
		<label class={FIELD}><span class="field-label">Unit</span> <input class="field font-mono" bind:value={draft.unit} disabled={draft.illegible} /></label>
	</div>
	<label class="flex items-center gap-2 text-[13px]"><input type="checkbox" bind:checked={draft.illegible} /> Illegible (stored as unknown)</label>
{:else if draft.action === 'choose_table'}
	<div class="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Table version">
		<label class={CHIP}><input type="radio" class="sr-only" bind:group={draft.choice} value="A" /> A (TableFormer)</label>
		<label class={CHIP}><input type="radio" class="sr-only" bind:group={draft.choice} value="B" /> B (vision model)</label>
	</div>
{:else if draft.action === 'choose_source'}
	<div class="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Authoritative source">
		<label class={CHIP}><input type="radio" class="sr-only" bind:group={draft.choice} value="A" /> Source A</label>
		<label class={CHIP}><input type="radio" class="sr-only" bind:group={draft.choice} value="B" /> Source B</label>
	</div>
{:else if draft.action === 'mark_superseded'}
	<div class="flex flex-wrap items-center gap-1.5" role="radiogroup" aria-label="Superseded document">
		<span class="field-label">The older one is</span>
		{#each documents as doc (doc.doc_id)}
			<label class={CHIP}><input type="radio" class="sr-only" bind:group={draft.superseded_doc_id} value={doc.doc_id} /> {doc.label}</label>
		{/each}
	</div>
{:else if draft.action === 'use_replacement'}
	<p class="text-muted-foreground m-0 text-[13px]">Uploading a readable copy needs the upload endpoint, which does not exist yet. Skip or mark junk instead.</p>
{:else if draft.action === 'redact'}
	<p class="text-muted-foreground m-0 text-[13px]">The redaction editor arrives with the sensitive-content panes.</p>
{/if}
