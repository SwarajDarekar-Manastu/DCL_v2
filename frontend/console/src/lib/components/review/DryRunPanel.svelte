<script lang="ts">
	import type { DryRunResponse } from '$lib/api_endpoint';

	interface Props {
		result: DryRunResponse;
	}

	let { result }: Props = $props();
	const num = (v: number | null | undefined) => (v === null || v === undefined ? '—' : Number(v.toPrecision(5)).toString());
</script>

<section class="bg-muted/40 grid gap-2 rounded-md border p-3 text-[13px]" aria-label="Preview">
	{#if result.channels?.length}
		<div class="overflow-x-auto rounded-md border bg-background">
			<table class="w-full text-xs">
				<thead>
					<tr class="bg-muted/60 text-muted-foreground text-left">
						<th class="px-2.5 py-1 font-medium">Channel</th><th class="px-2.5 py-1 font-medium">Unit</th>
						<th class="px-2.5 py-1 text-right font-medium">min</th><th class="px-2.5 py-1 text-right font-medium">max</th>
						<th class="px-2.5 py-1 text-right font-medium">mean</th><th class="px-2.5 py-1 text-right font-medium">p99</th>
						<th class="px-2.5 py-1 font-medium">Sanity</th>
					</tr>
				</thead>
				<tbody>
					{#each result.channels as c (c.canonical_name)}
						<tr class="border-t">
							<td class="px-2.5 py-1 font-mono">{c.canonical_name}</td>
							<td class="px-2.5 py-1 font-mono">{c.unit_si}</td>
							<td class="num px-2.5 py-1 text-right font-mono">{num(c.stat_min)}</td>
							<td class="num px-2.5 py-1 text-right font-mono">{num(c.stat_max)}</td>
							<td class="num px-2.5 py-1 text-right font-mono">{num(c.stat_mean)}</td>
							<td class="num px-2.5 py-1 text-right font-mono">{num(c.stat_p99)}</td>
							<td
								class={[
									'px-2.5 py-1 whitespace-nowrap',
									c.within_sanity === true && 'text-ok font-medium',
									c.within_sanity === false && 'text-hard font-medium',
									c.within_sanity === null && 'text-muted-foreground'
								]}
								>{c.within_sanity === null ? 'no bounds' : c.within_sanity ? 'within' : 'outside'}
								{#if c.sanity_min !== null || c.sanity_max !== null}<span class="num font-mono font-normal">({num(c.sanity_min)} … {num(c.sanity_max)})</span>{/if}</td
							>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
	<p class="m-0">Affects <strong class="num font-semibold">{result.affected_documents}</strong> document{result.affected_documents === 1 ? '' : 's'}.</p>
	{#if result.new_flags?.length}
		<p class="text-hard m-0 font-medium" role="alert">
			Would raise {result.new_flags.length} new flag{result.new_flags.length === 1 ? '' : 's'}:
			{result.new_flags.map((f) => `${f.flag_type} (${f.severity})`).join(', ')}
		</p>
	{/if}
	{#each result.messages ?? [] as message, i (i)}<p class="text-muted-foreground m-0">{message}</p>{/each}
</section>
