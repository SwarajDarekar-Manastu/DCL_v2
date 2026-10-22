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
	const LIT = '[&.lit]:bg-info-bg [&.lit]:text-foreground [&.lit]:shadow-[inset_0_0_0_1.5px_var(--info)]';
</script>

{#if sheetName}<p class="text-muted-foreground m-0 mb-2 text-xs">Sheet: {sheetName}</p>{/if}
<div class="table-scroll bg-background rounded-md border">
	<table class="data-table">
		<tbody>
			{#each rows as row, r (r)}
				<tr>
					{#each row as cell, c (c)}
						{#if r < headerRows}
							<th class="border-r last:border-r-0 {LIT}" class:lit={lit(r, c)}>{cell}</th>
						{:else}
							<td class="num border-r py-1.5 whitespace-nowrap last:border-r-0 {LIT}" class:lit={lit(r, c)}>{cell}</td>
						{/if}
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
</div>
