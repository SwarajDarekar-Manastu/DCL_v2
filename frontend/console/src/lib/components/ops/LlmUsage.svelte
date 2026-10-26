<script lang="ts">
	// Gemini use and cost over the last days (GET /ops/llm-usage): totals per model, then per task, costliest first.
	// A cost is what each call recorded at the price then in force (Settings › models.prices).
	import { ApiError, getLlmUsage, type LlmUsage } from '$lib/api_endpoint';
	import Notice from '$lib/components/shell/Notice.svelte';

	const PERIODS = [1, 7, 30, 90];
	let days = $state(7);
	let usage = $state<LlmUsage | null>(null);
	let error = $state('');

	$effect(() => {
		getLlmUsage(days)
			.then((u) => {
				usage = u;
				error = '';
			})
			.catch((e) => (error = e instanceof ApiError ? e.detail : String(e)));
	});

	const int = (n: number) => n.toLocaleString('en-US');
	const usd = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `$${v.toFixed(v < 1 ? 4 : 2)}`);

	let tasks = $derived.by(() => {
		const byTask = new Map<string, { model: string; purpose: string; calls: number; billed: number; hits: number; errors: number; tokensOut: number; cost: number | null }>();
		for (const r of usage?.rows ?? []) {
			const key = `${r.model} ${r.purpose}`;
			const t = byTask.get(key) ?? { model: r.model, purpose: r.purpose, calls: 0, billed: 0, hits: 0, errors: 0, tokensOut: 0, cost: null };
			t.calls += r.calls;
			t.billed += r.billed_calls;
			t.hits += r.cache_hits;
			t.errors += r.errors;
			t.tokensOut += r.output_tokens;
			if (r.cost_usd !== null && r.cost_usd !== undefined) t.cost = (t.cost ?? 0) + r.cost_usd;
			byTask.set(key, t);
		}
		return [...byTask.values()].sort((a, b) => (b.cost ?? 0) - (a.cost ?? 0) || b.billed - a.billed);
	});
	let unpriced = $derived((usage?.by_model ?? []).filter((m) => m.unpriced_calls > 0));
</script>

<section class="panel" aria-labelledby="usage-title">
	<div class="panel-header">
		<div>
			<h2 id="usage-title" class="panel-title">
				Gemini use and cost <span class="text-muted-foreground font-normal">{usage ? `· ${usd(usage.total_cost_usd)}` : ''}</span>
			</h2>
			<p class="text-muted-foreground m-0 text-xs">
				Billed calls include failed replies that still used tokens. Cache hits cost nothing. Days are UTC.
			</p>
		</div>
		<div class="flex gap-1" role="group" aria-label="Period">
			{#each PERIODS as p (p)}
				<button type="button" class="period {p === days ? 'active' : ''}" aria-pressed={p === days} onclick={() => (days = p)}>
					{p === 1 ? 'Today' : `${p} days`}
				</button>
			{/each}
		</div>
	</div>
	{#if error}<div class="px-4 py-3"><Notice tone="error">{error}</Notice></div>{/if}
	{#if unpriced.length}
		<div class="px-4 pt-3">
			<Notice tone="warning">
				{unpriced.map((m) => `${int(m.unpriced_calls)} ${m.model}`).join(', ')} billed calls ran while the model had no price, so their cost is
				missing from the total. Add the model under Settings › models.prices.
			</Notice>
		</div>
	{/if}
	{#if usage}
		<table class="data-table" aria-label="Per model">
			<thead>
				<tr>
					<th scope="col">Model</th><th scope="col" class="num">Calls</th><th scope="col" class="num">Billed</th><th scope="col" class="num">Cache hits</th><th scope="col" class="num">Errors</th><th scope="col" class="num">Tokens in / out</th><th scope="col" class="num">Cost</th>
				</tr>
			</thead>
			<tbody>
				{#each usage.by_model as m (m.model)}
					<tr>
						<td class="font-mono text-xs">{m.model}</td>
						<td class="num font-mono">{int(m.calls)}</td>
						<td class="num font-mono">{int(m.billed_calls)}</td>
						<td class="num font-mono">{int(m.cache_hits)}</td>
						<td class="num font-mono {m.errors ? 'text-hard' : ''}">{int(m.errors)}</td>
						<td class="num font-mono">{int(m.input_tokens)} / {int(m.output_tokens)}</td>
						<td class="num font-mono">{usd(m.cost_usd)}</td>
					</tr>
				{:else}<tr><td colspan="7" class="text-muted-foreground text-center">No model calls in this period.</td></tr>{/each}
			</tbody>
		</table>
		{#if tasks.length}
			<details class="border-t">
				<summary class="cursor-pointer px-4 py-2 text-sm">Per task ({tasks.length})</summary>
				<table class="data-table" aria-label="Per task">
					<thead>
						<tr>
							<th scope="col">Task</th><th scope="col">Model</th><th scope="col" class="num">Billed</th><th scope="col" class="num">Cache hits</th><th scope="col" class="num">Errors</th><th scope="col" class="num">Tokens out</th><th scope="col" class="num">Cost</th>
						</tr>
					</thead>
					<tbody>
						{#each tasks as t (t.model + t.purpose)}
							<tr>
								<td class="font-mono text-xs">{t.purpose}</td>
								<td class="font-mono text-xs">{t.model}</td>
								<td class="num font-mono">{int(t.billed)}</td>
								<td class="num font-mono">{int(t.hits)}</td>
								<td class="num font-mono {t.errors ? 'text-hard' : ''}">{int(t.errors)}</td>
								<td class="num font-mono">{int(t.tokensOut)}</td>
								<td class="num font-mono">{usd(t.cost)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</details>
		{/if}
	{/if}
</section>

<style>
	.period {
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 2px 8px;
		font-size: 12px;
		background: transparent;
		color: var(--muted-foreground);
	}
	.period.active {
		color: var(--foreground);
		border-color: var(--foreground);
	}
</style>
