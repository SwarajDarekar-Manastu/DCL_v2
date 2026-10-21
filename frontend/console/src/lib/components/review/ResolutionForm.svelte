<script lang="ts">
	import type { Resolution } from '$lib/api_endpoint';
	import { PRESSURE_CHOICES } from './resolution';

	interface Props {
		draft: Resolution;
	}

	let { draft = $bindable() }: Props = $props();

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
</script>

{#if draft.action === 'set_unit'}
	<fieldset>
		<legend>Unit of channel <input class="inline" aria-label="Channel" bind:value={draft.channel} /></legend>
		<label>Quantity <input bind:value={draft.quantity} /></label>
		{#if draft.quantity === 'pressure'}
			<div class="chips" role="radiogroup" aria-label="Pressure unit">
				{#each PRESSURE_CHOICES as c (c.label)}
					<label class="chip"
						><input type="radio" name="pressure-{draft.channel}" checked={chosenPressure === c.label} onchange={() => pickPressure(c.label)} />
						{c.label}</label
					>
				{/each}
			</div>
		{/if}
		<label>Unit (pint) <input bind:value={draft.unit} placeholder="e.g. psi, bar, kPa, degC" /></label>
		<label
			>Gauge or absolute
			<select bind:value={draft.gauge_or_abs}>
				<option value="gauge">gauge</option>
				<option value="absolute">absolute</option>
				<option value="n/a">not a pressure</option>
				<option value="unknown">unknown</option>
			</select>
		</label>
		{#if draft.gauge_or_abs === 'gauge'}
			<label
				>Ambient reference
				<select bind:value={draft.ambient_condition}>
					<option value={null}>choose…</option>
					<option value="SEA_LEVEL">sea level</option>
					<option value="VACUUM_CHAMBER">vacuum chamber</option>
					<option value="AMBIENT_RECORDED">recorded ambient channel</option>
					<option value="UNKNOWN">unknown</option>
				</select>
			</label>
			<label
				>Ambient pressure, bar(a) <input
					type="number"
					step="0.0001"
					bind:value={draft.ambient_pressure_bar_abs}
					placeholder="1.01325"
				/></label
			>
		{/if}
		<label
			>Custom expression <input
				bind:value={draft.expression}
				placeholder="val * 0.0689476 + 1.01325"
				onchange={(e) => {
					if (draft.action === 'set_unit' && !(e.currentTarget as HTMLInputElement).value) draft.expression = null;
				}}
			/></label
		>
	</fieldset>
{:else if draft.action === 'set_fact_unit'}
	<label>Unit <input bind:value={draft.unit} placeholder="leave empty to keep as text" /></label>
{:else if draft.action === 'map_columns'}
	<table class="grid" aria-label="Column mapping">
		<thead><tr><th>Col</th><th>Canonical name</th><th>Unit</th><th>Quantity</th><th>Time</th><th></th></tr></thead>
		<tbody>
			{#each draft.columns as column, i (i)}
				<tr>
					<td><input type="number" min="0" class="narrow" aria-label="Column index" bind:value={column.index} /></td>
					<td><input aria-label="Canonical name" bind:value={column.canonical_name} placeholder="pt_101_chamber" /></td>
					<td><input aria-label="Unit" class="narrow" bind:value={column.unit} /></td>
					<td><input aria-label="Quantity" class="narrow" bind:value={column.quantity} /></td>
					<td><input type="checkbox" aria-label="Time column" bind:checked={column.is_time} /></td>
					<td
						><button type="button" aria-label="Remove column" onclick={() => draft.action === 'map_columns' && draft.columns.splice(i, 1)}
							>×</button
						></td
					>
				</tr>
			{/each}
		</tbody>
	</table>
	<button
		type="button"
		onclick={() =>
			draft.action === 'map_columns' &&
			draft.columns.push({ index: draft.columns.length, canonical_name: '', unit: null, quantity: null, is_time: false })}
		>Add column</button
	>
{:else if draft.action === 'map_json_keys'}
	<ul class="keys">
		{#each Object.entries(draft.key_to_section) as [key, section] (key)}
			<li><code>{key}</code> → {section}</li>
		{/each}
	</ul>
	<label>Key <input bind:value={newKey} /></label>
	<label>Section <input bind:value={newSection} /></label>
	<button
		type="button"
		disabled={!newKey || !newSection}
		onclick={() => {
			if (draft.action !== 'map_json_keys') return;
			draft.key_to_section = { ...draft.key_to_section, [newKey]: newSection };
			newKey = '';
			newSection = '';
		}}>Add mapping</button
	>
	<label>Save as report schema <input bind:value={draft.save_as_schema} placeholder="optional name" /></label>
{:else if draft.action === 'set_value'}
	<label>Value <input bind:value={draft.value} disabled={draft.illegible} /></label>
	<label>Unit <input bind:value={draft.unit} disabled={draft.illegible} /></label>
	<label class="check"><input type="checkbox" bind:checked={draft.illegible} /> Illegible (stored as unknown)</label>
{:else if draft.action === 'choose_table'}
	<div class="chips" role="radiogroup" aria-label="Table version">
		<label class="chip"><input type="radio" bind:group={draft.choice} value="A" /> A (TableFormer)</label>
		<label class="chip"><input type="radio" bind:group={draft.choice} value="B" /> B (vision model)</label>
	</div>
{:else if draft.action === 'choose_source'}
	<div class="chips" role="radiogroup" aria-label="Authoritative source">
		<label class="chip"><input type="radio" bind:group={draft.choice} value="A" /> Source A</label>
		<label class="chip"><input type="radio" bind:group={draft.choice} value="B" /> Source B</label>
	</div>
{:else if draft.action === 'mark_superseded'}
	<label>Superseded document id <input bind:value={draft.superseded_doc_id} placeholder="uuid" /></label>
{:else if draft.action === 'use_replacement'}
	<p class="note">Uploading a readable copy needs the upload endpoint, which does not exist yet. Skip or mark junk instead.</p>
{:else if draft.action === 'redact'}
	<p class="note">The redaction editor arrives with the sensitive-content panes.</p>
{/if}

<style>
	fieldset {
		border: 0;
		padding: 0;
		margin: 0;
		display: grid;
		gap: 0.4rem;
	}
	legend {
		font-weight: 600;
		margin-bottom: 0.3rem;
	}
	label {
		display: grid;
		gap: 0.15rem;
		font-size: 0.82rem;
	}
	.check,
	.chip {
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem 0.8rem;
	}
	input:not([type='radio']):not([type='checkbox']),
	select {
		font: inherit;
		padding: 0.2rem 0.35rem;
		background: var(--bg);
		color: inherit;
		border: 1px solid var(--border);
		border-radius: 0.25rem;
	}
	.inline {
		width: 9rem;
	}
	.narrow {
		width: 5rem;
	}
	.grid {
		border-collapse: collapse;
		font-size: 0.8rem;
	}
	.grid th,
	.grid td {
		padding: 0.15rem 0.25rem;
		text-align: left;
	}
	.keys {
		padding-left: 1rem;
		font-size: 0.82rem;
	}
	.note {
		font-size: 0.82rem;
		opacity: 0.8;
	}
	button {
		justify-self: start;
		font: inherit;
		font-size: 0.8rem;
		padding: 0.2rem 0.6rem;
		cursor: pointer;
	}
</style>
