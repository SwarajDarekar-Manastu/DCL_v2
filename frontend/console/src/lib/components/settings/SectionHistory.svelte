<script lang="ts">
	// "Rollback to version" for a whole section (file 08 §3.2): every write to the section's keys, newest first;
	// restoring a moment writes, in one rollback, each key's version from that moment where it differs today.
	import { ApiError, rollbackSettings, settingHistory, type ConfigEntry } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import { restoreAt, sectionTimeline, summary, type SectionPoint, type SectionRestore } from './settings_form';

	interface Props {
		keys: string[];
		title: string;
		onRestored: (message: string) => void;
	}

	let { keys, title, onRestored }: Props = $props();
	let histories = $state<Record<string, ConfigEntry[]>>({});
	let error = $state('');
	let busy = $state(false);
	let chosen = $state<SectionPoint | null>(null);
	let plan = $state<SectionRestore | null>(null);

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

	$effect(() => {
		const wanted = keys;
		Promise.all(wanted.map(async (key) => [key, (await settingHistory(key)).items] as const))
			.then((pairs) => (histories = Object.fromEntries(pairs)))
			.catch((e) => (error = describe(e)));
	});

	let timeline = $derived(sectionTimeline(histories).slice(0, 40));

	function choose(point: SectionPoint) {
		chosen = point;
		plan = restoreAt(histories, point.at);
	}

	async function restore() {
		if (!chosen || !plan) return;
		busy = true;
		error = '';
		try {
			const result = await rollbackSettings({ versions: plan.versions, description: `restore ${title} to ${chosen.at.slice(0, 16)}` });
			onRestored(`${title} restored to ${chosen.at.slice(0, 16).replace('T', ' ')}: ${result.applied.map((a) => `${a.key} v${a.version}`).join(', ')}.`);
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}
</script>

<section class="grid gap-2" aria-label="Section history">
	{#if error}<Notice tone="error">{error}</Notice>{/if}
	<ol class="m-0 grid max-h-80 gap-1 overflow-y-auto p-0">
		{#each timeline as p (p.key + p.version)}
			<li class="flex list-none items-start gap-3 rounded-md border px-3 py-1.5 text-xs" class:bg-muted={chosen === p}>
				<span class="num w-32 shrink-0 font-mono">{p.at.slice(0, 16).replace('T', ' ')}</span>
				<span class="min-w-0 flex-1"
					><code>{p.key}</code> v{p.version} · {p.by}{#if p.description}<span class="text-muted-foreground">{` · ${p.description}`}</span>{/if}</span
				>
				<Button variant="outline" size="xs" disabled={busy} onclick={() => choose(p)}>Restore to here</Button>
			</li>
		{:else}
			<li class="text-muted-foreground list-none text-sm">No writes yet.</li>
		{/each}
	</ol>
	{#if chosen && plan}
		<div class="grid gap-2 rounded-md border px-3 py-2.5 text-sm" role="region" aria-label="Restore plan">
			{#if Object.keys(plan.versions).length}
				<p class="m-0">
					Restoring to {chosen.at.slice(0, 16).replace('T', ' ')} writes:
					{Object.entries(plan.versions)
						.map(([k, v]) => `${k} → v${v} (${summary(histories[k].find((e) => e.version === v)?.value, 60)})`)
						.join('; ')}
				</p>
			{:else}
				<p class="m-0">Every key already has the value it had then; nothing to write.</p>
			{/if}
			{#if plan.newer.length}<p class="text-muted-foreground m-0">Set after that moment and kept as they are: {plan.newer.join(', ')}.</p>{/if}
			<div class="flex gap-2">
				<Button size="sm" disabled={busy || !Object.keys(plan.versions).length} onclick={restore}>Restore section</Button>
				<Button size="sm" variant="ghost" disabled={busy} onclick={() => ((chosen = null), (plan = null))}>Cancel</Button>
			</div>
		</div>
	{/if}
</section>
