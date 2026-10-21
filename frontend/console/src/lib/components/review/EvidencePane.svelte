<script lang="ts">
	// Generic evidence renderer: S1 publishes typed evidence per flag type later; until then every key
	// is shown, tables of rows as tables, so a reviewer never loses information.
	interface Props {
		evidence: Record<string, unknown>;
		suggestion?: Record<string, unknown> | null;
	}

	let { evidence, suggestion = null }: Props = $props();

	const isRowTable = (v: unknown): v is unknown[][] => Array.isArray(v) && v.length > 0 && v.every(Array.isArray);
	const isObjectTable = (v: unknown): v is Record<string, unknown>[] =>
		Array.isArray(v) && v.length > 0 && v.every((x) => x !== null && typeof x === 'object' && !Array.isArray(x));
	const columnsOf = (rows: Record<string, unknown>[]) => [...new Set(rows.flatMap((r) => Object.keys(r)))];
	const cell = (v: unknown) => (v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v));
	const label = (key: string) => key.replaceAll('_', ' ');
</script>

<section class="evidence" aria-label="Evidence">
	{#if Object.keys(evidence).length === 0}
		<p class="muted">No evidence attached to this flag.</p>
	{/if}
	{#each Object.entries(evidence) as [key, value] (key)}
		<div class="item">
			<h4>{label(key)}</h4>
			{#if isRowTable(value)}
				<div class="scroll">
					<table>
						<tbody>
							{#each value as row, r (r)}
								<tr>{#each row as v, c (c)}<td>{cell(v)}</td>{/each}</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else if isObjectTable(value)}
				<div class="scroll">
					<table>
						<thead><tr>{#each columnsOf(value) as col (col)}<th>{label(col)}</th>{/each}</tr></thead>
						<tbody>
							{#each value as row, r (r)}
								<tr>{#each columnsOf(value) as col (col)}<td>{cell(row[col])}</td>{/each}</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else if Array.isArray(value) && value.every((v) => typeof v !== 'object')}
				<p>{value.join(', ')}</p>
			{:else if typeof value === 'string' && value.includes('\n')}
				<pre>{value}</pre>
			{:else if value !== null && typeof value === 'object'}
				<pre>{JSON.stringify(value, null, 2)}</pre>
			{:else}
				<p>{cell(value)}</p>
			{/if}
		</div>
	{/each}
	{#if suggestion}
		<div class="item suggestion">
			<h4>Suggested{typeof suggestion.confidence === 'number' ? ` (${suggestion.confidence.toFixed(2)})` : ''}</h4>
			<pre>{JSON.stringify(suggestion, null, 2)}</pre>
		</div>
	{/if}
</section>

<style>
	.evidence {
		display: grid;
		gap: 0.6rem;
		font-size: 0.82rem;
	}
	h4 {
		margin: 0 0 0.2rem;
		font-size: 0.78rem;
		text-transform: capitalize;
		opacity: 0.75;
	}
	p,
	pre {
		margin: 0;
	}
	pre {
		white-space: pre-wrap;
		font-size: 0.78rem;
	}
	.scroll {
		overflow-x: auto;
	}
	table {
		border-collapse: collapse;
	}
	th,
	td {
		border: 1px solid var(--border);
		padding: 0.15rem 0.4rem;
		white-space: nowrap;
		text-align: left;
	}
	.suggestion {
		border-left: 3px solid var(--warn);
		padding-left: 0.5rem;
	}
	.muted {
		opacity: 0.7;
	}
</style>
