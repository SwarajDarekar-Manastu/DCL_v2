<script lang="ts">
	// Fallback renderer for evidence kinds without a dedicated pane: every key is shown, rows as tables.
	interface Props {
		evidence: Record<string, unknown>;
	}

	let { evidence }: Props = $props();

	const isRowTable = (v: unknown): v is unknown[][] => Array.isArray(v) && v.length > 0 && v.every(Array.isArray);
	const isObjectTable = (v: unknown): v is Record<string, unknown>[] =>
		Array.isArray(v) && v.length > 0 && v.every((x) => x !== null && typeof x === 'object' && !Array.isArray(x));
	const columnsOf = (rows: Record<string, unknown>[]) => [...new Set(rows.flatMap((r) => Object.keys(r)))];
	const cell = (v: unknown) => (v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v));
	const label = (key: string) => key.replaceAll('_', ' ');
</script>

<section class="grid content-start gap-3 text-sm" aria-label="Evidence">
	{#if Object.keys(evidence).length === 0}
		<p class="text-muted-foreground m-0">No evidence attached to this flag.</p>
	{/if}
	{#each Object.entries(evidence).filter(([key]) => key !== 'kind') as [key, value] (key)}
		<div class="grid gap-1">
			<h4 class="eyebrow">{label(key)}</h4>
			{#if isRowTable(value)}
				<div class="overflow-x-auto rounded-md border">
					<table class="num w-full font-mono text-xs">
						<tbody>
							{#each value as row, r (r)}
								<tr class="border-t first:border-t-0">{#each row as v, c (c)}<td class="px-2.5 py-0.5 whitespace-nowrap">{cell(v)}</td>{/each}</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else if isObjectTable(value)}
				<div class="overflow-x-auto rounded-md border">
					<table class="w-full text-xs">
						<thead
							><tr class="bg-muted/60"
								>{#each columnsOf(value) as col (col)}<th class="text-muted-foreground px-2.5 py-1 text-left font-medium whitespace-nowrap">{label(col)}</th
									>{/each}</tr
							></thead
						>
						<tbody>
							{#each value as row, r (r)}
								<tr class="border-t">{#each columnsOf(value) as col (col)}<td class="px-2.5 py-1 whitespace-nowrap">{cell(row[col])}</td>{/each}</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else if Array.isArray(value) && value.every((v) => typeof v !== 'object')}
				<p class="m-0">{value.join(', ')}</p>
			{:else if typeof value === 'string' && value.includes('\n')}
				<pre class="code-block m-0 max-h-64">{value}</pre>
			{:else if value !== null && typeof value === 'object'}
				<pre class="code-block m-0 max-h-64">{JSON.stringify(value, null, 2)}</pre>
			{:else}
				<p class="m-0">{cell(value)}</p>
			{/if}
		</div>
	{/each}
</section>
