<script lang="ts">
	import type { DryRunResponse } from '$lib/api_endpoint';

	interface Props {
		result: DryRunResponse;
	}

	let { result }: Props = $props();
	const num = (v: number | null | undefined) => (v === null || v === undefined ? '—' : Number(v.toPrecision(5)).toString());
</script>

<section class="dry-run" aria-label="Preview">
	{#if result.channels?.length}
		<table>
			<thead><tr><th>Channel</th><th>Unit</th><th>min</th><th>max</th><th>mean</th><th>p99</th><th>Sanity</th></tr></thead>
			<tbody>
				{#each result.channels as c (c.canonical_name)}
					<tr class:ok={c.within_sanity === true} class:bad={c.within_sanity === false}>
						<td>{c.canonical_name}</td>
						<td>{c.unit_si}</td>
						<td>{num(c.stat_min)}</td>
						<td>{num(c.stat_max)}</td>
						<td>{num(c.stat_mean)}</td>
						<td>{num(c.stat_p99)}</td>
						<td
							>{c.within_sanity === null ? 'no bounds' : c.within_sanity ? 'within' : 'outside'}
							{#if c.sanity_min !== null || c.sanity_max !== null}({num(c.sanity_min)} … {num(c.sanity_max)}){/if}</td
						>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
	<p>Affects {result.affected_documents} document{result.affected_documents === 1 ? '' : 's'}.</p>
	{#if result.new_flags?.length}
		<p class="bad" role="alert">
			Would raise {result.new_flags.length} new flag{result.new_flags.length === 1 ? '' : 's'}:
			{result.new_flags.map((f) => `${f.flag_type} (${f.severity})`).join(', ')}
		</p>
	{/if}
	{#each result.messages ?? [] as message, i (i)}<p>{message}</p>{/each}
</section>

<style>
	.dry-run {
		font-size: 0.8rem;
		display: grid;
		gap: 0.3rem;
	}
	table {
		border-collapse: collapse;
	}
	th,
	td {
		border: 1px solid var(--border);
		padding: 0.15rem 0.4rem;
		text-align: left;
	}
	.ok td:last-child {
		color: var(--ok);
	}
	.bad,
	.bad td:last-child {
		color: var(--hard);
	}
	p {
		margin: 0;
	}
</style>
