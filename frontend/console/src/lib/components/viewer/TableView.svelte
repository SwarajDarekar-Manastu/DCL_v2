<script lang="ts">
	interface Props {
		rows: string[][];
		headerRows: number;
		highlight: [number, number, number, number] | null;
		sheetName: string | null;
	}

	let { rows, headerRows, highlight, sheetName }: Props = $props();
	const lit = (r: number, c: number) =>
		highlight !== null && r >= highlight[0] && r <= highlight[2] && c >= highlight[1] && c <= highlight[3];
</script>

{#if sheetName}<p class="sheet">Sheet: {sheetName}</p>{/if}
<div class="scroll">
	<table>
		<tbody>
			{#each rows as row, r (r)}
				<tr>
					{#each row as cell, c (c)}
						{#if r < headerRows}
							<th class:lit={lit(r, c)}>{cell}</th>
						{:else}
							<td class:lit={lit(r, c)}>{cell}</td>
						{/if}
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.sheet {
		margin: 0 0 0.5rem;
		font-size: 0.85rem;
	}
	.scroll {
		overflow-x: auto;
	}
	table {
		border-collapse: collapse;
		background: var(--surface);
		font-size: 0.875rem;
	}
	th,
	td {
		border: 1px solid var(--border);
		padding: 0.3rem 0.5rem;
		white-space: nowrap;
	}
	.lit {
		background: rgb(245 158 11 / 0.25);
	}
</style>
