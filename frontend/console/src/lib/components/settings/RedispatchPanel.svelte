<script lang="ts">
	// Settings › Routes "re-process affected documents" (file 08 §3.2): count first, then re-dispatch.
	import { ApiError, redispatchPreview, redispatchRoute, type RedispatchPreview } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import { ROUTES } from './sources';

	let route = $state<string>('A1');
	let preview = $state<RedispatchPreview | null>(null);
	let error = $state('');
	let notice = $state('');
	let busy = $state(false);

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	async function act(run: () => Promise<void>) {
		busy = true;
		error = '';
		notice = '';
		try {
			await run();
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	const count = () => act(async () => void (preview = await redispatchPreview(route)));
	const confirm = () =>
		act(async () => {
			const result = await redispatchRoute(route);
			preview = null;
			notice = `Route ${result.route}: ${result.redispatched} documents sent for re-processing${result.started ? '' : ' (the queue was unreachable; the next sweep starts them)'}.`;
		});
</script>

<section aria-label="Re-process documents" class="panel grid gap-2 p-3">
	<h3 class="eyebrow m-0">Re-process affected documents</h3>
	<p class="text-muted-foreground m-0 text-sm">After a parser or configuration change, re-run every committed document of one route. The count comes first.</p>
	{#if error}<Notice tone="error">{error}</Notice>{/if}
	{#if notice}<Notice tone="success">{notice}</Notice>{/if}
	<div class="flex flex-wrap items-end gap-2">
		<label class="field-label grid gap-1"
			>Route
			<select class="field w-24" bind:value={route} onchange={() => (preview = null)}>
				{#each ROUTES as r (r)}<option value={r}>{r}</option>{/each}
			</select>
		</label>
		<Button size="sm" variant="outline" disabled={busy} onclick={count}>Count documents</Button>
	</div>
	{#if preview}
		<p class="m-0 text-sm">
			Route {preview.route}: <strong>{preview.documents}</strong> documents{preview.sample.length ? `, e.g. ${preview.sample.slice(0, 5).join(', ')}` : ''}.
		</p>
		<div class="flex gap-2">
			<Button size="sm" disabled={busy || preview.documents === 0} onclick={confirm}>Re-process {preview.documents} documents</Button>
			<Button size="sm" variant="ghost" disabled={busy} onclick={() => (preview = null)}>Cancel</Button>
		</div>
	{/if}
</section>
